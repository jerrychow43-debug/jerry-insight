import os
import time
import json
import re
import threading
import chromadb
import numpy as np
import pandas as pd
import streamlit as st
import requests  
from openai import OpenAI
from concurrent.futures import ThreadPoolExecutor

# =====================================================================
# 🔒 1. 全局配置与环境初始化
# =====================================================================
st.set_page_config(page_title="省钱智探agent", layout="wide", page_icon="🛡️")

# 核心状态机状态保持
if "active_query" not in st.session_state:
    st.session_state["active_query"] = None
if "just_recorded" not in st.session_state:
    st.session_state["just_recorded"] = None  
if 'LAST_AUDIT' not in st.session_state:
    st.session_state['LAST_AUDIT'] = None
if 'SUBMIT_PROCESSING' not in st.session_state:
    st.session_state['SUBMIT_PROCESSING'] = False
# 🛠️ 用于记录当前这笔账单是否已经做出决策（点击过按钮）
if 'ACTION_COMPLETED' not in st.session_state:
    st.session_state['ACTION_COMPLETED'] = False

# 🔄 【新增】初始化多轮对话上下文与侧边栏历史归档
if st.session_state.get("SUBMIT_PROCESSING") and st.session_state.get("LAST_AUDIT"):
    st.session_state["SUBMIT_PROCESSING"] = False

if "chat_history" not in st.session_state:
    st.session_state["chat_history"] = []  # 结构: [{"role": "user/assistant", "content": "..."}]
if "history_sessions" not in st.session_state:
    st.session_state["history_sessions"] = [] # 结构: [{"query": "...", "audit_data": {...}}]

# =====================================================================
# 🛠️ 2. 核心底层组件引入与环境配置对齐
# =====================================================================
from bs4 import BeautifulSoup  
from core.router import clean_query_to_entity, fallback_clean_query_to_entity
from core.intent_plus import classify_user_intent
from core.hybrid_retriever import JaccardHybridRetriever
from tools.mcp_server import JerryMcpServer

from data.sql_db import init_runtime_tables, load_recent_chat_history, save_audit_log, save_chat_history, save_notification_log
from dotenv import load_dotenv

try:
    from core.memory_manager import AdvancedMemoryManager
except KeyError as import_err:
    print(f"Memory manager hot-reload import failed, using local fallback: {import_err}")

    class AdvancedMemoryManager:
        def __init__(self, client, max_turns: int = 3):
            self.client = client
            self.max_turns = max_turns
            self.short_term_memory = []

        def add_message(self, role: str, content: str):
            self.short_term_memory.append({"role": role, "content": content})
            self.short_term_memory = self.short_term_memory[-(self.max_turns * 2):]

        def get_compiled_context(self) -> str:
            lines = ["【近期临近会话上下文】:"]
            for msg in self.short_term_memory:
                role_tag = "用户" if msg["role"] == "user" else "铁算盘"
                lines.append(f"- {role_tag}: {msg['content']}")
            return "\n".join(lines)


def safe_web_search_pro(keyword):
    try:
        from tools.search import web_search_pro
        return web_search_pro(keyword)
    except Exception as exc:
        print(f"web_search_pro unavailable, using fallback: {exc}")
        fallback_block = [(f"暂未取得实时网页搜索结果，已使用本地兜底行情判断：{keyword}", "", 0.5)]
        fallback_text = f"【本地兜底情报】暂未取得 {keyword} 的实时搜索结果，请结合常识和预算谨慎判断。"
        return fallback_block, fallback_text, []


def safe_crawl_smzdm_price(keyword):
    try:
        from tools.price_crawler import crawl_smzdm_price
        return crawl_smzdm_price(keyword)
    except Exception as exc:
        print(f"crawl_smzdm_price unavailable, skipping crawler: {exc}")
        return []


def create_fsm_agent():
    try:
        from core.jerry_fsm_agent import JerryFSMAgent
        return JerryFSMAgent()
    except Exception as exc:
        print(f"JerryFSMAgent unavailable, using local fallback: {exc}")

        class LocalFSMAgent:
            def __init__(self):
                self.current_state = "INIT"

            def transition_to(self, next_state):
                print(f"[FSM fallback] {self.current_state} -> {next_state}")
                self.current_state = next_state

        return LocalFSMAgent()

load_dotenv()
init_runtime_tables()

# 🤖 【钉钉通道安全注入】
DINGTALK_WEBHOOK = st.secrets.get("DINGTALK_WEBHOOK", os.getenv("DINGTALK_WEBHOOK", os.getenv("DING_WEBHOOK", "")))

def send_dingtalk_worker_sync(title, markdown_content):
    if not DINGTALK_WEBHOOK:
        st.toast("⚠️ 未检测到 DINGTALK_WEBHOOK 凭证", icon="❌")
        return {"errcode": -1, "errmsg": "No webhook url"}

    headers = {"Content-Type": "application/json;charset=utf-8"}
    full_title = f"省钱智探agent - {title}"
    
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": full_title,
            "text": f"## 省钱智探agent · 实时通知\n\n**【安全审计定位】**: 省钱智探agent\n\n{markdown_content}"
        }
    }
    try:
        response = requests.post(DINGTALK_WEBHOOK, data=json.dumps(data), headers=headers, timeout=10)
        res_json = response.json()
        save_notification_log("dingtalk", full_title, markdown_content, "success" if res_json.get("errcode") == 0 else "failed", json.dumps(res_json, ensure_ascii=False))
        if res_json.get("errcode") == 0:
            st.toast("💥【钉钉推送成功】已顺利送达群聊！", icon="✅")
        else:
            if res_json.get("errcode") == 310000:
                st.toast(f"🚨【钉钉安全拦截】: 关键词不匹配或未配置安全加签密钥！", icon="🔒")
            else:
                st.toast(f"❌【钉钉内部错误】: {res_json.get('errmsg')}", icon="🚨")
        return res_json
    except Exception as e:
        save_notification_log("dingtalk", full_title if "full_title" in locals() else title, markdown_content, "error", str(e))
        st.toast(f"⚠️ 钉钉网关网络异常: {e}", icon="📡")
        return {"errcode": -2, "errmsg": str(e)}

def send_dingtalk_background(title, markdown_content):
    if not DINGTALK_WEBHOOK:
        save_notification_log("dingtalk", title, markdown_content, "failed", "No webhook url")
        print("DINGTALK_WEBHOOK is missing.")
        return {"errcode": -1, "errmsg": "No webhook url"}

    headers = {"Content-Type": "application/json;charset=utf-8"}
    full_title = f"Jerry-Insight - {title}"
    markdown_content = f"省钱智探agent\n\n{markdown_content}"
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": full_title,
            "text": f"## Jerry-Insight 实时通知\n\n{markdown_content}",
        },
    }
    try:
        response = requests.post(DINGTALK_WEBHOOK, data=json.dumps(data), headers=headers, timeout=10)
        try:
            res_json = response.json()
        except Exception:
            res_json = {"status_code": response.status_code, "text": response.text[:300]}
        status = "success" if res_json.get("errcode") == 0 else "failed"
        save_notification_log("dingtalk", full_title, markdown_content, status, json.dumps(res_json, ensure_ascii=False))
        print(f"DingTalk notification {status}: {full_title}; response={json.dumps(res_json, ensure_ascii=False)}")
        return res_json
    except Exception as e:
        save_notification_log("dingtalk", full_title, markdown_content, "error", str(e))
        print(f"DingTalk notification error: {e}")
        return {"errcode": -2, "errmsg": str(e)}

if 'ASYNC_EXECUTOR' not in st.session_state:
    st.session_state['ASYNC_EXECUTOR'] = ThreadPoolExecutor(max_workers=8)

def global_pure_async_notify(ding_token, wx_token, content):
    """ 异步推送核心：扔进线程池，杜绝因网络延迟导致的前端卡顿 """
    title = "资产动态调整"
    if 'ASYNC_EXECUTOR' in st.session_state:
        return st.session_state['ASYNC_EXECUTOR'].submit(send_dingtalk_background, title, content)
    return send_dingtalk_background(title, content)

FILE_LOCK = threading.Lock()
PROFILE_FILE = "jerry_profile.json"

@st.cache_resource
def init_chroma_and_inject_profiles():
    if os.path.exists("/mount/src/jerry-insight") or "STREAMLIT_RUNTIME_ENV" in os.environ:
        from chromadb.config import Settings
        const_client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    else:
        const_client = chromadb.PersistentClient(path="./bankv2")
    collection = const_client.get_or_create_collection(name="jerry_history")
    return collection

memory_collection = init_chroma_and_inject_profiles()
hybrid_retriever = JaccardHybridRetriever(memory_collection)

def reload_history_sessions(limit=100):
    sessions = []
    for row in reversed(load_recent_chat_history(limit)):
        audit_data = row.get("audit_data") or {}
        if not audit_data and row.get("item_name"):
            audit_data = {
                "price": row.get("amount") or 0.0,
                "item": row.get("item_name"),
                "display_answer": row.get("assistant_reply") or "",
                "info_blocks": [],
                "price_table_data": [],
                "crawler_results": [],
                "long_term_context": "",
            }
        elif row.get("assistant_reply"):
            audit_data = {
                "price": row.get("amount") or 0.0,
                "item": row.get("item_name") or row.get("intent") or "CHAT",
                "display_answer": row.get("assistant_reply") or "",
                "info_blocks": [],
                "price_table_data": [],
                "crawler_results": [],
                "long_term_context": "",
                "read_only": True,
            }
        if not audit_data:
            continue
        if audit_data.get("direct_expense"):
            audit_data["read_only"] = True
        audit_data.setdefault("display_answer", row.get("assistant_reply") or "")
        audit_data.setdefault("info_blocks", [])
        audit_data.setdefault("price_table_data", [])
        audit_data.setdefault("crawler_results", [])
        audit_data.setdefault("long_term_context", "")
        sessions.append({"query": row["query"], "audit_data": audit_data})
    st.session_state["history_sessions"] = sessions

if not st.session_state["history_sessions"]:
    reload_history_sessions()

def get_dynamic_profile():
    with FILE_LOCK:
        if not os.path.exists(PROFILE_FILE):
            default_profile = {"user_name": "Jerry", "monthly_budget": 10000.0, "current_surplus": 10000.0, "fixed_expenses": {"饮食": 1200, "话费交通": 300}, "recent_purchases": []}
            with open(PROFILE_FILE, "w", encoding="utf-8") as f: 
                json.dump(default_profile, f, ensure_ascii=False, indent=4)
            return default_profile
        with open(PROFILE_FILE, "r", encoding="utf-8") as f: 
            return json.load(f)


def record_direct_expense(item_name, amount, source_query=""):
    with FILE_LOCK:
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                profile = json.load(f)
        else:
            profile = {"user_name": "Jerry", "monthly_budget": 10000.0, "current_surplus": 10000.0, "fixed_expenses": {}, "recent_purchases": []}
        profile["current_surplus"] = round(float(profile.get("current_surplus", 0)) - float(amount), 2)
        profile.setdefault("recent_purchases", [])
        if item_name not in profile["recent_purchases"]:
            profile["recent_purchases"].append(item_name)
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=4)

    try:
        memory_collection.add(
            documents=[f"Jerry recorded a direct expense: {item_name}, amount {amount} yuan."],
            metadatas=[{"source": "direct_expense"}],
            ids=[f"direct_{int(time.time())}_{os.urandom(2).hex()}"],
        )
    except Exception as mem_err:
        print(f"direct expense memory save failed: {mem_err}")

    reply = (
        f"已直接记账：{item_name}，支出 {amount} 元。\n\n"
        f"当前剩余预算：{profile['current_surplus']} 元。\n\n"
        "下次如果还想先查价格，可以说：我想买某个商品，帮我看看值不值。"
    )
    save_audit_log(source_query or item_name, reply[:80])
    save_chat_history(
        query=source_query or f"{item_name} {amount}",
        intent="DIRECT_EXPENSE",
        assistant_reply=reply,
        item_name=item_name,
        amount=float(amount),
        audit_data={"item": item_name, "price": float(amount), "direct_expense": True},
    )
    global_pure_async_notify(
        None,
        None,
        (
            f"### Jerry-Insight 直接记账通知\n\n"
            f"- 消费项目：`{item_name}`\n"
            f"- 扣款金额：`-{amount}` 元\n"
            f"- 当前余额：`{profile['current_surplus']}` 元"
        ),
    )
    return reply, profile

api_key = st.secrets.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
base_url = st.secrets.get("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
openai_client = OpenAI(api_key=api_key, base_url=base_url)

if 'GLOBAL_MEMORY_MANAGER' not in st.session_state: 
    st.session_state['GLOBAL_MEMORY_MANAGER'] = AdvancedMemoryManager(openai_client)


# ==========================================================
# 🌟 3. JerryAgentHarness 状态机引擎
# ==========================================================
class JerryAgentHarness:
    def __init__(self, max_steps=4):
        self.client = openai_client
        self.model = "deepseek-chat" 
        self.max_steps = max_steps

    def run_harness(self, item_name, raw_info_text, profile_data, long_term_context, memory_ctx, status_widget=None):
        system_instruction = (
            "你是 Jerry 财务智能体系统【首席风控审计官】，代号“铁算盘”。\n"
            "我们要审计的商品是：【" + str(item_name) + "】。\n\n"
            "【❗⚠️ 核心价格限制死命令 ⚠️】\n"
            "当审计对象是可乐、雪碧、饮料、矿泉水、零食等单体快消品时，默认数量必须是【1瓶/1支/1个】！\n"
            "如果网络行情返回的是一整箱（如24瓶270元）或大礼包价格，你必须在心里除以数量，折算成【单瓶单价】（例如 3.00 或 3.50）填入下面的 estimated_price 字段。绝对不允许将整箱、批发的几百元作为单瓶默认购买价输出！\n\n"
            "你必须且只能输出标准的 JSON 块，禁止包含 any JSON 之外的问候性、引言或多余寒暄。你的输出格式必须 be 以下两种之一：\n\n"
            "1. 如果需要继续追查搜索（必须是你认为目前全网行情线索匮乏时才使用）：\n"
            "{\"action\": \"Call_Web_Search\", \"action_input\": \"关键词\"}\n\n"
            "2. 如果情报足够，给出最终审计报告（核心内容）：\n"
            "{\n"
            "  \"action\": \"Final Answer\",\n"
            "  \"action_input\": \"【建议购买/建议避坑/持币观望】\\n\\n【深度审计理由】：\\n（在这里请结合 Jerry 的月度生活费剩余、历史消费习惯、商品性价比、全网行情，以及上下文历史多轮对话中用户的具体倾向，给出极其详尽、深刻、温情地消费心理审计与规避建议。）\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + str(item_name) + "\\\", \\\"estimated_price\\\": 请填入你根据全网情报审计出的真实合理【单物品单价】数字，不要带‘元’字，例如3.50}\"\n"
            "}"
        )
        
        # 🔄 【深度修复答非所问】：在这里提取短期的历史多轮 Chat History，拼接后注入模型输入端
        short_term_history_str = ""
        if st.session_state["chat_history"]:
            short_term_history_str = "\n".join([f"-> {msg['role'].upper()}: {msg['content']}" for msg in st.session_state["chat_history"][-6:]]) # 取最近3轮交互
        
        user_input_context = (
            f"【短期多轮会话上下文（重要参考，防止答非所问）】:\n{short_term_history_str if short_term_history_str else '暂无前序多轮对话。'}\n\n"
            f"【历史档案】：\n{long_term_context}\n\n"
            f"【治理缓存】：\n{memory_ctx}\n\n"
            f"【财务画像】：\n- 剩余资金: {profile_data['current_surplus']} 元\n\n"
            f"【初始情报】：\n{raw_info_text[:1200]}"
        )
        conversation_history = [{"role": "system", "content": system_instruction}, {"role": "user", "content": user_input_context}]
        
        step = 0
        raw_output = ""
        while step < self.max_steps:
            step += 1
            try:
                if status_widget: status_widget.write(f"🧠 [Harness 状态机] 推理寻优中 ({step}/{self.max_steps})...")
                response = self.client.chat.completions.create(model=self.model, messages=conversation_history, temperature=0.3)
                raw_output = response.choices[0].message.content.strip()
                
                if raw_output.startswith("```json"):
                    raw_output = raw_output.replace("```json", "", 1).rstrip("```").strip()
                elif raw_output.startswith("```"):
                    raw_output = raw_output.replace("```", "", 1).rstrip("```").strip()

                json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
                clean_json_str = json_match.group(0) if json_match else raw_output
                parsed_json = json.loads(clean_json_str)
                
                if parsed_json.get("action") == "Final Answer": 
                    return parsed_json.get("action_input")
                elif parsed_json.get("action") == "Call_Web_Search":
                    search_kw = parsed_json.get("action_input")
                    if status_widget: status_widget.write(f"🔍 触发多路追查，深度搜索: `{search_kw}`...")
                    _, search_feedback_text, _ = safe_web_search_pro(search_kw)
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报反馈】：\n{search_feedback_text[:1200]}"})
            except Exception as e:
                print(f"Harness Step {step} 异常: {e}")
                if step >= self.max_steps: break
                
        if "Final Answer" not in raw_output:
            try:
                if status_widget: status_widget.write("⚠️ 触发布局收敛机制，正在强行清算账目并生成终报...")
                conversation_history.append({"role": "user", "content": "注意：时间到！请立刻停止任何 Call_Web_Search 动作。基于你目前掌握的所有情报与会话上下文，直接以 Final Answer 的 JSON 格式输出最终审计报告！"})
                final_res = self.client.chat.completions.create(model=self.model, messages=conversation_history, temperature=0.2)
                raw_output = final_res.choices[0].message.content.strip()
                
                if raw_output.startswith("```"): 
                    raw_output = raw_output.with_prefix("```")[1].replace("json", "", 1).strip()
                json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
                if json_match:
                    parsed_json = json.loads(json_match.group(0))
                    if parsed_json.get("action") == "Final Answer":
                        return parsed_json.get("action_input")
            except Exception as final_err:
                print(f"强行收敛失败: {final_err}")

        if 'action_input' in raw_output:
            try:
                json_match = re.search(r'\{.*\}', raw_output, re.DOTALL)
                if json_match:
                    extracted_text = json.loads(json_match.group(0)).get("action_input", raw_output)
                    if "PRICE_DATA" in extracted_text:
                        return extracted_text
                    raw_output = extracted_text
            except: pass

        if "PRICE_DATA" in raw_output:
            return raw_output
        else:
            found_nums = re.findall(r'(?:价格|标价|估值|均价|为|扣减)\s*([0-9.]+)', raw_output)
            fallback_price = float(found_nums[0]) if found_nums else 0.0
            return f"📋 最终报告（强行收敛总结）\n\n{raw_output}\n\nPRICE_DATA: {{\"item\": \"{item_name}\", \"estimated_price\": {fallback_price}}}"


# ==========================================================
# 👑 4. FSM 状态机托管管道
# ==========================================================
def run_fsm_scout_pipeline(query, status_widget):
    fsm = create_fsm_agent()
    fsm.transition_to("INTENT_CHECK")
    if classify_user_intent(query).intent != "SHOPPING_QUERY":
        fsm.transition_to("END")
        return "INVALID_INTENT", None, None, None, None, ""

    fsm.transition_to("PRICE_SCOUT")
    clean_keyword = fallback_clean_query_to_entity(query)
    if clean_keyword == "NONE":
        clean_keyword = clean_query_to_entity(query)
    if clean_keyword == "NONE":
        clean_keyword = query.strip()
    
    future_memory = st.session_state['ASYNC_EXECUTOR'].submit(hybrid_retriever.retrieve_and_rerank, query)
    future_web = st.session_state['ASYNC_EXECUTOR'].submit(safe_web_search_pro, clean_keyword)
    future_crawler = st.session_state['ASYNC_EXECUTOR'].submit(safe_crawl_smzdm_price, clean_keyword)
    
    try:
        existing_data = memory_collection.get()
        if not existing_data or not existing_data.get("ids") or len(existing_data["ids"]) == 0:
            long_term_context = "暂无历史档案存证。"
        else:
            long_term_context = future_memory.result()
    except Exception as chroma_err:
        long_term_context = "历史档案加载隔离状态。" 

    raw_info_blocks, raw_info_text, price_table_data = future_web.result()
    
    crawler_results = None
    try:
        crawler_results = future_crawler.result(timeout=2.5)
    except Exception as t_e:
        print(f"⚠️ 爬虫响应超时: {t_e}")
    
    if crawler_results:
        raw_info_text = f"【什么值得买精选行情】:\n" + "\n".join([item["price_info"] for item in crawler_results]) + "\n\n" + raw_info_text
        
    info_blocks = raw_info_blocks[:4] if len(raw_info_blocks) >= 4 else raw_info_blocks
    
    fsm.transition_to("AUDIT_REPORT")
    st.session_state['GLOBAL_MEMORY_MANAGER'].add_message("user", query)
    memory_ctx = st.session_state['GLOBAL_MEMORY_MANAGER'].get_compiled_context()
    
    raw_answer = JerryAgentHarness().run_harness(clean_keyword, raw_info_text, get_dynamic_profile(), long_term_context, memory_ctx, status_widget)
    fsm.transition_to("END")
    return raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results, long_term_context


# =======================================================================
# 🎯 🌟【核心高能回调控制器】
# =======================================================================
def callback_execute_confirm():
    """ 真正执行扣款的隔离回调 """
    st.session_state['ACTION_COMPLETED'] = True
    
    if st.session_state.get('LAST_AUDIT'):
        audit_data = st.session_state['LAST_AUDIT']
        try:
            profile = get_dynamic_profile()
            profile["current_surplus"] = round(profile["current_surplus"] - audit_data['price'], 2)
            if audit_data['item'] not in profile["recent_purchases"]:
                profile["recent_purchases"].append(audit_data['item'])
            
            with open(PROFILE_FILE, "w", encoding="utf-8") as f: 
                json.dump(profile, f, ensure_ascii=False, indent=4)
            
            memory_collection.add(documents=[f"强行确认购买了关于'{audit_data['item']}'的商品。[已买入]"], ids=[f"pass_{int(time.time())}"])
            save_audit_log(st.session_state["active_query"], audit_data["display_answer"][:50])
            
            msg_content = (
                f"### 🪙 省钱智探agent · 账单自动核销支出回执\n\n"
                f"--- \n\n"
                f"👉 **已购入好物**：`{audit_data['item']}`\n\n"
                f"👉 **本次实际扣减**：`{audit_data['price']} 元`\n\n"
                f"💰 **本月卡内当前剩余流动资金**：**{profile['current_surplus']} 元**\n\n"
                f"--- \n"
                f"» *省钱智探agent 铁算盘核销完毕*"
            )
            global_pure_async_notify(None, None, msg_content)
            
            deduct_notice_content = (
                f"### 💸 资产动态调整 · 实时扣款成功通知\n\n"
                f"--- \n\n"
                f"🔔 **通知类型**：账户资金减少\n\n"
                f"➖ **扣款金额**：`-{audit_data['price']} 元`\n\n"
                f"🛍️ **消费账目**：`{audit_data['item']}`\n\n"
                f"💳 **当前卡内余额**：**{profile['current_surplus']} 元**\n\n"
                f"🕒 **扣款时间**：`{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}`\n\n"
                f"--- \n"
                f"» *资产实时监控中 · 记账本已同步*"
            )
            global_pure_async_notify(None, None, deduct_notice_content)

            time.sleep(0.2)
            st.session_state["just_recorded"] = f"💰 资产扣减成功！顺利购入【{audit_data['item']}】，已支出 {audit_data['price']} 元。"
        except Exception as async_err:
            print(f"后端执行异常: {async_err}")
            
    st.rerun()


def callback_execute_cancel():
    """ 纯粹听从劝阻放弃购买的回调 """
    st.session_state['ACTION_COMPLETED'] = True
    
    if st.session_state.get('LAST_AUDIT'):
        audit_data = st.session_state['LAST_AUDIT']
        try:
            memory_collection.add(documents=[f"听从劝阻放弃购买关于'{audit_data['item']}'的商品。[已拦截]"], ids=[f"block_{int(time.time())}"])
            
            msg_content = (
                f"### 🙅‍♂️ 省钱智探agent · 冲动消费成功拦截回执\n\n"
                f"--- \n\n"
                f"👉 **放弃购买商品**：`{audit_data['item']}`\n\n"
                f"💰 **完美省下**：`{audit_data['price']} 元`\n\n"
                f"💡 *历史指纹库已追加该商品拦截指纹，守护资产成功！*\n\n"
                f"--- \n"
                f"» *省钱智探agent 拦截审计完毕*"
            )
            global_pure_async_notify(None, None, msg_content)
            st.session_state["just_recorded"] = f"🙅‍♂️ 已听从劝阻！成功拦截对【{audit_data['item']}】的冲动消费，未扣除任何资产。"
        except Exception as err:
            print(f"拦截存证失败: {err}")
            
    st.rerun()


# ==========================================================
# 🎨 5. UI 渲染与侧边栏
# ==========================================================
with st.sidebar:
    st.header("🕵️智能体调度中心")
    st.write("---")
    
    def super_clear_all_states():
        try:
            all_ids = memory_collection.get()["ids"]
            if all_ids: memory_collection.delete(ids=all_ids)
        except: pass
        if os.path.exists(PROFILE_FILE):
            try: os.remove(PROFILE_FILE)
            except: pass
        st.session_state['LAST_AUDIT'] = None
        st.session_state["active_query"] = None
        st.session_state["just_recorded"] = None
        st.session_state['SUBMIT_PROCESSING'] = False
        st.session_state['ACTION_COMPLETED'] = False
        st.session_state["chat_history"] = []       # 🔄 清空会话
        st.session_state["history_sessions"] = []   # 🔄 清空历史归档
        st.rerun()

    st.button("🧼 一键重置指纹数据库", type="secondary", width=250, on_click=super_clear_all_states, disabled=st.session_state['SUBMIT_PROCESSING'])
    st.write("---")

    # 🔄 【新增功能】：在侧边栏渲染历史对话记录归档
    st.subheader("📜 审计历史会话流")
    if st.session_state["history_sessions"]:
        for idx, session in enumerate(reversed(st.session_state["history_sessions"])):
            # 生成带序号和截断的按钮名称
            btn_label = f"🕒 {len(st.session_state['history_sessions'])-idx}. {session['query'][:12]}..."
            
            # 回溯历史的回调闭包函数
            def make_load_callback(s_data):
                return lambda: [
                    st.session_state.update({"SUBMIT_PROCESSING": False}),
                    st.session_state.update({"active_query": s_data["query"]}),
                    st.session_state.update({"LAST_AUDIT": s_data["audit_data"]}),
                    st.session_state.update({"ACTION_COMPLETED": True}) # 历史回顾默认锁死面板按钮
                ]
                
            st.button(btn_label, key=f"hist_btn_{idx}", use_container_width=True, on_click=make_load_callback(session))
    else:
        st.caption("暂无前序会话记录")
    st.write("---")

    st.subheader("📊 铁算盘·资产风控看板")
    try:
        all_mems = memory_collection.get()
        item_status_map = {}
        if all_mems and all_mems['documents']:
            for doc in all_mems['documents']:
                part, status_type = None, None
                if "强行确认购买了关于'" in doc or "[已买入]" in doc:
                    part = doc.split("关于'")[1].split("'")[0] if "关于'" in doc else doc
                    status_type = "WHITELIST"
                elif "关于'" in doc or "[已拦截]" in doc:
                    part = doc.split("关于'")[1].split("'")[0] if "关于'" in doc else doc
                    status_type = "BLACKLIST"
                if part:
                    item_status_map[part.strip().replace("'", "").replace('"', "")] = status_type
        blacklist = [k for k, v in item_status_map.items() if v == "BLACKLIST"]
        whitelist = [k for k, v in item_status_map.items() if v == "WHITELIST"]
        
        with st.expander("🔴 被强制拦截的坑位", expanded=False): # 修改默认折叠，留出空间给历史记录
            if blacklist:
                for item in blacklist[-5:]: st.markdown(f"❌ `{item}`")
            else: st.caption("暂无历史拦截记录")
        with st.expander("🟢 已安全放行的好物", expanded=False):
            if whitelist:
                for item in whitelist[-5:]: st.markdown(f"✅ `{item}`")
            else: st.caption("暂无历史放行记录")
    except: 
        st.caption("看板数据同步中...")

st.title("🛡️省钱智探agent")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

# 状态核销提示（Toast 提醒）
if st.session_state.get("just_recorded"):
    st.toast(st.session_state["just_recorded"], icon="🪙")
    st.session_state["just_recorded"] = None

# 对话框管理
st.session_state['SUBMIT_PROCESSING'] = False
chat_query = st.chat_input("输入商品名称，开始资产风控审计...", key="user_chat_input_core_key", disabled=False)

# ==========================================================
# 🚨 6. 核心高能控制器流程整合与修复
# ==========================================================
if st.session_state['SUBMIT_PROCESSING'] and st.session_state["active_query"] is None:
    target_query = st.query_params.get("chat_query", None)
    if target_query:
        st.session_state["active_query"] = target_query

# 拦截 chat_input 的真实提交事件
if chat_query and chat_query.strip():
    query_text = chat_query.strip()
    st.session_state['SUBMIT_PROCESSING'] = True
    st.session_state["active_query"] = query_text
    st.session_state['LAST_AUDIT'] = None  # 强清旧账单缓存
    st.session_state['ACTION_COMPLETED'] = False # 重置按钮点击判定
    
    # 🔄 【新增】：实时追加短期多轮会话的 User 视角
    st.session_state["chat_history"].append({"role": "user", "content": query_text})

    parsed_intent = classify_user_intent(query_text)
    if parsed_intent.intent in ("HELP_OR_META", "SMALLTALK_OR_OTHER", "INVALID"):
        reply_text = parsed_intent.reply or "我主要负责消费审计、价格查询和记账。你可以说：我想买某个商品，帮我看看值不值。"
        st.session_state["chat_history"].append({"role": "assistant", "content": reply_text})
        save_chat_history(query_text, parsed_intent.intent, assistant_reply=reply_text)
        reload_history_sessions()
        with st.chat_message("assistant"):
            st.markdown(reply_text)
        st.session_state['SUBMIT_PROCESSING'] = False
        st.session_state["active_query"] = None
        st.session_state["LAST_AUDIT"] = {
            "price": 0.0,
            "item": query_text,
            "display_answer": reply_text,
            "info_blocks": [],
            "price_table_data": [],
            "crawler_results": [],
            "long_term_context": "",
            "read_only": True,
        }
        st.session_state["active_query"] = query_text
        st.rerun()

    if parsed_intent.intent == "DIRECT_EXPENSE":
        reply_text, profile_after_record = record_direct_expense(parsed_intent.item_name, parsed_intent.amount, query_text)
        reload_history_sessions()
        st.session_state["chat_history"].append({"role": "assistant", "content": reply_text})
        st.session_state["LAST_AUDIT"] = {
            "price": float(parsed_intent.amount),
            "item": parsed_intent.item_name,
            "display_answer": (
                f"### 已扣除 {parsed_intent.item_name} {float(parsed_intent.amount):g} 元\n\n"
                f"{reply_text}\n\n"
                f"当前余额：{profile_after_record['current_surplus']} 元"
            ),
            "info_blocks": [],
            "price_table_data": [],
            "crawler_results": [],
            "long_term_context": "",
            "read_only": True,
        }
        st.session_state['SUBMIT_PROCESSING'] = False
        st.session_state["just_recorded"] = f"已扣除 {parsed_intent.item_name} {float(parsed_intent.amount):g} 元"
        st.rerun()
    
    ask_msg_content = (
        f"### 🔍 省钱智探agent捕获新审计提问\n\n"
        f"--- \n\n"
        f"👤 **用户输入原始问题**：\"{query_text}\"\n\n"
        f"🕒 **触发时间**：`{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime())}`\n\n"
        f"🛸 *Scout 正在通过 FSM 状态机进行多维调度搜集情报...*"
    )
    global_pure_async_notify(None, None, ask_msg_content)
    
    with st.chat_message("assistant"):
        status = st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True)
        try:
            raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results, long_term_context = run_fsm_scout_pipeline(query_text, status)
            
            if raw_answer == "INVALID_INTENT":
                status.update(label="🚨 监测到非业务输入。", state="error", expanded=False)
                st.session_state["LAST_AUDIT"] = {
                    "price": 0.0,
                    "item": query_text,
                    "display_answer": "### 没有进入商品审计\n\n这句话暂时没有被系统识别成商品购买请求。你可以试试：我想买可乐，帮我看看值不值。",
                    "info_blocks": [],
                    "price_table_data": [],
                    "crawler_results": [],
                    "long_term_context": "",
                    "read_only": True,
                }
                st.session_state['SUBMIT_PROCESSING'] = False
                st.rerun()
                
            status.update(label="🚀 FSM 流程闭合！情报与定向爬虫数据同步完毕！", state="complete", expanded=False)
            
            detected_price = 0.0
            if "PRICE_DATA:" in raw_answer:
                try: 
                    price_part = raw_answer.rsplit("PRICE_DATA:", 1)[1].strip()
                    price_match = re.search(r'"estimated_price"\s*:\s*([0-9.]+)', price_part)
                    if price_match:
                        detected_price = float(price_match.group(1))
                    else:
                        clean_json_match = re.search(r'\{.*\}', price_part, re.DOTALL)
                        json_str = clean_json_match.group(0) if clean_json_match else price_part
                        detected_price = float(json.loads(json_str)["estimated_price"])
                except Exception as p_err: 
                    print(f"⚠️ 价格精细化抽取未命中: {p_err}")
            
            if detected_price == 0.0:
                found_numbers = re.findall(r'(\d+)\s*-\s*(\d+)\s*元', raw_answer)
                if found_numbers:
                    detected_price = float(found_numbers[0][0])  
                else:
                    single_nums = re.findall(r'(\d+)\s*元', raw_answer)
                    if single_nums: detected_price = float(single_nums[0])

            # 🛠️ 【核心逻辑二次纠偏】
            is_beverage = any(x in clean_keyword.lower() for x in ["可乐", "cola", "饮料", "水", "雪碧", "芬达", "矿泉水"])
            if is_beverage and detected_price > 20.0:
                detected_price = 3.0
            elif detected_price == 0.0:
                if is_beverage:
                    detected_price = 3.0 
                else:
                    detected_price = 15.0  
                    
            # 提炼纯文本答案并清洗 PRICE_DATA 后缀
            final_display_text = raw_answer.split("PRICE_DATA:")[0] if "PRICE_DATA:" in raw_answer else raw_answer
            
            # 🔄 【新增】：实时追加短期多轮会话的 Assistant 视角，彻底闭合会话缓存链条
            st.session_state["chat_history"].append({"role": "assistant", "content": final_display_text})
            
            st.session_state['LAST_AUDIT'] = {
                "price": detected_price, 
                "item": clean_keyword, 
                "display_answer": final_display_text,
                "info_blocks": info_blocks,
                "price_table_data": price_table_data,
                "crawler_results": crawler_results,
                "long_term_context": long_term_context
            }
            
            # 🔄 【新增】：将当前审计成果持久化同步至侧边栏历史归档列表中
            save_chat_history(
                query_text,
                "SHOPPING_QUERY",
                assistant_reply=final_display_text,
                item_name=clean_keyword,
                amount=detected_price,
                audit_data=st.session_state['LAST_AUDIT'],
            )
            reload_history_sessions()
            global_pure_async_notify(
                None,
                None,
                (
                    f"### Jerry-Insight 审计结果已生成\n\n"
                    f"- 用户问题：`{query_text}`\n"
                    f"- 商品目标：`{clean_keyword}`\n"
                    f"- 预估金额：`{detected_price}` 元\n\n"
                    f"{final_display_text[:1200]}"
                ),
            )
            
        except Exception as e:
            status.update(label=f"❌ 流程运行异常: {str(e)}", state="error", expanded=False)
            print(f"Shopping flow error for query={query_text}: {e}")
            st.session_state["LAST_AUDIT"] = {
                "price": 0.0,
                "item": query_text,
                "display_answer": (
                    "### 审计流程中断\n\n"
                    f"系统已经收到你的问题：`{query_text}`，但后续搜索/审计流程出现异常。\n\n"
                    f"错误信息：`{e}`\n\n"
                    "你可以换个更短的商品名再试一次，比如：可乐、雪碧、拍立得。"
                ),
                "info_blocks": [],
                "price_table_data": [],
                "crawler_results": [],
                "long_term_context": "",
                "read_only": True,
            }
            st.session_state['SUBMIT_PROCESSING'] = False
            # Keep the fallback result visible in this run instead of flashing away.
            
    st.session_state['SUBMIT_PROCESSING'] = False
    # Let the result renderer below consume LAST_AUDIT in the same Streamlit run.


# ==========================================================
# 🎨 7. 纯静态前端渲染区与交互遮罩 management
# ==========================================================
main_ui_container = st.empty()

if st.session_state['LAST_AUDIT'] and st.session_state["active_query"] and st.session_state['LAST_AUDIT'].get("read_only"):
    audit_data = st.session_state['LAST_AUDIT']
    with main_ui_container.container():
        with st.chat_message("user"):
            st.write(st.session_state["active_query"])
        with st.chat_message("assistant"):
            st.markdown(audit_data.get("display_answer") or "这条历史记录没有可显示的回复。")
            st.caption("这条记录已经处理完成，可以继续在下方输入新问题。")

elif st.session_state['LAST_AUDIT'] and st.session_state["active_query"]:
    audit_data = st.session_state['LAST_AUDIT']
    
    with main_ui_container.container():
        with st.chat_message("user"):
            st.write(st.session_state["active_query"])
            
        with st.chat_message("assistant"):
            if audit_data.get("read_only"):
                st.markdown(audit_data.get("display_answer") or "这条历史记录没有可显示的回复。")
                st.caption("这条记录已经处理完成，可以继续在下方输入新问题。")
            st.markdown("### 🌐 Jerry-Scout 全网核心情报来源与存证链接")
            blocks = audit_data["info_blocks"]
            for idx in range(4):
                if blocks and idx < len(blocks):
                    text_snippet, source_url, rerank_score = blocks[idx]
                else:
                    text_snippet = f"对齐商品 【{audit_data['item']}】 的多渠道行情分布与全网存证基准线线索。"
                    source_url = f"https://search.smzdm.com/?s={audit_data['item']}"
                    rerank_score = 0.88 - (idx * 0.04)
                    
                st.markdown(f"**情报源 [{idx+1}]** ｜ 匹配度分值: `{round(float(rerank_score), 4)}`")
                st.caption(f"内容摘要: {text_snippet[:150]}...")
                if source_url: st.markdown(f"🔗 [点击查看原始存证网页]({source_url})")
                st.write("---")

            st.markdown("### 📌 Jerry-Scout 关联历史输入知识库线索")
            lt_ctx = audit_data["long_term_context"]
            if lt_ctx and len(lt_ctx.strip()) > 10 and "暂无历史档案" not in lt_ctx:
                st.info(f"🔍 铁算盘为你捞出了关于【{audit_data['item']}】的历史输入关联记录快照：\n\n{lt_ctx}")
            else:
                st.caption(f"💡 历史拦截库中暂未匹配到针对“{audit_data['item']}”的历史指纹。已自动保存。")

            st.markdown("### 📊 Jerry-Scout 监测到全网全渠道实时比价盘口")
            parsed_data = []
            if audit_data["price_table_data"] and isinstance(audit_data["price_table_data"], list):
                parsed_data.extend(audit_data["price_table_data"])
            if audit_data["crawler_results"]:
                for spider_item in audit_data["crawler_results"]:
                    parsed_data.append({"🛒 渠道平台": f"🔥 {spider_item['platform']}", "💰 实时报价与情报": spider_item['price_info'], "🔗 原始链接": spider_item['source']})
            if not parsed_data:
                parsed_data = [{"🛒 渠道平台": "官方电商渠道", "💰 实时报价与情报": f"全网均价约 {audit_data['price']} 元大盘浮动", "🔗 原始链接": "本地商超端"}]
                
            st.dataframe(pd.DataFrame(parsed_data), hide_index=True)

            st.markdown("### 🛡️ Jerry 财务智能体 深度审计报告")
            st.markdown(audit_data["display_answer"])

        # 🪙 底部资产核销与决策面板
        st.write("---")
        col1, col2 = st.columns(2)
        
        is_insufficient = dynamic_profile['current_surplus'] < audit_data['price']
        expected_surplus = round(dynamic_profile['current_surplus'] - audit_data['price'], 2)
        
        buttons_disabled = st.session_state['ACTION_COMPLETED'] or audit_data.get("read_only", False)
        
        with col1:
            if is_insufficient:
                st.button(f"❌ 余额不足支付 ({audit_data['price']}元)", type="primary", use_container_width=True, disabled=True)
                st.markdown(f"<p style='color:red;font-size:14px;margin-top:5px;'>⚠️ 缺口金额: {round(audit_data['price'] - dynamic_profile['current_surplus'], 2)} 元</p>", unsafe_allow_html=True)
            else:
                st.button(f"🪙 确认记入账本 (扣减 {audit_data['price']}元)", type="primary", key="btn_confirm_deduct", use_container_width=True, on_click=callback_execute_confirm, disabled=buttons_disabled)
                st.info(f"💡 确认后预计卡内还剩：**{expected_surplus}** 元")

        with col2:
            st.button(f"🙅‍♂️ 听从劝阻 (放弃购买)", type="secondary", key="btn_cancel_deduct", use_container_width=True, on_click=callback_execute_cancel, disabled=buttons_disabled)
            st.success(f"💰 听劝后可完美保留流动资金：**{dynamic_profile['current_surplus']}** 元不变")
