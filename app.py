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
# 🔒 1. 初始化页面配置与面试官资产风控访问锁
# =====================================================================
st.set_page_config(page_title="Jerry-Insight Pro", layout="wide")

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    st.title("🛡️ Jerry-Insight Pro 访问鉴权")
    st.markdown("欢迎来到 Jerry-Insight 工业级消费风控 Agent 引擎演示现场。")
    input_password = st.text_input("请输入面试官专属访问令牌 (Token)：", type="password")
    
    # 专属密码设置
    if input_password == "jerry2026":
        st.session_state['authenticated'] = True
        st.success("验证通过，正在初始化铁算盘引擎...")
        st.rerun()
    elif input_password:
        st.error("令牌错误，请联系作者获取正确访问权限。")
    st.stop()  # 未验证通过时，强行阻断后续所有核心组件和业务逻辑的加载

# =====================================================================
# 🛠️ 2. 初代路由、去噪组件与新引入的状态机/爬虫组件
# =====================================================================
from bs4 import BeautifulSoup  # BeautifulSoup 导入直接放这里
from core.router import classify_intent, clean_query_to_entity
from core.memory_manager import AdvancedMemoryManager
from core.hybrid_retriever import JaccardHybridRetriever
from tools.mcp_server import JerryMcpServer

from core.brain import ask_llm
from tools.search import web_search_pro
from tools.price_crawler import crawl_smzdm_price  # 完美引入新爬虫
from core.jerry_fsm_agent import JerryFSMAgent     # 完美引入新状态机
from data.sql_db import save_audit_log
from dotenv import load_dotenv

try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): return "未检测到 notify 微信零件"
    def push_dingtalk(content, title=None): return "未检测到 notify 钉钉零件"

load_dotenv()
st.set_page_config(page_title="Jerry-Insight Pro v3.5+", layout="wide", page_icon="🛡️")

FILE_LOCK = threading.Lock()
PROFILE_FILE = "jerry_profile.json"

if 'ASYNC_EXECUTOR' not in st.session_state:
    st.session_state['ASYNC_EXECUTOR'] = ThreadPoolExecutor(max_workers=8)

@st.cache_resource
def init_chroma_and_inject_profiles():
    chroma_client = chromadb.PersistentClient(path="./memory_bank_v2")
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

api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

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
# 🌟 核心升级组件：深度解封版 JerryAgentHarness (高质文笔，无痛防摔)
# ==========================================================
class JerryAgentHarness:
    def __init__(self, max_steps=4):
        self.client = openai_client
        self.model = "deepseek-chat" 
        self.max_steps = max_steps

    def run_harness(self, item_name, raw_info_text, profile_data, long_term_context, memory_ctx, status_widget=None):
        # 🟢 重新精雕细琢的约束 System Prompt：死卡 JSON 框架，但全面放开内部的“文笔和篇幅”！
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
            "  \"action_input\": \"【建议购买/建议避坑/持币观望】\\n\\n【深度审计理由】：\\n（在这里请结合 Jerry 的月度生活费剩余、历史消费习惯、商品性价比、全网行情，给出极其详尽、深刻、温情的消费心理审计与规避建议。请不要敷衍，尽可能详细、全方位地展开长文描述，保留你作为资深风控官独特的感性关怀与专业审计眼光。）\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + item_name + "\\\", \\\"estimated_price\\\": 预估单价}\"\n"
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
                # 🟢 将温度微调到 0.3：既保证 JSON 不走样，又彻底激活大模型的文学修辞和细腻深度
                response = self.client.chat.completions.create(model=self.model, messages=conversation_history, temperature=0.3)
                raw_output = response.choices[0].message.content.strip()
                
                # 🟢 【超强强力防御】：提取文本中任何包含 { ... } 的段落，无视大模型可能吐出的任何 markdown 代码块标识
                json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
                if json_match:
                    clean_json_str = json_match.group(0)
                else:
                    if "```json" in raw_output:
                        clean_json_str = raw_output.split("```json")[1].split("```")[0].strip()
                    elif "```" in raw_output:
                        clean_json_str = raw_output.split("```")[1].split("```")[0].strip()
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
        
        # 🟢 【柔性收敛兜底层】：若发生了极端抖动导致不合规，依然帮它把长文提取出来并擦好屁股，永不弹窗中断
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
    
    # ---- 状态 1: 意图检查 (INTENT_CHECK) ----
    fsm.transition_to("INTENT_CHECK")
    intent = classify_intent(query)
    if intent == "INVALID":
        fsm.transition_to("END")
        return "INVALID_INTENT", None, None, None, None

    # ---- 状态 2: 价格/情报搜索 (PRICE_SCOUT) ----
    fsm.transition_to("PRICE_SCOUT")
    clean_keyword = clean_query_to_entity(query)
    
    # 线程池并发调度：数据库、全网API、以及自定义价格爬虫
    future_memory = st.session_state['ASYNC_EXECUTOR'].submit(hybrid_retriever.retrieve_and_rerank, query)
    future_web = st.session_state['ASYNC_EXECUTOR'].submit(web_search_pro, clean_keyword)
    future_crawler = st.session_state['ASYNC_EXECUTOR'].submit(crawl_smzdm_price, clean_keyword)
    
    long_term_context = future_memory.result()
    raw_info_blocks, raw_info_text, price_table_data = future_web.result()
    crawler_results = future_crawler.result()
    
    # 将爬虫获取到的精细 DOM 数据合并融入 RAG 提示词上下文
    if crawler_results:
        crawler_text = "\n".join([item["price_info"] for item in crawler_results])
        raw_info_text = f"【什么值得买精选爆料行情】:\n{crawler_text}\n\n" + raw_info_text
        
    info_blocks = native_diversity_rerank(raw_info_blocks)
    
    # ---- 状态 3: 深度决策审计报告 (AUDIT_REPORT) ----
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

    if st.button("🧹 清空当前聊天会话", width="stretch"):
        st.session_state['SHORT_TERM_MEMORY'] = []
        st.session_state['LAST_AUDIT'] = None
        st.rerun()

st.title("🛡️ Jerry-Insight Pro v3.5+")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

query = st.chat_input("输入商品名称...")

if query and query.strip():
    with st.chat_message("user"): st.write(query)

    with st.chat_message("assistant"):
        with st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True) as status:
            raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results = run_fsm_scout_pipeline(query, status)
            
        if raw_answer == "INVALID_INTENT":
            st.error("🚨 监测到非业务输入/无效安全隐患。")
        else:
            status.update(label="🚀 FSM 流程闭合！情报与定向爬虫数据同步完毕！", state="complete", expanded=False)

            # ==========================================================
            # 🔗 网页存证跳转链接渲染
            # ==========================================================
            if info_blocks:
                with st.expander("🌐 查看 Jerry-Scout 全网核心情报来源与存证链接", expanded=False):
                    for idx, block in enumerate(info_blocks):
                        text_snippet, source_url, rerank_score = block
                        st.markdown(f"**情报源 [{idx+1}]** ｜ 匹配度分值: `{rerank_score}`")
                        st.caption(f"内容摘要: {text_snippet[:150]}...")
                        if source_url:
                            st.markdown(f"🔗 [点击查看原始存证网页]({source_url})")
                        st.write("---")

            # ==========================================================
            # 📊 数据表渲染：完美融合大盘数据与【定向爆破爬虫】实时爆料
            # ==========================================================
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

                # 把精确网页 DOM 爆料插入表格首行进行高亮展示
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
                    st.dataframe(df, use_container_width=True, hide_index=True)

            # ==========================================================
            # 价格解析与深度报告渲染
            # ==========================================================
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
            if detected_price is None: detected_price = 50.0

            st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
            st.markdown(display_answer)
            st.session_state['GLOBAL_MEMORY_MANAGER'].add_message("assistant", display_answer)
            
            st.session_state['LAST_AUDIT'] = {"price": detected_price, "item": clean_keyword}
            
            short_conclusion = "建议避坑" if "建议避坑" in display_answer else ("建议购买" if "建议购买" in display_answer else "持币观望")
            push_brief = f"### 🕵️ 铁算盘·消费审计报告\n- **商品目标**：{clean_keyword}\n- **审计结论**：**{short_conclusion}**\n- **预估金额**：{detected_price} 元"
            st.session_state['ASYNC_EXECUTOR'].submit(async_push_notification, push_brief, "🕵️ 消费审计报告")

            try:
                memory_collection.add(documents=[f"Jerry曾咨询过关于'{clean_keyword}'的购买决策。结论是：[{short_conclusion}]"], metadatas=[{"source": "chat_log"}], ids=[f"mem_{os.urandom(4).hex()}"])
                save_audit_log(query, display_answer[:50])
            except: 
                pass

# ==========================================================
# 资产闭环记账阶段 (MCP 记账)
# ==========================================================
if st.session_state['LAST_AUDIT']:
    st.write("---")
    audit_item = st.session_state['LAST_AUDIT']["item"]
    audit_price = st.session_state['LAST_AUDIT']["price"]
    
    if st.button(f" 确认记入账本 (扣减 {audit_price}元)", type="primary"):
        rpc_payload = json.dumps({
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "record_expense", "arguments": {"amount": audit_price, "item_name": audit_item}},
            "id": 1
        })
        mcp_gateway.handle_json_rpc(rpc_payload)
        
        current_profile = get_dynamic_profile()
        
        st.session_state['PENDING_NOTIFY'] = {
            "title": "⚠️ 资产账户变动联合报告",
            "content": (
                f"### 🛡️ 铁算盘·消费审计报告 (资产扣减)\n"
                f"- **买入明细**：`{audit_item}`\n"
                f"- **消费扣减**：`- {audit_price} 元`\n\n"
                f"---\n\n"
                f"### ⚠️ 实时大盘风险控制报告\n"
                f"- **当前本月剩余流动资金**：**{current_profile['current_surplus']} 元**\n"
                f"- **风控提示**：系统已强制对齐月度资产预算规划！"
            )
        }
        
        try:
            memory_collection.add(documents=[f"Jerry最终确认购买了关于'{audit_item}'的商品。最终状态：[已买入]"], ids=[f"corr_{os.urandom(4).hex()}"])
        except: 
            pass
            
        st.session_state['LAST_AUDIT'] = None
        st.rerun()