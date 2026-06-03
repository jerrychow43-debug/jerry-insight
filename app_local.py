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

# ==========================================================
# 1. 核心路由、去噪与全新引入的状态机/爬虫组件
# ==========================================================
from core.router import classify_intent, clean_query_to_entity 
from core.intent_plus import classify_user_intent
from core.memory_manager import AdvancedMemoryManager
from core.hybrid_retriever import JaccardHybridRetriever
from tools.mcp_server import JerryMcpServer

from core.brain import ask_llm
from tools.search_local import web_search_pro
from tools.price_crawler import crawl_smzdm_price  # 🟢 完美引入新爬虫
from core.jerry_fsm_agent import JerryFSMAgent     # 🟢 完美引入新状态机
from data.sql_db import init_runtime_tables, load_recent_chat_history, save_audit_log, save_chat_history, save_notification_log
from dotenv import load_dotenv

try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): return "未检测到 notify 微信零件"
    def push_dingtalk(content, title=None): return "未检测到 notify 钉钉零件"

load_dotenv()
init_runtime_tables()
st.set_page_config(page_title="Jerry-Insight Pro v3.5+", layout="wide", page_icon="🛡️")

# 全局文件互斥锁，确保本地账本 I/O 数据不发生 Data Race
FILE_LOCK = threading.Lock()
PROFILE_FILE = "jerry_profile.json"

if 'ASYNC_EXECUTOR' not in st.session_state:
    st.session_state['ASYNC_EXECUTOR'] = ThreadPoolExecutor(max_workers=8)

@st.cache_resource
def init_chroma_and_inject_profiles():
    chroma_client = chromadb.PersistentClient(path="./memory_bank")
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
        save_notification_log("notify", title or "", content, "error", str(e))
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
    """
    核心资产闭环记账函数（已引入互斥锁原子保护，防止高并发写空文件崩溃）
    """
    with FILE_LOCK:
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                profile = json.load(f)
        else:
            profile = {"user_name": "Jerry", "monthly_budget": 2000.0, "current_surplus": 850.0, "fixed_expenses": {"饮食": 1200, "话费交通": 300}, "recent_purchases": []}
        
        # 精准核销资金
        profile["current_surplus"] = round(profile["current_surplus"] - amount, 2)
        if "recent_purchases" not in profile:
            profile["recent_purchases"] = []
        if item_name not in profile["recent_purchases"]:
            profile["recent_purchases"].append(item_name)
            
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=4)

mcp_gateway = JerryMcpServer(update_profile_balance, FILE_LOCK)


def record_direct_expense(item_name, amount, source_query=""):
    update_profile_balance(float(amount), item_name)
    profile = get_dynamic_profile()
    reply = (
        f"已直接记账：{item_name}，支出 {amount} 元。\n\n"
        f"当前剩余预算：{profile['current_surplus']} 元。\n\n"
        "如果你想先查价格，可以说：我想买某个商品，帮我看看值不值。"
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
    st.session_state['ASYNC_EXECUTOR'].submit(
        async_push_notification,
        (
            f"### Jerry-Insight 直接记账通知\n\n"
            f"- 消费项目：`{item_name}`\n"
            f"- 扣款金额：`-{amount}` 元\n"
            f"- 当前余额：`{profile['current_surplus']}` 元"
        ),
        "Jerry-Insight 直接记账通知",
    )
    return reply, profile

api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
openai_client = OpenAI(api_key=api_key, base_url="https://api.deepseek.com")

if 'GLOBAL_MEMORY_MANAGER' not in st.session_state:
    st.session_state['GLOBAL_MEMORY_MANAGER'] = AdvancedMemoryManager(openai_client)

if 'SHORT_TERM_MEMORY' not in st.session_state: st.session_state['SHORT_TERM_MEMORY'] = []
if 'LAST_AUDIT' not in st.session_state: st.session_state['LAST_AUDIT'] = None
if 'PENDING_NOTIFY' not in st.session_state: st.session_state['PENDING_NOTIFY'] = None
if 'HISTORY_SESSIONS' not in st.session_state:
    st.session_state['HISTORY_SESSIONS'] = load_recent_chat_history(20)

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

class JerryAgentHarness:
    def __init__(self, max_steps=4):
        self.client = openai_client
        self.model = "deepseek-chat" 
        self.max_steps = max_steps

    def run_harness(self, item_name, raw_info_text, profile_data, long_term_context, memory_ctx, status_widget=None):
        system_instruction = (
            "你是 Jerry-Insight 系统【首席风控审计官】，代号“铁算盘”。\n"
            "我们要审计的商品是：【" + item_name + "】。\n\n"
            "你必须严格遵循协议输出标准 JSON 块：\n"
            "1. {\"action\": \"Call_Web_search\", \"action_input\": \"关键词\"}\n"
            "2. {\"action\": \"Final Answer\", \"action_input\": \"报告文本...\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + item_name + "\\\", \\\"estimated_price\\\": 预估单价}\"}"
        )
        user_input_context = f"【历史档案】：\n{long_term_context}\n\n【治理缓存】：\n{memory_ctx}\n\n【财务画像】：\n- 剩余资金: {profile_data['current_surplus']} 元\n\n【初始情报】：\n{raw_info_text[:1000]}"
        conversation_history = [{"role": "system", "content": system_instruction}, {"role": "user", "content": user_input_context}]
        
        step = 0
        while step < self.max_steps:
            step += 1
            try:
                if status_widget: status_widget.write(f"🧠 [Harness 状态机] 推理寻优中 ({step}/{self.max_steps})...")
                response = self.client.chat.completions.create(model=self.model, messages=conversation_history, temperature=0.3)
                raw_output = response.choices[0].message.content.strip()
                
                if "```json" in raw_output:
                    raw_output = raw_output.split("```json")[1].split("```")[0].strip()
                elif "```" in raw_output:
                    raw_output = raw_output.split("```")[1].split("```")[0].strip()
                    
                parsed_json = json.loads(raw_output)
                action = parsed_json.get("action")
                action_input = parsed_json.get("action_input")

                if action == "Final Answer": return action_input
                elif action == "Call_Web_search":
                    _, search_feedback_text, _ = web_search_pro(action_input)
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报】：\n{search_feedback_text[:1200]}"})
            except:
                if step >= self.max_steps - 1:
                    return "⚠️ 【铁算盘兜底】格式异常收敛。\nPRICE_DATA: {\"item\": \"" + item_name + "\", \"estimated_price\": 100.0}"
        return "⚠️ 【Harness超时熔断】\nPRICE_DATA: {\"item\": \"" + item_name + "\", \"estimated_price\": 50.0}"

def async_push_notification(content, title=None):
    try:
        wx_res = push_wechat(content)
        save_notification_log("wechat", title or "", content, "sent", str(wx_res))
        ding_res = push_dingtalk(content, title=title)
        save_notification_log("dingtalk", title or "", content, "sent", str(ding_res))
    except Exception as e:
        print(f"后台静默发送失败: {e}")

if st.session_state['PENDING_NOTIFY']:
    task = st.session_state['PENDING_NOTIFY']
    st.session_state['ASYNC_EXECUTOR'].submit(async_push_notification, task["content"], task["title"])
    st.session_state['PENDING_NOTIFY'] = None

# ==========================================================
# 📊 状态机对接层：将原 UI 流程彻底封装，让 FSM 掌控全局
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
    
    future_memory = st.session_state['ASYNC_EXECUTOR'].submit(hybrid_retriever.retrieve_and_rerank, query)
    future_web = st.session_state['ASYNC_EXECUTOR'].submit(web_search_pro, clean_keyword)
    future_crawler = st.session_state['ASYNC_EXECUTOR'].submit(crawl_smzdm_price, clean_keyword)
    
    long_term_context = future_memory.result()
    raw_info_blocks, raw_info_text, price_table_data = future_web.result()
    crawler_results = future_crawler.result()
    
    if crawler_results:
        crawler_text = "\n".join([item["price_info"] for item in crawler_results])
        raw_info_text = f"【精细化社区实时爆料行情】:\n{crawler_text}\n\n" + raw_info_text
        
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
    st.subheader("Recent history")
    for row in st.session_state.get('HISTORY_SESSIONS', [])[:8]:
        label = f"{row.get('created_at', '')} - {row.get('query', '')[:18]}"
        with st.expander(label, expanded=False):
            if row.get("item_name"):
                st.caption(f"Item: {row.get('item_name')} / Amount: {row.get('amount') or '-'}")
            st.write(row.get("assistant_reply") or "No reply summary")
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

    parsed_intent = classify_user_intent(query)
    if parsed_intent.intent in ("HELP_OR_META", "SMALLTALK_OR_OTHER", "INVALID"):
        reply_text = parsed_intent.reply or "我主要负责消费审计、价格查询和记账。你可以说：我想买某个商品，帮我看看值不值。"
        save_chat_history(query, parsed_intent.intent, assistant_reply=reply_text)
        st.session_state['HISTORY_SESSIONS'] = load_recent_chat_history(20)
        with st.chat_message("assistant"):
            st.markdown(reply_text)
        st.stop()

    if parsed_intent.intent == "DIRECT_EXPENSE":
        reply_text, _ = record_direct_expense(parsed_intent.item_name, parsed_intent.amount, query)
        st.session_state['HISTORY_SESSIONS'] = load_recent_chat_history(20)
        with st.chat_message("assistant"):
            st.success(reply_text)
        st.stop()

    with st.chat_message("assistant"):
        with st.status("🛸 Jerry-Scout 正在通过 FSM 状态机进行多维调度...", expanded=True) as status:
            raw_answer, clean_keyword, info_blocks, price_table_data, crawler_results = run_fsm_scout_pipeline(query, status)
            
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
                            try: valid_json_str = price_table_data.replace("'", '"'); parsed_data = json.loads(valid_json_str)
                            except: parsed_data = eval(price_table_data)
                        else: parsed_data = price_table_data
                    except: pass

                if crawler_results and isinstance(parsed_data, list):
                    for spider_item in crawler_results:
                        parsed_data.insert(0, {
                            "平台": f"🔥 {spider_item['platform']} (定向爆破)",
                            "参考报价/情报说明": spider_item['price_info'],
                            "数据出处": spider_item['source']
                        })

                if isinstance(parsed_data, list) and len(parsed_data) > 0:
                    df = pd.DataFrame(parsed_data)
                    column_mapping = {"平台": "🛒 渠道平台", "参考报价/情报说明": "💰 实时报价与情报", "数据出处": "🔗 原始链接"}
                    df = df.rename(columns=column_mapping)
                    st.dataframe(df, use_container_width=True, hide_index=True)

            detected_price = None
            display_answer = raw_answer
            if "PRICE_DATA:" in raw_answer:
                try:
                    parts = raw_answer.split("PRICE_DATA:")
                    display_answer = parts[0]
                    parsed_price_data = json.loads(parts[1].strip())
                    detected_price = float(parsed_price_data["estimated_price"])
                except: pass
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
                save_chat_history(
                    query,
                    "SHOPPING_QUERY",
                    assistant_reply=display_answer,
                    item_name=clean_keyword,
                    amount=detected_price,
                    audit_data={"price": detected_price, "item": clean_keyword, "display_answer": display_answer},
                )
                st.session_state['HISTORY_SESSIONS'] = load_recent_chat_history(20)
            except: pass

# ==========================================================
# 资产闭环记账阶段 (MCP 记账联动)
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
                f"### 🛡️ 铁算盘·消费审计报告 (资产扣减)\\n"
                f"- **买入明细**：`{audit_item}`\\n"
                f"- **消费扣减**：`- {audit_price} 元`\\n\\n"
                f"---\\n\\n"
                f"### ⚠️ 实时大盘风险控制报告\\n"
                f"- **当前本月剩余流动资金**：**{current_profile['current_surplus']} 元**\\n"
                f"- **风控提示**：系统已强制对齐月度资产预算规划！"
            )
        }
        
        try:
            memory_collection.add(documents=[f"Jerry最终确认购买了关于'{audit_item}'的商品。最终状态：[已买入]"], ids=[f"corr_{os.urandom(4).hex()}"])
        except: pass
            
        st.session_state['LAST_AUDIT'] = None
        st.rerun()
