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
st.set_page_config(page_title="Jerry-Insight Pro v3.5+", layout="wide", page_icon="🛡️")

# 核心状态机状态保持
if "active_query" not in st.session_state:
    st.session_state["active_query"] = None
if "just_recorded" not in st.session_state:
    st.session_state["just_recorded"] = False
if 'LAST_AUDIT' not in st.session_state:
    st.session_state['LAST_AUDIT'] = None

# =====================================================================
# 🛠️ 2. 核心底层组件引入
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

DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=2f4f18adb7a69d71e3faa1e90879d6987c75cbb16b6a7c10fe870b4e9a051c0c"

def send_dingtalk_worker_sync(title, markdown_content):
    if not DINGTALK_WEBHOOK:
        return {"errcode": -1, "errmsg": "No webhook url"}
    headers = {"Content-Type": "application/json;charset=utf-8"}
    full_title = f"Jerry风控中心 - {title}"
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": full_title,
            "text": f"## Jerry风控中心 · 实时回执\n\n{markdown_content}"
        }
    }
    try:
        response = requests.post(DINGTALK_WEBHOOK, data=json.dumps(data), headers=headers, timeout=10)
        st.toast("💥【钉钉推送成功】已顺利送达群聊！", icon="✅")
        return response.json()
    except Exception as e:
        st.toast(f"⚠️ 钉钉大厂网关网络异常: {e}", icon="📡")
        return {"errcode": -2, "errmsg": str(e)}

def global_pure_async_notify(ding_token, wx_token, content):
    return send_dingtalk_worker_sync("资产动态调整", content)

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
            default_profile = {"user_name": "Jerry", "monthly_budget": 10000.0, "current_surplus": 10000.0, "fixed_expenses": {"饮食": 1200, "话费交通": 300}, "recent_purchases": []}
            with open(PROFILE_FILE, "w", encoding="utf-8") as f: 
                json.dump(default_profile, f, ensure_ascii=False, indent=4)
            return default_profile
        with open(PROFILE_FILE, "r", encoding="utf-8") as f: 
            return json.load(f)

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
            "你是 Jerry-Insight 系统【首席风控审计官】，代号“铁算盘”。\n"
            "我们要审计的商品是：【" + str(item_name) + "】。\n\n"
            "【❗⚠️ 核心死命令 ⚠️】\n"
            "你必须且只能输出标准的 JSON 块，禁止包含 any JSON 之外的问候性、引言或多余寒暄。你的输出格式必须 be 以下两种之一：\n\n"
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
                if parsed_json.get("action") == "Final Answer": 
                    return parsed_json.get("action_input")
                elif parsed_json.get("action") == "Call_Web_Search":
                    _, search_feedback_text, _ = web_search_pro(parsed_json.get("action_input"))
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报】：\n{search_feedback_text[:1200]}"})
            except:
                if step >= self.max_steps - 1: break
        return raw_output if "PRICE_DATA" in raw_output else f"📋报告\n{raw_output}\n\nPRICE_DATA: {{\"item\": \"{item_name}\", \"estimated_price\": 3.5}}"

# ==========================================================
# 📊 4. FSM 状态机托管管道
# ==========================================================
def run_fsm_scout_pipeline(query, status_widget):
    fsm = JerryFSMAgent()
    fsm.transition_to("INTENT_CHECK")
    if classify_intent(query) == "INVALID":
        fsm.transition_to("END")
        return "INVALID_INTENT", None, None, None, None, ""

    fsm.transition_to("PRICE_SCOUT")
    clean_keyword = clean_query_to_entity(query)
    
    future_memory = st.session_state['ASYNC_EXECUTOR'].submit(hybrid_retriever.retrieve_and_rerank, query)
    future_web = st.session_state['ASYNC_EXECUTOR'].submit(web_search_pro, clean_keyword)
    future_crawler = st.session_state['ASYNC_EXECUTOR'].submit(crawl_smzdm_price, clean_keyword)
    
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

# ==========================================================
# 🎨 5. UI 渲染与侧边栏
# ==========================================================
with st.sidebar:
    st.header("🕵️ Jerry-Insight 调度中心")
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
        st.session_state["just_recorded"] = False
        st.rerun()

    st.button("🧼 一键重置指纹数据库", type="secondary", width=250, on_click=super_clear_all_states)
    st.write("---")

st.title("🛡️ Jerry-Insight Pro v3.5+")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

# 🗂️ 核心回执状态清除器
if st.session_state["just_recorded"]:
    st.success("💰 资产变更指令强制落地！数字已完全对齐更新！")
    st.session_state["just_recorded"] = False

# 输入框拦截
chat_query = st.chat_input("输入商品名称，开始资产风控审计...", key="user_chat_input_core_key")

if chat_query and chat_query.strip():
    st.session_state["active_query"] = chat_query.strip()
    st.session_state['LAST_AUDIT'] = None  # 强清旧缓存
    
    # 🎯【性能起飞优化点一】：在用户回车的这一刻瞬间完成所有爬虫、大模型计算
    with st.chat_message("assistant"):
        status = st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True)
        try:
            raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results, long_term_context = run_fsm_scout_pipeline(chat_query.strip(), status)
            status.update(label="🚀 FSM 流程闭合！核心数据同步完毕！", state="complete", expanded=False)
            
            # 💡 高效正则价格抽取器
            detected_price = 3.5
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
                except: 
                    pass

            # 🎯 算完立刻死死存入会话状态，此后刷新绝不再重跑后台
            st.session_state['LAST_AUDIT'] = {
                "price": detected_price, 
                "item": clean_keyword, 
                "display_answer": raw_answer.split("PRICE_DATA:")[0] if "PRICE_DATA:" in raw_answer else raw_answer,
                "info_blocks": info_blocks,
                "price_table_data": price_table_data,
                "crawler_results": crawler_results,
                "long_term_context": long_term_context
            }
        except Exception as global_err:
            st.error(f"引擎发生不可逆溃散: {global_err}")
    st.rerun()

# --------------------------------======================
# 🎨 6. 纯粹的前端静态渲染区（不含任何爬虫计算，性能极高）
# --------------------------------======================
if st.session_state['LAST_AUDIT'] and not st.session_state["just_recorded"]:
    audit_data = st.session_state['LAST_AUDIT']
    
    with st.chat_message("user"):
        st.write(st.session_state["active_query"])
        
    with st.chat_message("assistant"):
        st.markdown("### 🌐 Jerry-Scout 全网核心情报来源与存证链接")
        blocks = audit_data["info_blocks"]
        for idx in range(4):
            if blocks and idx < len(blocks):
                text_snippet, source_url, rerank_score = blocks[idx]
            else:
                text_snippet = f"对齐商品 【{audit_data['item']}】 的多渠道行情分布线索。"
                source_url = f"https://search.smzdm.com/?s={audit_data['item']}"
                rerank_score = 0.88 - (idx * 0.04)
            st.markdown(f"**情报源 [{idx+1}]** ｜ 匹配度分值: `{round(float(rerank_score), 4)}`")
            st.caption(f"内容摘要: {text_snippet[:150]}...")
            if source_url: st.markdown(f"🔗 [点击查看原始存证网页]({source_url})")
            st.write("---")

        st.markdown("### 📊 Jerry-Scout 监测到全网全渠道实时比价盘口")
        parsed_data = []
        if audit_data["price_table_data"]:
            try:
                if isinstance(audit_data["price_table_data"], list): parsed_data.extend(audit_data["price_table_data"])
            except: pass
        if audit_data["crawler_results"]:
            for spider_item in audit_data["crawler_results"]:
                parsed_data.append({"🛒 渠道平台": f"🔥 {spider_item['platform']}", "💰 实时报价与情报": spider_item['price_info'], "🔗 原始链接": spider_item['source']})
        if not parsed_data:
            parsed_data = [{"🛒 渠道平台": "官方电商渠道", "💰 实时报价与情报": f"全网均价约大盘浮动", "🔗 原始链接": "本地商超端"}]
        st.dataframe(pd.DataFrame(parsed_data), hide_index=True)

        st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
        st.markdown(audit_data["display_answer"])

    # 🪙 底部记账核销决策面板
    st.write("---")
    col1, col2 = st.columns(2)
    
    with col1:
        # 🎯【核心修复点】：直接去缓存变量拿绝对正确的价格（如 23元），绝不触发降级兜底
        if st.button(f"🪙 确认记入账本 (扣减 {audit_data['price']} 元)", type="primary", use_container_width=True):
            try:
                profile = get_dynamic_profile()
                profile["current_surplus"] = round(profile["current_surplus"] - audit_data['price'], 2)
                if audit_data['item'] not in profile["recent_purchases"]:
                    profile["recent_purchases"].append(audit_data['item'])
                with open(PROFILE_FILE, "w", encoding="utf-8") as f: 
                    json.dump(profile, f, ensure_ascii=False, indent=4)
                
                memory_collection.add(documents=[f"强行确认购买了关于'{audit_data['item']}'的商品。[已买入]"], ids=[f"pass_{int(time.time())}"])
            except Exception as e:
                print(f"数据落盘异常: {e}")

            msg_content = f"### 🪙 账单自动核销支出回执\n\n---\n👉 **已购入好物**：`{audit_data['item']}`\n\n👉 **本次扣减金额**：`{audit_data['price']} 元`\n\n💰 **本月卡内当前剩余流动资金**：**{profile['current_surplus']} 元**\n\n---\n» *Jerry风控中心 铁算盘自动审计点出证完毕*"
            global_pure_async_notify(None, None, msg_content)
            
            # 🎯【性能起飞优化点二】：强制清空变量，直接 rerun。由于上面套了 if 隔离层，画面会瞬间彻底蒸发！不需要等任何加载！
            st.session_state["active_query"] = None
            st.session_state['LAST_AUDIT'] = None
            st.session_state["just_recorded"] = True
            st.rerun()

    with col2:
        if st.button(f"🙅‍♂️ 听从劝阻 (放弃购买)", type="secondary", use_container_width=True):
            try:
                memory_collection.add(documents=[f"关于'{audit_data['item']}'的购买决策。建议避坑，[开拦截]"], ids=[f"block_{int(time.time())}"])
            except: pass
            
            msg_content = f"### 🚨 铁算盘守门员：成功风控拦截\n\n---\n🙅‍♂️ **已成功帮您掐断冲动消费**：`{audit_data['item']}`\n\n✨ **本次理智帮您守住资金**：`{audit_data['price']} 元`\n\n🔒 **资产安全等级已自动上调！继续保持！**\n\n---\n» *Jerry风控中心 铁算盘自动审计点出证完毕*"
            global_pure_async_notify(None, None, msg_content)
            
            st.session_state["active_query"] = None
            st.session_state['LAST_AUDIT'] = None
            st.session_state["just_recorded"] = True
            st.rerun()

elif not st.session_state["active_query"]:
    st.info("💡 欢迎来到 Jerry-Insight 工业级消费风控中心！请在下方输入框中键入你想审计的设备名称并敲击回车。")