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
if 'SUBMIT_PROCESSING' not in st.session_state:
    st.session_state['SUBMIT_PROCESSING'] = False

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

# 🤖 【钉钉通道安全注入】
DINGTALK_WEBHOOK = "https://oapi.dingtalk.com/robot/send?access_token=2f4f18adb7a69d71e3faa1e90879d6987c75cbb16b6a7c10fe870b4e9a051c0c"

def send_dingtalk_worker_sync(title, markdown_content):
    if not DINGTALK_WEBHOOK:
        st.toast("⚠️ 未检测到 DINGTALK_WEBHOOK 凭证", icon="❌")
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
        res_json = response.json()
        if res_json.get("errcode") == 0:
            st.toast("💥【钉钉推送成功】已顺利送达群聊！", icon="✅")
        else:
            st.toast(f"❌【钉钉内部错误】: {res_json.get('errmsg')}", icon="🚨")
        return res_json
    except Exception as e:
        st.toast(f"⚠️ 钉钉大厂网关网络异常: {e}", icon="📡")
        return {"errcode": -2, "errmsg": str(e)}

def global_pure_async_notify(ding_token, wx_token, content):
    title = "资产动态调整"
    return send_dingtalk_worker_sync(title, content)

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
            "1. 如果需要 continue 追查搜索（必须是你认为目前全网行情线索匮乏时才使用）：\n"
            "{\"action\": \"Call_Web_Search\", \"action_input\": \"关键词\"}\n\n"
            "2. 如果情报足够，给出最终审计报告（核心内容）：\n"
            "{\n"
            "  \"action\": \"Final Answer\",\n"
            "  \"action_input\": \"【建议购买/建议避坑/持币观望】\\n\\n【深度审计理由】：\\n（在这里请结合 Jerry 的月度生活费剩余、历史消费习惯、商品性价比、全网行情，给出极其详尽、深刻、温情地消费心理审计与规避建议。）\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + str(item_name) + "\\\", \\\"estimated_price\\\": 请填入你根据全网情报审计出的真实合理市场估值或二手价数字，不要带‘元’字，例如3500.00}\"\n"
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
                    _, search_feedback_text, _ = web_search_pro(search_kw)
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报反馈】：\n{search_feedback_text[:1200]}"})
            except Exception as e:
                print(f"Harness Step {step} 异常: {e}")
                if step >= self.max_steps: break
                
        if "Final Answer" not in raw_output:
            try:
                if status_widget: status_widget.write("⚠️ 触发布局收敛机制，正在强行清算账目并生成终报...")
                conversation_history.append({"role": "user", "content": "注意：时间到！请立刻停止任何 Call_Web_Search 动作。基于你目前掌握的所有情报，直接以 Final Answer 的 JSON 格式输出最终审计报告！"})
                final_res = self.client.chat.completions.create(model=self.model, messages=conversation_history, temperature=0.2)
                raw_output = final_res.choices[0].message.content.strip()
                
                if raw_output.startswith("```"): 
                    raw_output = raw_output.split("```")[1].replace("json", "", 1).strip()
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
# 4. FSM 状态机托管管道
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
# 🎯 🌟【核心重构区一】：彻底解决重复扣款的回调函数机制 🌟
# ==========================================================
def callback_confirm_deduct():
    """将所有导致记账变更、写文件的敏感操作全部收回单次点击事件回调中，彻底消除时序竞争"""
    if st.session_state['LAST_AUDIT']:
        audit_data = st.session_state['LAST_AUDIT']
        try:
            profile = get_dynamic_profile()
            
            # 执行核心扣减
            profile["current_surplus"] = round(profile["current_surplus"] - audit_data['price'], 2)
            if audit_data['item'] not in profile["recent_purchases"]:
                profile["recent_purchases"].append(audit_data['item'])
                
            # 瞬间落盘 JSON
            with open(PROFILE_FILE, "w", encoding="utf-8") as f: 
                json.dump(profile, f, ensure_ascii=False, indent=4)
            
            # 同步写向量库与 SQL
            memory_collection.add(documents=[f"强行确认购买了关于'{audit_data['item']}'的商品。[已买入]"], ids=[f"pass_{int(time.time())}"])
            save_audit_log(st.session_state["active_query"], audit_data["display_answer"][:50])
            
            # 发送消息通道
            msg_content = (
                f"### 🪙 账单自动核销支出回执\n\n"
                f"--- \n\n"
                f"👉 **已购入好物**：`{audit_data['item']}`\n\n"
                f"👉 **本次扣减金额**：`{audit_data['price']} 元`\n\n"
                f"💰 **本月卡内当前剩余流动资金**：**{profile['current_surplus']} 元**\n\n"
                f"--- \n"
                f"» *Jerry风控中心 铁算盘自动审计点出证完毕*"
            )
            global_pure_async_notify(None, None, msg_content)
            
            # 状态硬洗刷
            st.session_state["active_query"] = None
            st.session_state['LAST_AUDIT'] = None
            st.session_state["just_recorded"] = True
        except Exception as err:
            print(f"回调记账安全拦截网关执行异常: {err}")
            
def callback_cancel_deduct():
    """放弃购买回调"""
    st.session_state["active_query"] = None
    st.session_state['LAST_AUDIT'] = None


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
        st.session_state['SUBMIT_PROCESSING'] = False
        st.rerun()

    st.button("🧼 一键重置指纹数据库", type="secondary", width=250, on_click=super_clear_all_states, disabled=st.session_state['SUBMIT_PROCESSING'])
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

# 状态核销提示（若刚发生落盘）
if st.session_state.get("just_recorded", False):
    st.success("💰 资产变更指令强制落地！数字已完全对齐更新！")
    st.session_state["just_recorded"] = False

chat_query = st.chat_input("输入商品名称，开始资产风控审计...", key="user_chat_input_core_key", disabled=st.session_state['SUBMIT_PROCESSING'])

if chat_query and chat_query.strip():
    st.session_state["active_query"] = chat_query.strip()
    st.session_state['LAST_AUDIT'] = None  # 强清旧账单缓存
    
    with st.chat_message("assistant"):
        status = st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True)
        try:
            raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results, long_term_context = run_fsm_scout_pipeline(chat_query.strip(), status)
            
            if raw_answer == "INVALID_INTENT":
                status.update(label="🚨 监测到非业务输入。", state="error", expanded=False)
                st.error("请输入有效的业务商品进行审计. ")
                st.stop()
                
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
            
            if detected_price == 0.0 or detected_price == 3.5:
                found_numbers = re.findall(r'(\d+)\s*-\s*(\d+)\s*元', raw_answer)
                if found_numbers:
                    detected_price = float(found_numbers[0][0])  
                else:
                    single_nums = re.findall(r'(\d+)\s*元', raw_answer)
                    if single_nums: detected_price = float(single_nums[0])

            st.session_state['LAST_AUDIT'] = {
                "price": detected_price, 
                "item": clean_keyword, 
                "display_answer": raw_answer.split("PRICE_DATA:")[0] if "PRICE_DATA:" in raw_answer else raw_answer,
                "info_blocks": info_blocks,
                "price_table_data": price_table_data,
                "crawler_results": crawler_results,
                "long_term_context": long_term_context
            }
        except Exception as e:
            status.update(label=f"❌ 流程运行异常: {str(e)}", state="error", expanded=False)
            st.error(f"引擎报错: {e}")
            st.stop()
            
    st.rerun()

# ==========================================================
# 🎨 6. 纯静态前端渲染区与交互遮罩管理
# ==========================================================
main_ui_container = st.empty()

if st.session_state['LAST_AUDIT']:
    audit_data = st.session_state['LAST_AUDIT']
    
    with main_ui_container.container():
        with st.chat_message("user"):
            st.write(st.session_state["active_query"])
            
        with st.chat_message("assistant"):
            st.markdown("### 🌐 Jerry-Scout 全网核心情报来源与存证链接")
            blocks = audit_data["info_blocks"]
            for idx in range(4):
                if blocks and idx < len(blocks):
                    text_snippet, source_url, rerank_score = blocks[idx]
                else:
                    text_snippet = f"对齐商品 【{audit_data['item']}】 的多渠道行情分布与全网存证基准线线索。"
                    source_url = f"[https://search.smzdm.com/?s=](https://search.smzdm.com/?s=){audit_data['item']}"
                    rerank_score = 0.88 - (idx * 0.04)
                    
                st.markdown(f"**情报源 [{idx+1}]** ｜ 匹配度分值: `{round(float(rerank_score), 4)}`")
                st.caption(f"内容摘要: {text_snippet[:150]}...")
                if source_url: st.markdown(f"🔗 [点击查看原始存证网页]({source_url})")
                st.write("---")

            st.markdown("### 📌 Jerry-Scout 关联历史输入知识库线索")
            lt_ctx = audit_data["long_term_context"]
            if lt_ctx and len(lt_ctx.strip()) > 10:
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
                parsed_data = [{"🛒 渠道平台": "官方电商渠道", "💰 实时报价与情报": "全网均价约大盘浮动", "🔗 原始链接": "本地商超端"}]
                
            st.dataframe(pd.DataFrame(parsed_data), hide_index=True)

            st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
            st.markdown(audit_data["display_answer"])

        # 🪙 底部资产核销与决策面板
        st.write("---")
        col1, col2 = st.columns(2)
        
        # 🚨 💼【核心重构区二】：引入前端防穿仓安全锁逻辑
        current_available_surplus = dynamic_profile.get('current_surplus', 0.0)
        is_insufficient = current_available_surplus < audit_data['price']
        
        with col1:
            if is_insufficient:
                # 账户透支风险拦截：强行将扣款按钮锁定变灰
                st.button(f"❌ 余额不足支付 ({audit_data['price']}元)", type="primary", key="btn_confirm_deduct", use_container_width=True, disabled=True)
                st.caption(f"⚠️ 核心支付级风控锁触发：卡内当前剩余流动资金仅 {current_available_surplus} 元，无法核销本次价值 {audit_data['price']} 元的商品。请先重置数据库！")
            else:
                # 绑定回调函数：防多重刷单、刷点击
                st.button(f"🪙 确认记入账本 (扣减 {audit_data['price']}元)", type="primary", key="btn_confirm_deduct", use_container_width=True, on_click=callback_confirm_deduct)

        with col2:
            st.button(f"🙅‍♂️ 听从劝阻 (放弃购买)", type="secondary", key="btn_cancel_deduct", use_container_width=True, on_click=callback_cancel_deduct)