import os
import time
import json
import re
import threading
import chromadb
import numpy as np
import pandas as pd
import streamlit as st
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor

# =====================================================================
# 🔒 1. 初始化页面配置与强效会话隔离（防止冷启动自动跑历史任务）
# =====================================================================
st.set_page_config(page_title="Jerry-Insight Pro v3.5+", layout="wide", page_icon="🛡️")

# ⚡ 核心修复：如果检测到是新进来的页面，或者没有明确的动作，强制把 active_query 锁死为 None，不读取历史脏数据
if "active_query" not in st.session_state:
    st.session_state["active_query"] = None
if "has_searched" not in st.session_state:
    st.session_state["has_searched"] = False

# =====================================================================
# 🛠️ 2. 初代路由、去噪组件与状态机/爬虫组件引入
# =====================================================================
from bs4 import BeautifulSoup  
from core.router import classify_intent, clean_query_to_entity
from core.memory_manager import AdvancedMemoryManager
from core.hybrid_retriever import JaccardHybridRetriever
from tools.mcp_server import JerryMcpServer

from core.brain import ask_llm
from tools.search import web_search_pro
from tools.price_crawler import crawl_smzdm_price  
from core.jerry_fsm_agent import JerryFSMAgent     
from data.sql_db import save_audit_log
from dotenv import load_dotenv

# 💡 【精准对齐 Secrets 截图】：自动适配您在网页端填写的变量名
load_dotenv()
WECHAT_TOKEN = st.secrets.get("PUSH_TOKEN", os.getenv("PUSH_TOKEN"))
DINGTALK_TOKEN = st.secrets.get("DING_WEBHOOK", os.getenv("DING_WEBHOOK"))

try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): 
        if not WECHAT_TOKEN: return "未检测到 notify 微信零件且未配置 Secret Token"
        return "本地零件未就绪"
    def push_dingtalk(content, title=None): 
        if not DINGTALK_TOKEN: return "未检测到 notify 钉钉零件且未配置 Secret Token"
        return "本地零件未就绪"

FILE_LOCK = threading.Lock()
PROFILE_FILE = "jerry_profile.json"

if 'ASYNC_EXECUTOR' not in st.session_state:
    st.session_state['ASYNC_EXECUTOR'] = ThreadPoolExecutor(max_workers=8)

@st.cache_resource
def init_chroma_and_inject_profiles():
    if os.path.exists("/mount/src/jerry-insight") or "STREAMLIT_RUNTIME_ENV" in os.environ:
        from chromadb.config import Settings
        chroma_client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    else:
        chroma_client = chromadb.PersistentClient(path="./bankv2")
    collection = chroma_client.get_or_create_collection(name="jerry_history")
    try:
        check_exist = collection.get(ids=["rule_earphone", "rule_camera", "rule_drone", "rule_general"])
        if not check_exist or not check_exist['ids']:
            collection.add(
                documents=[
                    "Jerry专属耳机雷点偏好规则：当前每月生活费2000元。由于耳道极其敏感，极度反感并规避【入耳式】耳机，只接受头戴式或半入耳式。耳机品类极度关注高性价比、省钱 and 极致舒适度。",
                    "Jerry专属相机与数码消费偏好规则：当前每月生活费2000元。极度关注长期耐用性、保值率与售后红利保障，由于预算有限，买数码产品必须极其谨慎，杜绝冲动消费。",
                    "Jerry专属无人机航拍偏好规则：当前每月生活费2000元. 消费心理：关注飞行安全风险与续han能力（炸机成本太高，无法承受），偏好傻瓜式的一键直直出大片体验。",
                    "Jerry专属通用账务基本消费理念规则：当前每月生活费2000元。由于预算敏感，极度关注产品的高性价比、耐用性，拒绝高价溢价，对低质山寨产品零容忍。"
                ],
                metadatas=[{"category": "profile_rule", "tag": "耳机"}, {"category": "profile_rule", "tag": "相机"}, {"category": "profile_rule", "tag": "无人机"}, {"category": "profile_rule", "tag": "通用"}],
                ids=["rule_earphone", "rule_camera", "rule_drone", "rule_general"]
            )
    except Exception as e:
        print(f"画像基底向量初始化提示: {e}")
    return collection

memory_collection = init_chroma_and_inject_profiles()
hybrid_retriever = JaccardHybridRetriever(memory_collection)

def get_dynamic_profile():
    with FILE_LOCK:
        if not os.path.exists(PROFILE_FILE):
            default_profile = {
                "user_name": "Jerry", "monthly_budget": 2000.0, "current_surplus": 850.0,  
                "fixed_expenses": {"饮食": 1200, "话费交通": 300}, "recent_purchases": ["维他柠檬茶", "蓝牙耳机"]
            }
            with open(PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(default_profile, f, ensure_ascii=False, indent=4)
            return default_profile
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

def update_profile_balance(amount, item_name):
    if os.path.exists(PROFILE_FILE):
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            profile = json.load(f)
    else:
        profile = {"user_name": "Jerry", "monthly_budget": 2000.0, "current_surplus": 850.0, "fixed_expenses": {"饮食": 1200, "话费交通": 300}, "recent_purchases": []}
    
    profile["current_surplus"] = round(profile["current_surplus"] - amount, 2)
    if item_name not in profile["recent_purchases"]:
        profile["recent_purchases"].append(item_name)
    with open(PROFILE_FILE, "w", encoding="utf-8") as f:
        json.dump(profile, f, ensure_ascii=False, indent=4)

mcp_gateway = JerryMcpServer(update_profile_balance, FILE_LOCK)

# 💡 【完美对齐大模型 URL 配置】：全自动动态抓取云端大模型秘钥与自定义网关
api_key = st.secrets.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY"))
base_url = st.secrets.get("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
openai_client = OpenAI(api_key=api_key, base_url=base_url)

if 'GLOBAL_MEMORY_MANAGER' not in st.session_state:
    st.session_state['GLOBAL_MEMORY_MANAGER'] = AdvancedMemoryManager(openai_client)

if 'SHORT_TERM_MEMORY' not in st.session_state: st.session_state['SHORT_TERM_MEMORY'] = []
if 'LAST_AUDIT' not in st.session_state: st.session_state['LAST_AUDIT'] = None
if 'PENDING_NOTIFY' not in st.session_state: st.session_state['PENDING_NOTIFY'] = None

def native_diversity_rerank(info_blocks):
    if not info_blocks: return []
    unique_blocks = []
    for current in info_blocks:
        text, url, score = current
        is_duplicate = False
        for existing in unique_blocks:
            set_a = set(text)
            set_b = set(existing[0])
            jaccard = len(set_a & set_b) / max(len(set_a | set_b), 1)
            if jaccard > 0.65: 
                is_duplicate = True
                break
        if not is_duplicate: unique_blocks.append(current)
    return unique_blocks[:4]


# ==========================================================
# 🌟 核心升级组件：JerryAgentHarness 状态机引擎
# ==========================================================
class JerryAgentHarness:
    def __init__(self, max_steps=4):
        self.client = openai_client
        self.model = "deepseek-chat" 
        self.max_steps = max_steps

    def run_harness(self, item_name, raw_info_text, profile_data, long_term_context, memory_ctx, status_widget=None):
        system_instruction = (
            "你是 Jerry-Insight 系统【首席风控审计官】，代号“铁算盘”。\n"
            "我们要审计的商品是：【" + item_name + "】。\n\n"
            "【❗⚠️ 核心死命令 ⚠️❗】\n"
            "你必须且只能输出标准的 JSON 块，禁止包含任何 JSON 之外的问候性、引言或多余寒暄。你的输出格式必须是以下两种之一：\n\n"
            "1. 如果需要继续追查搜索：\n"
            "{\"action\": \"Call_Web_Search\", \"action_input\": \"关键词\"}\n\n"
            "2. 如果情报足够，给出最终审计报告（核心内容）：\n"
            "{\n"
            "  \"action\": \"Final Answer\",\n"
            "  \"action_input\": \"【建议购买/建议避坑/持币观望】\\n\\n【深度审计理由】：\\n（在这里请结合 Jerry 的月度生活费剩余、历史消费习惯、商品性价比、全网行情，给出极其详尽、深刻、温情地消费心理审计与规避建议。）\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + item_name + "\\\", \\\"estimated_price\\\": 预估单价}\"\n"
            "}"
        )
        user_input_context = f"【历史档案】：\n{long_term_context}\n\n【治理缓存】：\n{memory_ctx}\n\n【财务画像】：\n- 剩余资金: {profile_data['current_surplus']} 元\n\n【初始情报】：\n{raw_info_text[:1200]}"
        conversation_history = [{"role": "system", "content": system_instruction}, {"role": "user", "content": user_input_context}]
        
        step = 0
        raw_output = ""
        while step < self.max_steps:
            step += 1
            try:
                if status_widget: status_widget.write(f"🧠 [Harness 状态机] 推理寻优中 ({step}/{self.max_steps})...")
                response = self.client.chat.completions.create(model=self.model, messages=conversation_history, temperature=0.3)
                raw_output = response.choices[0].message.content.strip()
                
                json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
                if json_match:
                    clean_json_str = json_match.group(0)
                else:
                    if "```json" in raw_output:
                        clean_json_str = raw_output.split("
```json")[1].split("```")[0].strip()
                    elif "```" in raw_output:
                        clean_json_str = raw_output.split("
```")[1].split("```")[0].strip()
                    else:
                        clean_json_str = raw_output
                    
                parsed_json = json.loads(clean_json_str)
                action = parsed_json.get("action")
                action_input = parsed_json.get("action_input")

                if action == "Final Answer": 
                    return action_input
                elif action == "Call_Web_Search":
                    _, search_feedback_text, _ = web_search_pro(action_input)
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报】：\n{search_feedback_text[:1200]}"})
            except Exception as e:
                if step >= self.max_steps - 1:
                    break
        
        if raw_output:
            if "PRICE_DATA" not in raw_output:
                clean_text = raw_output.replace("`", "").replace("{", "").replace("}", "")
                return f"📋 【铁算盘智能修正报告】\n{clean_text}\n\nPRICE_DATA: {{\"item\": \"{item_name}\", \"estimated_price\": 88.0}}"
            return raw_output
            
        return "⚠️ 【智能降级提示】当前全网情报网较为拥堵，铁算盘建议您对该商品保持持币观望态度。\nPRICE_DATA: {\"item\": \"" + item_name + "\", \"estimated_price\": 50.0}"


def async_push_notification(content, title=None):
    try:
        push_wechat(content)
        push_dingtalk(content, title=title)
    except Exception as e:
        print(f"后台静默发送失败: {e}")

if st.session_state['PENDING_NOTIFY']:
    task = st.session_state['PENDING_NOTIFY']
    st.session_state['ASYNC_EXECUTOR'].submit(async_push_notification, task["content"], task["title"])
    st.session_state['PENDING_NOTIFY'] = None


# ==========================================================
# 📊 FSM 状态机生命周期托管管道
# ==========================================================
def run_fsm_scout_pipeline(query, status_widget):
    fsm = JerryFSMAgent()
    fsm.transition_to("INTENT_CHECK")
    intent = classify_intent(query)
    if intent == "INVALID":
        fsm.transition_to("END")
        return "INVALID_INTENT", None, None, None, None

    fsm.transition_to("PRICE_SCOUT")
    clean_keyword = clean_query_to_entity(query)
    
    future_memory = st.session_state['ASYNC_EXECUTOR'].submit(hybrid_retriever.retrieve_and_rerank, query)
    future_web = st.session_state['ASYNC_EXECUTOR'].submit(web_search_pro, clean_keyword)
    future_crawler = st.session_state['ASYNC_EXECUTOR'].submit(crawl_smzdm_price, clean_keyword)
    
    long_term_context = future_memory.result()
    raw_info_blocks, raw_info_text, price_table_data = future_web.result()
    crawler_results = future_crawler.result()
    
    if crawler_results:
        crawler_text = "\n".join([item["price_info"] for item in crawler_results])
        raw_info_text = f"【什么值得买精选爆料行情】:\n{crawler_text}\n\n" + raw_info_text
        
    info_blocks = native_diversity_rerank(raw_info_blocks)
    
    fsm.transition_to("AUDIT_REPORT")
    st.session_state['GLOBAL_MEMORY_MANAGER'].add_message("user", query)
    memory_ctx = st.session_state['GLOBAL_MEMORY_MANAGER'].get_compiled_context()
    
    harness_engine = JerryAgentHarness()
    raw_answer = harness_engine.run_harness(
        clean_keyword, raw_info_text, get_dynamic_profile(), 
        long_term_context, memory_ctx, status_widget=status_widget
    )
    
    fsm.transition_to("END")
    return raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results


# ==========================================================
# UI 渲染层
# ==========================================================
with st.sidebar:
    st.header("🕵️ Jerry-Insight 调度中心")
    st.write("---")
    st.subheader("📊 铁算盘·资产风控中心")
    try:
        all_mems = memory_collection.get()
        item_status_map = {}
        if all_mems and all_mems['documents']:
            for doc in all_mems['documents']:
                part, status_type = None, None
                if "强行确认购买了关于'" in doc:
                    part = doc.split("强行确认购买了关于'")[1].split("'的商品")[0]
                    status_type = "WHITELIST"
                elif "关于'" in doc:
                    part = doc.split("关于'")[1].split("'的购买决策")[0]
                    status_type = "BLACKLIST" if "建议避坑" in doc else "WHITELIST"
                if part:
                    item_status_map[part.strip().replace("'", "").replace('"', "")] = status_type
        blacklist = [k for k, v in item_status_map.items() if v == "BLACKLIST"]
        whitelist = [k for k, v in item_status_map.items() if v == "WHITELIST"]
        with st.expander("🔴 查看被强制拦截的坑位", expanded=True):
            if blacklist:
                for item in blacklist[-5:]: st.markdown(f"❌ `{item}`")
            else: st.caption("暂无历史拦截记录")
        with st.expander("🟢 查看已安全放行的好物", expanded=True):
            if whitelist:
                for item in whitelist[-5:]: st.markdown(f"✅ `{item}`")
            else: st.caption("暂无历史放行记录")
    except: st.caption("数据加载中...")

    if st.button("🧹 清空当前聊天会话"):
        st.session_state['SHORT_TERM_MEMORY'] = []
        st.session_state['LAST_AUDIT'] = None
        st.session_state["active_query"] = None
        st.session_state["has_searched"] = False
        st.rerun()

st.title("🛡️ Jerry-Insight Pro v3.5+")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

# 🛠️ 核心修改：利用 st.chat_input 触发机制，只有当用户真正产生敲击行为时，才激活单次任务
chat_query = st.chat_input("输入商品名称，开始资产风控审计...")
if chat_query and chat_query.strip():
    st.session_state["active_query"] = chat_query.strip()
    st.session_state["has_searched"] = True

current_task = st.session_state["active_query"]

# 🚀 【核心防线】：如果用户没有真正产生输入检索（has_searched 为 False），直接阻断在欢迎页，绝对不加载旧的无人机历史结果！
if not st.session_state["has_searched"] or not current_task:
    st.info("💡 欢迎来到 Jerry-Insight 工业级消费风控中心！请在下方的输入框中键入你想审计的设备名称（如：二手大疆无人机）并敲击回车。")
    st.stop()

# ==========================================================
# 执行核心流（只有用户真正敲了回车才会走到这里）
# ==========================================================
with st.chat_message("user"): 
    st.write(current_task)

with st.chat_message("assistant"):
    with st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True) as status:
        raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results = run_fsm_scout_pipeline(current_task, status)
        
    if raw_answer == "INVALID_INTENT":
        st.error("🚨 监测到非业务输入/无效安全隐患。")
    else:
        status.update(label="🚀 FSM 流程闭合！情报与定向爬虫数据同步完毕！", state="complete", expanded=False)

        if info_blocks:
            with st.expander("🌐 查看 Jerry-Scout 全网核心情报来源与存证链接", expanded=False):
                for idx, block in enumerate(info_blocks):
                    text_snippet, source_url, rerank_score = block
                    st.markdown(f"**情报源 [{idx+1}]** ｜ 匹配度分值: `{rerank_score}`")
                    st.caption(f"内容摘要: {text_snippet[:150]}...")
                    if source_url:
                        st.markdown(f"🔗 [点击查看原始存证网页]({source_url})")
                    st.write("---")

        if (price_table_data is not None and len(price_table_data) > 0) or crawler_results:
            st.markdown("### 📊 Jerry-Scout 监测到全网全渠道实时比价盘口")
            
            parsed_data = []
            if price_table_data is not None:
                try:
                    if isinstance(price_table_data, str):
                        try: 
                            valid_json_str = price_table_data.replace("'", '"')
                            parsed_data = json.loads(valid_json_str)
                        except: 
                            parsed_data = eval(price_table_data)
                    else: 
                        parsed_data = price_table_data
                except: 
                    pass

            if crawler_results and isinstance(parsed_data, list):
                for spider_item in crawler_results:
                    parsed_data.insert(0, {
                        "平台": f"🔥 {spider_item['platform']} (精细爆破)",
                        "参考报价/情报说明": spider_item['price_info'],
                        "数据出处": spider_item['source']
                    })

            if isinstance(parsed_data, list) and len(parsed_data) > 0:
                df = pd.DataFrame(parsed_data)
                column_mapping = {"平台": "🛒 渠道平台", "参考报价/情报说明": "💰 实时报价与情报", "数据出处": "🔗 原始链接"}
                df = df.rename(columns=column_mapping)
                st.dataframe(df, hide_index=True)

        detected_price = None
        display_answer = raw_answer
        if "PRICE_DATA:" in raw_answer:
            try:
                parts = raw_answer.split("PRICE_DATA:")
                display_answer = parts[0]
                parsed_price_data = json.loads(parts[1].strip())
                detected_price = float(parsed_price_data["estimated_price"])
            except: 
                pass

        st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
        st.markdown(display_answer)

        # 🧹 单次生命周期结束：立刻洗刷任务标志位，防止下一次自动跑
        st.session_state["active_query"] = None
        st.session_state["has_searched"] = False