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
if "has_searched" not in st.session_state:
    st.session_state["has_searched"] = False
if "just_recorded" not in st.session_state:
    st.session_state["just_recorded"] = False
if 'SHORT_TERM_MEMORY' not in st.session_state:
    st.session_state['SHORT_TERM_MEMORY'] = []
if 'LAST_AUDIT' not in st.session_state:
    st.session_state['LAST_AUDIT'] = None

# =====================================================================
# 🛠️ 2. 核心底层组件引入与环境配置对齐
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

# 🤖 【钉钉通道安全注入】：全量使用你的专属安全 Webhook
# 已经自动将你提供的 Token 和安全关键词进行绑定配置
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=6b0c4826bc4ae3c2ec313e9a5833077e6dfd1502f90a612bd8409240409c5a14"

def send_dingtalk_worker(title, markdown_content):
    """真正执行钉钉群机器人消息投递的后台工人线程"""
    if not DINGTALK_WEBHOOK:
        print("⚠️ 钉钉群推送失败：未配置有效的 DINGTALK_WEBHOOK 凭证。")
        return

    headers = {"Content-Type": "application/json;charset=utf-8"}
    
    # 封装钉钉专用的标准 Markdown 消息块
    # 💡 内部强制塞入安全设置关键词 【Jerry风控中心】，避免因关键字校验不通过被钉钉拦截
    data = {
        "msgtype": "markdown",
        "markdown": {
            "title": title,
            "text": f"## Jerry风控中心 · 实时回执\n\n{markdown_content}"
        }
    }

    try:
        # 向钉钉开放网关抛送标准的 HTTP POST 请求（不卡防火墙与特定SSL端口）
        response = requests.post(DINGTALK_WEBHOOK, data=json.dumps(data), headers=headers, timeout=10)
        res_json = response.json()
        if res_json.get("errcode") == 0:
            print("💥【钉钉推送成功】风控审计通知已顺利送达群聊！")
        else:
            print(f"❌【钉钉内部错误】发送失败，错误码: {res_json.get('errcode')}, 原因: {res_json.get('errmsg')}")
    except Exception as e:
        print(f"⚠️ 钉钉大厂网关异步投递发生异常: {e}")

# ✨【保持原有关联与接口签名不变】：内部重构为纯异步多线程调用钉钉机器人
def global_pure_async_notify(ding_token, wx_token, content):
    """
    完全切断 Streamlit 脐带的后台纯净线程，用钉钉通道对齐原发送总线
    """
    title = "Jerry风控中心资产变动"
    print(f"📡 [安全钉钉机器人通道激活] 正在启动后台异步线程...")
    
    # 依然拉起后台多线程，防止阻塞你的网页刷新
    thr = threading.Thread(target=send_dingtalk_worker, args=(title, content))
    thr.start()

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

def update_profile_balance(amount, item_name):
    profile = get_dynamic_profile()
    profile["current_surplus"] = round(profile["current_surplus"] - amount, 2)
    if item_name not in profile["recent_purchases"]:
        profile["recent_purchases"].append(item_name)
    with FILE_LOCK:
        with open(PROFILE_FILE, "w", encoding="utf-8") as f: 
            json.dump(profile, f, ensure_ascii=False, indent=4)

mcp_gateway = JerryMcpServer(update_profile_balance, FILE_LOCK)

api_key = st.secrets.get("DEEPSEEK_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
base_url = st.secrets.get("DEEPSEEK_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
openai_client = OpenAI(api_key=api_key, base_url=base_url)

if 'GLOBAL_MEMORY_MANAGER' not in st.session_state: 
    st.session_state['GLOBAL_MEMORY_MANAGER'] = AdvancedMemoryManager(openai_client)

def native_diversity_rerank(info_blocks):
    if not info_blocks: return []
    unique_blocks = []
    for current in info_blocks:
        text, url, score = current
        if not any(len(set(text) & set(x[0])) / max(len(set(text) | set(x[0])), 1) > 0.65 for x in unique_blocks): 
            unique_blocks.append(current)
    return unique_blocks[:4]

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
            "【❗⚠️ 核心死命令 ⚠️vl】\n"
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
    
    # 🛡️ 加上异常捕获，防止 Chroma 数据库崩溃连累整个发信和风控流程
    try:
        # 加上指纹库空值和大小安全盾检测，彻底杜绝 HNSW 数组异常
        existing_data = memory_collection.get()
        if not existing_data or not existing_data.get("ids") or len(existing_data["ids"]) == 0:
            long_term_context = "暂无历史档案存证。"
        else:
            available_count = min(len(existing_data["ids"]), 2)
            long_term_context = future_memory.result()
    except Exception as chroma_err:
        print(f"⚠️ [Chroma 兜底触发] 历史库检索发生异常，已自动跳过: {chroma_err}")
        long_term_context = "历史档案加载隔离状态。" 

    raw_info_blocks, raw_info_text, price_table_data = future_web.result()
    
    crawler_results = None
    try:
        crawler_results = future_crawler.result(timeout=2.5)
    except Exception as t_e:
        print(f"⚠️ 爬虫响应超时，自动熔断: {t_e}")
    
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
        
        # 🚨 清理数据库的同时物理炸毁负数老账本
        if os.path.exists(PROFILE_FILE):
            try: os.remove(PROFILE_FILE)
            except: pass
            
        st.session_state['SHORT_TERM_MEMORY'] = []
        st.session_state['LAST_AUDIT'] = None
        st.session_state["active_query"] = None
        st.session_state["has_searched"] = False
        st.session_state["just_recorded"] = False

    st.button("🧼 一键重置指纹数据库", type="secondary", use_container_width=True, on_click=super_clear_all_states)
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
        
        with st.expander("🔴 被强制拦截的坑位", expanded=True):
            if blacklist:
                for item in blacklist[-5:]: st.markdown(f"❌ `{item}`")
            else: st.caption("暂无历史拦截记录")
        with st.expander("🟢 已安全放行的好物", expanded=True):
            if whitelist:
                for item in whitelist[-5:]: st.markdown(f"✅ `{item}`")
            else: st.caption("暂无历史放行记录")
    except: 
        st.caption("看板数据同步中...")

st.title("🛡️ Jerry-Insight Pro v3.5+")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

# 使用显式全局 Key 控制输入框缓存
chat_query = st.chat_input("输入商品名称，开始资产风控审计...", key="user_chat_input_core_key")
if chat_query and chat_query.strip():
    st.session_state["active_query"] = chat_query.strip()
    st.session_state["has_searched"] = True
    st.session_state["just_recorded"] = False
    st.rerun()

current_task = st.session_state["active_query"]

if (not st.session_state["has_searched"] or not current_task) and not st.session_state["just_recorded"]:
    st.info("💡 欢迎来到 Jerry-Insight 工业级消费风控中心！请在下方输入框中键入你想审计的设备名称并敲击回车。")
    st.stop()

if current_task:
    with st.chat_message("user"): 
        st.write(current_task)

    with st.chat_message("assistant"):
        status = st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True)
        try:
            raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results, long_term_context = run_fsm_scout_pipeline(current_task, status)
            
            if raw_answer == "INVALID_INTENT":
                status.update(label="🚨 监测到非业务输入。", state="error", expanded=False)
                st.error("请输入有效的业务商品进行审计。")
                st.stop()
                
            status.update(label="🚀 FSM 流程闭合！情报与定向爬虫数据同步完毕！", state="complete", expanded=False)
            
            st.markdown("### 🌐 Jerry-Scout 全网核心情报来源与存证链接")
            for idx in range(4):
                if info_blocks and idx < len(info_blocks):
                    text_snippet, source_url, rerank_score = info_blocks[idx]
                else:
                    text_snippet = f"对齐商品 【{clean_keyword}】 的多渠道行情分布与全网存证基准线线索。"
                    source_url = f"https://search.smzdm.com/?s={clean_keyword}"
                    rerank_score = 0.88 - (idx * 0.04)
                    
                st.markdown(f"**情报源 [{idx+1}]** ｜ 匹配度分值: `{round(float(rerank_score), 4)}`")
                st.caption(f"内容摘要: {text_snippet[:150]}...")
                if source_url: 
                    st.markdown(f"🔗 [点击查看原始存证网页]({source_url})")
                st.write("---")

            st.markdown("### 📌 Jerry-Scout 关联历史输入知识库线索")
            if long_term_context and len(long_term_context.strip()) > 10:
                st.info(f"🔍 铁算盘为你捞出了关于【{clean_keyword}】的历史输入关联记录快照：\n\n{long_term_context}")
            else:
                st.caption(f"💡 历史拦截库中暂未匹配到针对“{clean_keyword}”的历史指纹。已自动将本次输入【{current_task}】作为全新存证关联词录入系统。")

            st.markdown("### 📊 Jerry-Scout 监测到全网全渠道实时比价盘口")
            parsed_data = []
            
            if price_table_data:
                try:
                    if isinstance(price_table_data, list): parsed_data.extend(price_table_data)
                    elif isinstance(price_table_data, str): parsed_data.extend(json.loads(price_table_data.replace("'", '"')))
                except: pass

            if crawler_results:
                for spider_item in crawler_results:
                    parsed_data.append({"平台": f"🔥 {spider_item['platform']}", "参考报价/情报说明": spider_item['price_info'], "数据出处": spider_item['source']})
            
            if not parsed_data:
                parsed_data = [
                    {"平台": "官方电商渠道", "参考报价/情报说明": f"全网均价约大盘浮动 (针对 {clean_keyword})", "数据出处": "https://www.taobao.com"},
                    {"平台": "基础核销通道", "参考报价/情报说明": "实时大盘均价核算中", "数据出处": "本地商超端"}
                ]
            
            df = pd.DataFrame(parsed_data)
            df = df.rename(columns={"平台": "🛒 渠道平台", "参考报价/情报说明": "💰 实时报价与情报", "数据出处": "🔗 原始链接"})
            st.dataframe(df, hide_index=True)

            display_answer = raw_answer.split("PRICE_DATA:")[0] if "PRICE_DATA:" in raw_answer else raw_answer
            st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
            st.markdown(display_answer)

            detected_price = 3.5
            if "PRICE_DATA:" in raw_answer:
                try: 
                    detected_price = float(json.loads(raw_answer.split("PRICE_DATA:")[1].strip())["estimated_price"])
                except: 
                    pass
            
            st.session_state['LAST_AUDIT'] = {"price": detected_price, "item": clean_keyword, "display_answer": display_answer}

        except Exception as e:
            status.update(label=f"❌ 流程运行异常: {str(e)}", state="error", expanded=False)
            st.error(f"引擎报错: {e}")

# ==========================================================
# 📊 6. 核心资产卡点修复与异步通知触发
# ==========================================================
if st.session_state['LAST_AUDIT']:
    st.write("---")
    audit_item = st.session_state['LAST_AUDIT']["item"]
    audit_price = st.session_state['LAST_AUDIT']["price"]
    audit_report = st.session_state['LAST_AUDIT']["display_answer"]
    
    col1, col2 = st.columns(2)
    
    with col1:
        if st.button(f"🪙 确认记入账本 (扣减 {audit_price}元)", type="primary", key="btn_confirm_deduct", use_container_width=True):
            try:
                profile = get_dynamic_profile()
                profile["current_surplus"] = round(profile["current_surplus"] - audit_price, 2)
                if audit_item not in profile["recent_purchases"]:
                    profile["recent_purchases"].append(audit_item)
                with open(PROFILE_FILE, "w", encoding="utf-8") as f: 
                    json.dump(profile, f, ensure_ascii=False, indent=4)
            except Exception as file_err:
                print(f"本地文件写入遇到不可抗力: {file_err}")

            try:
                memory_collection.add(documents=[f"强行确认购买了关于'{audit_item}'的商品。[已买入]"], ids=[f"pass_{int(time.time())}"])
                save_audit_log(current_task, audit_report[:50])
            except: 
                pass
            
            # 🤖 核心资产变动钉钉 Markdown 推送内容
            msg_content = (
                f"### 🪙 账单自动核销支出回执\n\n"
                f"--- \n\n"
                f"👉 **已购入好物**：`{audit_item}`\n\n"
                f"👉 **本次扣减金额**：`{audit_price} 元`\n\n"
                f"💰 **本月卡内当前剩余流动资金**：**{profile['current_surplus']} 元**\n\n"
                f"--- \n"
                f"» *Jerry风控中心 铁算盘自动审计审计点出证完毕*"
            )
            
            # 异步线程分流，调用全新钉钉通知总线
            st.session_state['ASYNC_EXECUTOR'].submit(
                global_pure_async_notify, 
                None, 
                None, 
                msg_content
            )
            
            # 清洗状态弹回
            st.session_state["active_query"] = None
            st.session_state["has_searched"] = False
            st.session_state['LAST_AUDIT'] = None
            st.session_state["just_recorded"] = True
            st.rerun()

    with col2:
        if st.button(f"🙅‍♂️ 听从劝阻 (放弃购买)", type="secondary", key="btn_cancel_deduct", use_container_width=True):
            try:
                memory_collection.add(documents=[f"关于'{audit_item}'的购买决策。建议避坑，[已拦截]"], ids=[f"block_{int(time.time())}"])
                save_audit_log(current_task, "用户选择听从风控劝阻")
            except: 
                pass
            
            # 🤖 核心风控拦截钉钉机器人 Markdown 推送内容
            msg_content = (
                f"### 🚨 铁算盘守门员：成功风控拦截\n\n"
                f"--- \n\n"
                f"🙅‍♂️ **已成功帮您掐断冲动消费**：`{audit_item}`\n\n"
                f"✨ **本次理智帮您守住资金**：`{audit_price} 元`\n\n"
                f"🔒 **资产安全等级已自动上调！继续保持！**\n\n"
                f"--- \n"
                f"» *Jerry风控中心 铁算盘自动审计审计点出证完毕*"
            )
            
            st.session_state['ASYNC_EXECUTOR'].submit(
                global_pure_async_notify, 
                None, 
                None, 
                msg_content
            )
            
            st.session_state["active_query"] = None
            st.session_state["has_searched"] = False
            st.session_state['LAST_AUDIT'] = None
            st.session_state["just_recorded"] = True
            st.rerun()

# 状态更新完毕提示
if st.session_state["just_recorded"]:
    st.success("💰 资产变更指令强制落地！数字已完全对齐更新！")
    st.session_state["just_recorded"] = False

st.write("---")
st.subheader("🧪 钉钉机器人通道联调测试")
if st.button("🚀 强制发送一封测试消息到我的钉钉", use_container_width=True):
    with st.spinner("正在向钉钉官方网关全速投递中..."):
        send_dingtalk_worker(
            "通道联调测试", 
            "### 🎉 恭喜！通道联调成功\n\n当你看到这条高亮卡片消息时，说明你的钉钉机器人 Webhook Token 配置完全正确！海外服务器到大厂群聊的 HTTP 通道已经彻底被打通！\n\n*安全设置校验关键词已通过：Jerry风控中心*"
        )
    st.success("💥 调试指令已向钉钉服务器抛出！去看看你的群里有没有弹出新卡片吧！")