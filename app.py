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

if 'authenticated' not in st.session_state:
    st.session_state['authenticated'] = False

if not st.session_state['authenticated']:
    st.title("🛡️ Jerry-Insight Pro 访问鉴权")
    input_password = st.text_input("请输入访问令牌 (Token)：", type="password")
    if input_password == "jerry2026":
        st.session_state['authenticated'] = True
        st.rerun()
    st.stop()

# 初始化核心生命周期变量
if "active_query" not in st.session_state:
    st.session_state["active_query"] = None
if "has_searched" not in st.session_state:
    st.session_state["has_searched"] = False
if "expense_recorded" not in st.session_state:
    st.session_state["expense_recorded"] = False

# =====================================================================
# 🛠️ 2. 核心组件与通知组件引入
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

try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): return "本地零件未就绪"
    def push_dingtalk(content, title=None): return "本地零件未就绪"

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
            default_profile = {"user_name": "Jerry", "monthly_budget": 2000.0, "current_surplus": 850.0, "fixed_expenses": {"饮食": 1200, "话费交通": 300}, "recent_purchases": []}
            with open(PROFILE_FILE, "w", encoding="utf-8") as f: json.dump(default_profile, f, ensure_ascii=False, indent=4)
            return default_profile
        with open(PROFILE_FILE, "r", encoding="utf-8") as f: return json.load(f)

def update_profile_balance(amount, item_name):
    profile = get_dynamic_profile()
    profile["current_surplus"] = round(profile["current_surplus"] - amount, 2)
    if item_name not in profile["recent_purchases"]:
        profile["recent_purchases"].append(item_name)
    with FILE_LOCK:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f: json.dump(profile, f, ensure_ascii=False, indent=4)

mcp_gateway = JerryMcpServer(update_profile_balance, FILE_LOCK)

api_key = st.secrets.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY"))
base_url = st.secrets.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
openai_client = OpenAI(api_key=api_key, base_url=base_url)

if 'GLOBAL_MEMORY_MANAGER' not in st.session_state: st.session_state['GLOBAL_MEMORY_MANAGER'] = AdvancedMemoryManager(openai_client)
if 'SHORT_TERM_MEMORY' not in st.session_state: st.session_state['SHORT_TERM_MEMORY'] = []
if 'LAST_AUDIT' not in st.session_state: st.session_state['LAST_AUDIT'] = None
if 'PENDING_NOTIFY' not in st.session_state: st.session_state['PENDING_NOTIFY'] = None

def native_diversity_rerank(info_blocks):
    if not info_blocks: return []
    unique_blocks = []
    for current in info_blocks:
        text, url, score = current
        if not any(len(set(text) & set(x[0])) / max(len(set(text) | set(x[0])), 1) > 0.65 for x in unique_blocks): unique_blocks.append(current)
    return unique_blocks[:4]

# ==========================================================
# 🌟 JerryAgentHarness 引擎
# ==========================================================
class JerryAgentHarness:
    def __init__(self, max_steps=4):
        self.client = openai_client
        self.model = "deepseek-chat" 
        self.max_steps = max_steps

    def run_harness(self, item_name, raw_info_text, profile_data, long_term_context, memory_ctx, status_widget=None):
        system_instruction = (
            "你是 Jerry-Insight 系统【首席风控审计官】，代号“铁算盘”。\n"
            "我们要审计的商品是：【" + str(item_name) + "】。\n\n"
            "【❗⚠️ 核心死命令 ⚠️❗】\n"
            "你必须且只能输出标准的 JSON 块，禁止包含任何 JSON 之外的问候性、引言或多余寒暄。你的输出格式必须是以下两种之一：\n\n"
            "1. 如果需要继续追查搜索：\n"
            "{\"action\": \"Call_Web_Search\", \"action_input\": \"关键词\"}\n\n"
            "2. 如果情报足够，给出最终审计报告（核心内容）：\n"
            "{\n"
            "  \"action\": \"Final Answer\",\n"
            "  \"action_input\": \"【建议购买/建议避坑/持币观望】\\n\\n【深度审计理由】：\\n（在这里请结合 Jerry 的月度生活费剩余、历史消费习惯、商品性价比、全网行情，给出极其详尽、深刻、温情地消费心理审计与规避建议。）\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + str(item_name) + "\\\", \\\"estimated_price\\\": 3.5}\"\n"
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
                
                if parsed_json.get("action") == "Final Answer": return parsed_json.get("action_input")
                elif parsed_json.get("action") == "Call_Web_Search":
                    _, search_feedback_text, _ = web_search_pro(parsed_json.get("action_input"))
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报】：\n{search_feedback_text[:1200]}"})
            except:
                if step >= self.max_steps - 1: break
        return raw_output if "PRICE_DATA" in raw_output else f"📋报告\n{raw_output}\n\nPRICE_DATA: {{\"item\": \"{item_name}\", \"estimated_price\": 3.5}}"

def async_push_notification(content, title=None):
    try:
        if WECHAT_TOKEN: push_wechat(content)
        if DINGTALK_TOKEN: push_dingtalk(content, title=title)
    except Exception as e: print(f"后台通知发送失败: {e}")

# ==========================================================
# 📊 FSM 状态机托管管道
# ==========================================================
def run_fsm_scout_pipeline(query, status_widget):
    fsm = JerryFSMAgent()
    fsm.transition_to("INTENT_CHECK")
    if classify_intent(query) == "INVALID":
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
        raw_info_text = f"【什么值得买精选爆料行情】:\n" + "\n".join([item["price_info"] for item in crawler_results]) + "\n\n" + raw_info_text
        
    info_blocks = native_diversity_rerank(raw_info_blocks)
    
    fsm.transition_to("AUDIT_REPORT")
    st.session_state['GLOBAL_MEMORY_MANAGER'].add_message("user", query)
    memory_ctx = st.session_state['GLOBAL_MEMORY_MANAGER'].get_compiled_context()
    
    raw_answer = JerryAgentHarness().run_harness(clean_keyword, raw_info_text, get_dynamic_profile(), long_term_context, memory_ctx, status_widget)
    fsm.transition_to("END")
    return raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results

# ==========================================================
# UI 渲染层
# ==========================================================
with st.sidebar:
    st.header("🕵️ Jerry-Insight 调度中心")
    st.write("---")
    if st.button("🧹 清空当前聊天会话"):
        st.session_state['SHORT_TERM_MEMORY'] = []
        st.session_state['LAST_AUDIT'] = None
        st.session_state["active_query"] = None
        st.session_state["has_searched"] = False
        st.session_state["expense_recorded"] = False
        st.rerun()

st.title("🛡️ Jerry-Insight Pro v3.5+")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

chat_query = st.chat_input("输入商品名称，开始资产风控审计...")
if chat_query and chat_query.strip():
    st.session_state["active_query"] = chat_query.strip()
    st.session_state["has_searched"] = True
    st.session_state["expense_recorded"] = False  # 新一轮查询重置记账状态
    st.rerun()

current_task = st.session_state["active_query"]

# 🚀 【安全卫士阻断欢迎页】
if not st.session_state["has_searched"] or not current_task:
    st.info("💡 欢迎来到 Jerry-Insight 工业级消费风控中心！请在下方输入框中键入你想审计的设备名称并敲击回车。")
    st.stop()

# 主流渲染逻辑
with st.chat_message("user"): 
    st.write(current_task)

with st.chat_message("assistant"):
    status = st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True)
    try:
        raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results = run_fsm_scout_pipeline(current_task, status)
        
        if raw_answer == "INVALID_INTENT":
            status.update(label="🚨 监测到非业务输入/无效安全隐患。", state="error", expanded=False)
            st.error("请输入有效的业务商品进行审计。")
            st.stop()
            
        status.update(label="🚀 FSM 流程闭合！情报与定向爬虫数据同步完毕！", state="complete", expanded=False)
        
        # 🟢 【核心修复】：链接与情报来源展示
        if info_blocks:
            st.markdown("### 🌐 Jerry-Scout 全网核心情报来源与存证链接")
            for idx, block in enumerate(info_blocks):
                text_snippet, source_url, rerank_score = block
                st.markdown(f"**情报源 [{idx+1}]** ｜ 匹配度分值: `{rerank_score}`")
                st.caption(f"内容摘要: {text_snippet[:150]}...")
                if source_url: st.markdown(f"🔗 [点击查看原始存证网页]({source_url})")
                st.write("---")

        # 🟢 【核心修复】：比价盘口展示
        if (price_table_data is not None and len(price_table_data) > 0) or crawler_results:
            st.markdown("### 📊 Jerry-Scout 监测到全网全渠道实时比价盘口")
            parsed_data = []
            if crawler_results:
                for spider_item in crawler_results:
                    parsed_data.append({"🛒 渠道平台": f"🔥 {spider_item['platform']}", "💰 实时报价与情报": spider_item['price_info'], "🔗 原始链接": spider_item['source']})
            st.dataframe(pd.DataFrame(parsed_data), hide_index=True)

        # 报告正文
        display_answer = raw_answer.split("PRICE_DATA:")[0] if "PRICE_DATA:" in raw_answer else raw_answer
        st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
        st.markdown(display_answer)

        # 价格兜底解析
        detected_price = 3.5  # 针对可乐默认
        if "PRICE_DATA:" in raw_answer:
            try: detected_price = float(json.loads(raw_answer.split("PRICE_DATA:")[1].strip())["estimated_price"])
            except: pass
        
        # 锁进缓存凭证
        if not st.session_state["expense_recorded"]:
            st.session_state['LAST_AUDIT'] = {"price": detected_price, "item": clean_keyword, "display_answer": display_answer}

    except Exception as e:
        status.update(label=f"❌ 流程运行异常: {str(e)}", state="error", expanded=False)
        st.error(f"引擎报错: {e}")

# ==========================================================
# 📊 资产闭环记账阶段 (修正了生命周期的阻塞)
# ==========================================================
if st.session_state['LAST_AUDIT'] and not st.session_state["expense_recorded"]:
    st.write("---")
    audit_item = st.session_state['LAST_AUDIT']["item"]
    audit_price = st.session_state['LAST_AUDIT']["price"]
    audit_report = st.session_state['LAST_AUDIT']["display_answer"]
    
    if st.button(f"🪙 确认记入账本 (扣减 {audit_price}元)", type="primary"):
        # 调用记账核心 MCP 逻辑
        rpc_payload = json.dumps({
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "record_expense", "arguments": {"amount": audit_price, "item_name": audit_item}},
            "id": 1
        })
        mcp_gateway.handle_json_rpc(rpc_payload)
        
        # 触发双通道通知推送 (保证微信和钉钉能准确捕获)
        current_profile = get_dynamic_profile()
        short_conclusion = "建议避坑" if "建议避坑" in audit_report else "持币观望"
        
        notify_content = (
            f"### 🛡️ 铁算盘·消费审计资产扣减报告\n"
            f"- **买入明细**：`{audit_item}`\n"
            f"- **消费扣减**：`- {audit_price} 元`\n"
            f"- **审计结论**：**{short_conclusion}**\n\n"
            f"---\n"
            f"### ⚠️ 实时风险控制面板\n"
            f"- **当前卡内剩余流动资金**：**{current_profile['current_surplus']} 元**\n"
            f"- **资产风控提示**：当前账户严重超支，系统已强制同步财务预警。"
        )
        st.session_state['ASYNC_EXECUTOR'].submit(async_push_notification, notify_content, "⚠️ 资产账户变动联合报告")
        
        # 更新状态锁，防止 st.stop 断流
        st.session_state["expense_recorded"] = True
        st.session_state['LAST_AUDIT'] = None
        st.success(f"✅ 成功记账！已从流动资金中扣除 {audit_price} 元。")
        st.rerun()

# 当扣账成功后，在最下方持久显示扣除成功后的状态提示
if st.session_state["expense_recorded"]:
    st.write("---")
    st.success("💰 铁算盘已完成该商品的资产账目核销，当前大盘资金余额已实时更新。")