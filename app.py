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
# 🔒 1. 初始化页面配置与强效会话隔离
# =====================================================================
st.set_page_config(page_title="Jerry-Insight Pro v3.5+", layout="wide", page_icon="🛡️")

if "active_query" not in st.session_state:
    st.session_state["active_query"] = None
if "has_searched" not in st.session_state:
    st.session_state["has_searched"] = False

# =====================================================================
# 🛠️ 2. 核心组件与依赖引入
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

load_dotenv()
WECHAT_TOKEN = st.secrets.get("PUSH_TOKEN", os.getenv("PUSH_TOKEN"))
DINGTALK_TOKEN = st.secrets.get("DING_WEBHOOK", os.getenv("DING_WEBHOOK"))

# 🛡️ 确保通知组件能安全引入，并提供同步发送的健壮性
try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): return "本地微信零件未就绪"
    def push_dingtalk(content, title=None): return "本地钉钉零件未就绪"

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
    return collection

memory_collection = init_chroma_and_inject_profiles()
hybrid_retriever = JaccardHybridRetriever(memory_collection)

def get_dynamic_profile():
    with FILE_LOCK:
        if not os.path.exists(PROFILE_FILE):
            default_profile = {
                "user_name": "Jerry", "monthly_budget": 2000.0, "current_surplus": 850.0,  
                "fixed_expenses": {"饮食": 1200, "话费交通": 300}, "recent_purchases": []
            }
            with open(PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(default_profile, f, ensure_ascii=False, indent=4)
            return default_profile
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

def update_profile_balance(amount, item_name):
    with FILE_LOCK:
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                profile = json.load(f)
        else:
            profile = {"user_name": "Jerry", "monthly_budget": 2000.0, "current_surplus": 850.0, "recent_purchases": []}
        
        profile["current_surplus"] = round(profile["current_surplus"] - amount, 2)
        if item_name not in profile["recent_purchases"]:
            profile["recent_purchases"].append(item_name)
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=4)

mcp_gateway = JerryMcpServer(update_profile_balance, FILE_LOCK)

api_key = st.secrets.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY"))
base_url = st.secrets.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
openai_client = OpenAI(api_key=api_key, base_url=base_url)

if 'GLOBAL_MEMORY_MANAGER' not in st.session_state:
    st.session_state['GLOBAL_MEMORY_MANAGER'] = AdvancedMemoryManager(openai_client)

if 'SHORT_TERM_MEMORY' not in st.session_state: st.session_state['SHORT_TERM_MEMORY'] = []

def native_diversity_rerank(info_blocks):
    if not info_blocks: return []
    unique_blocks = []
    for current in info_blocks:
        text, url, score = current
        is_duplicate = False
        for existing in unique_blocks:
            if len(set(text) & set(existing[0])) / max(len(set(text) | set(existing[0])), 1) > 0.65: 
                is_duplicate = True
                break
        if not is_duplicate: unique_blocks.append(current)
    return unique_blocks[:4]

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
            "  \"action_input\": \"【建议避坑】\\n\\n【深度审计理由】：\\n（请结合 Jerry 目前的流动资金余额、每月2000元的生活费预算，深度切入消费偏好与性价比，给出详尽、严格、温情地全套审计意见。）\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + item_name + "\\\", \\\"estimated_price\\\": 预估单价}\"\n"
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
                clean_json_str = json_match.group(0) if json_match else raw_output
                parsed_json = json.loads(clean_json_str)
                
                if parsed_json.get("action") == "Final Answer": 
                    return parsed_json.get("action_input")
                elif parsed_json.get("action") == "Call_Web_Search":
                    _, search_feedback_text, _ = web_search_pro(parsed_json.get("action_input"))
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报】：\n{search_feedback_text[:1200]}"})
            except:
                break
        
        # 🟢 彻底重构 186 行防御分裂逻辑，改用最安全的无换行文本替代，彻底避免 SyntaxError
        if raw_output and "PRICE_DATA" not in raw_output:
            return raw_output + f"\n\nPRICE_DATA: {{\"item\": \"{item_name}\", \"estimated_price\": 2500.0}}"
        return raw_output

def run_fsm_scout_pipeline(query, status_widget):
    fsm = JerryFSMAgent()
    fsm.transition_to("INTENT_CHECK")
    if classify_intent(query) == "INVALID":
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
        raw_info_text = "【什么值得买精选爆料】:\n" + "\n".join([i["price_info"] for i in crawler_results]) + "\n\n" + raw_info_text
        
    info_blocks = native_diversity_rerank(raw_info_blocks)
    
    fsm.transition_to("AUDIT_REPORT")
    st.session_state['GLOBAL_MEMORY_MANAGER'].add_message("user", query)
    
    harness_engine = JerryAgentHarness()
    raw_answer = harness_engine.run_harness(
        clean_keyword, raw_info_text, get_dynamic_profile(), 
        long_term_context, st.session_state['GLOBAL_MEMORY_MANAGER'].get_compiled_context(), status_widget
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
        blacklist, whitelist = [], []
        if all_mems and all_mems['documents']:
            for doc in all_mems['documents']:
                if "建议避坑" in doc and "关于'" in doc:
                    blacklist.append(doc.split("关于'")[1].split("'的购买决策")[0])
                elif "确定购买" in doc and "关于'" in doc:
                    whitelist.append(doc.split("关于'")[1].split("'的商品")[0])
        
        with st.expander("🔴 查看被强制拦截的坑位", expanded=True):
            if blacklist:
                for item in set(blacklist[-5:]): st.markdown(f"❌ `{item}`")
            else: st.caption("暂无历史拦截记录")
        with st.expander("🟢 查看已安全放行的好物", expanded=True):
            if whitelist:
                for item in set(whitelist[-5:]): st.markdown(f"✅ `{item}`")
            else: st.caption("暂无历史放行记录")
    except:
        st.caption("侧边栏流水加载中...")

    if st.button("🧹 清空当前聊天会话"):
        st.session_state['SHORT_TERM_MEMORY'] = []
        st.session_state["active_query"] = None
        st.session_state["has_searched"] = False
        st.rerun()

st.title("🛡️ Jerry-Insight Pro v3.5+")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

chat_query = st.chat_input("输入商品名称，开始资产风控审计...")
if chat_query and chat_query.strip():
    st.session_state["active_query"] = chat_query.strip()
    st.session_state["has_searched"] = True

current_task = st.session_state["active_query"]

if not st.session_state["has_searched"] or not current_task:
    st.info("💡 欢迎来到 Jerry-Insight 消费风控中心！请输入你想审计的商品（如：苹果手机）并回车。")
    st.stop()

# ==========================================================
# 执行核心流
# ==========================================================
with st.chat_message("user"): 
    st.write(current_task)

with st.chat_message("assistant"):
    with st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True) as status:
        raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results = run_fsm_scout_pipeline(current_task, status)
    
    if raw_answer == "INVALID_INTENT":
        st.error("🚨 监测到非业务输入/无效安全隐患。")
    else:
        status.update(label="🚀 FSM 流程闭合！基础情报同步完毕！", state="complete", expanded=False)

        # 🛠️ 解决痛点三：100% 确保全网情报源长链接一键点击跳转
        if info_blocks:
            with st.expander("🌐 查看 Jerry-Scout 全网核心情报来源与存证链接", expanded=False):
                for idx, block in enumerate(info_blocks):
                    text_snippet, source_url, _ = block
                    st.markdown(f"🔗 **情报源 [{idx+1}]** ｜ [点击直接打开原始网页]({source_url})")
                    st.caption(f"摘要: {text_snippet[:120]}...")

        # 🛠️ 解决痛点三：利用 LinkColumn 让全渠道比价链接支持直达
        if price_table_data or crawler_results:
            st.markdown("### 📊 Jerry-Scout 监测到全网全渠道实时比价盘口")
            parsed_data = list(price_table_data) if isinstance(price_table_data, list) else []
            if crawler_results:
                for spider_item in crawler_results:
                    parsed_data.insert(0, {"平台": f"🔥 {spider_item['platform']}", "参考报价/情报说明": spider_item['price_info'], "数据出处": spider_item['source']})
            
            if parsed_data:
                df = pd.DataFrame(parsed_data)
                df = df.rename(columns={"平台": "🛒 渠道平台", "参考报价/情报说明": "💰 实时报价与情报", "数据出处": "🔗 原始链接"})
                st.data_editor(
                    df, 
                    hide_index=True, 
                    disabled=True, 
                    column_config={"🔗 原始链接": st.column_config.LinkColumn("🔗 快捷直达链接", help="点击直接跳转电商或爆料网")}
                )

        # 提取核心价格
        detected_price = 2500.0
        display_answer = raw_answer
        if "PRICE_DATA:" in raw_answer:
            try:
                parts = raw_answer.split("PRICE_DATA:")
                display_answer = parts[0]
                detected_price = float(json.loads(parts[1].strip())["estimated_price"])
            except: pass

        st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
        st.markdown(display_answer)

        # 🛠️ 解决痛点二：前台阻塞强发推送，绝不在后台被吞，并在页面直接打印返回状态！
        notification_title = f"🛡️ Jerry-Insight 消费风控阻断通报: 【{clean_keyword}】"
        notification_body = f"Jerry 正在尝试购买：【{clean_keyword}】\n财务账本余额：{dynamic_profile['current_surplus']} 元\n风控结论：{display_answer[:300]}"
        
        with st.status("🚀 正在向微信和钉钉主控台同步发射风控警报...", expanded=True) as notify_status:
            res_wx = push_wechat(notification_body)
            res_dd = push_dingtalk(notification_body, title=notification_title)
            notify_status.write(f"📲 微信通道反馈: {res_wx}")
            notify_status.write(f"📲 钉钉通道反馈: {res_dd}")
            notify_status.update(label="🔔 微信与钉钉风控通报发射完毕！", state="complete")

        # 🛠️ 解决痛点一：100% 唤醒扣款决策组件，按钮绝对不会丢
        st.write("---")
        st.markdown("### ⚖️ 风控终审决策交互中心")
        
        col1, col2 = st.columns(2)
        with col1:
            if st.button("✅ 听劝，放弃购买（记录安全放行/合规执行）"):
                memory_collection.add(
                    documents=[f"Jerry非常听劝，面对关于'{clean_keyword}'的购买决策，在听取铁算盘审计后，主动放弃了购买，保障了本月资产安全。"],
                    metadatas=[{"category": "audit_action", "status": "pass"}],
                    ids=[f"action_pass_{int(time.time())}"]
                )
                st.success("🎉 铁算盘为你点赞！不买立省 100%！已记录至安全守信账本。")
                st.session_state["active_query"] = None
                st.session_state["has_searched"] = False
                time.sleep(1)
                st.rerun()
                
        with col2:
            if st.button("🚨 不听，我非要强行购买（触发真实记账扣款）"):
                # 扣减实际检测出来的苹果手机预估总价
                update_profile_balance(detected_price, clean_keyword)
                memory_collection.add(
                    documents=[f"Jerry强行确认购买了关于'{clean_keyword}'的商品，产生了金额为 {detected_price} 元的强行扣款账务。"],
                    metadatas=[{"category": "audit_action", "status": "force_buy"}],
                    ids=[f"action_force_{int(time.time())}"]
                )
                # 强发破产紧急状态通知
                push_dingtalk(f"🚨 高危警报！Jerry没有听从风控建议，强行购买了【{clean_keyword}】，扣款 {detected_price} 元！当前账户极其危险！")
                st.error(f"💸 已强行执行资产扣款！账本成功扣除 {detected_price} 元。已上报至高危行为存证单。")
                st.session_state["active_query"] = None
                st.session_state["has_searched"] = False
                time.sleep(1)
                st.rerun()

        # 彻底清空单次缓存
        st.session_state["active_query"] = None
        st.session_state["has_searched"] = False