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

# 🛠️ 工业级重排、记忆、路由、协议组件全线导入
from core.intent_router import TwoStageIntentRouter
from core.memory_manager import AdvancedMemoryManager
from core.hybrid_retriever import JaccardHybridRetriever
from tools.mcp_server import JerryMcpServer

from core.router import clean_query_to_entity 
from core.brain import ask_llm
from tools.search import web_search_pro
from data.sql_db import save_audit_log
from dotenv import load_dotenv

try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): return "未检测到 notify 微信零件"
    def push_dingtalk(content, title=None): return "未检测到 notify 钉钉零件"

load_dotenv()
st.set_page_config(page_title="Jerry-Insight Pro v3.5", layout="wide", page_icon="🛡️")

# 🔒 初始化全局互斥锁与文件
FILE_LOCK = threading.Lock()
PROFILE_FILE = "jerry_profile.json"

# 【优化核心】：全局常驻线程池，只在单例中初始化一次，全剧复用
if 'ASYNC_EXECUTOR' not in st.session_state:
    st.session_state['ASYNC_EXECUTOR'] = ThreadPoolExecutor(max_workers=8) # 扩大核心线程数

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
                    "Jerry专属无人机航拍偏好规则：当前每月生活费2000元. 消费心理：关注飞行安全风险与续han能力（炸机成本太高，无法承受），偏好傻瓜式的一键直出大片体验。",
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
if 'HARNESS_TRACE' not in st.session_state: st.session_state['HARNESS_TRACE'] = []

# 用于保存待发送的异步通知队列，防止 Rerun 杀线
if 'PENDING_NOTIFY' not in st.session_state: st.session_state['PENDING_NOTIFY'] = None

def log_harness_trace(step, node_type, action, details):
    st.session_state['HARNESS_TRACE'].append({
        "timestamp": time.strftime("%H:%M:%S", time.localtime()),
        "step": step, "node_type": node_type, "action": action, "details": details
    })

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
            "1. {\"action\": \"Call_Web_Search\", \"action_input\": \"关键词\"}\n"
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
                    raw_output = re.search(r'```json\s*({.*?})\s*```', raw_output, re.DOTALL).group(1)
                parsed_json = json.loads(raw_output)
                action = parsed_json.get("action")
                action_input = parsed_json.get("action_input")

                if action == "Final Answer": return action_input
                elif action == "Call_Web_Search":
                    _, search_feedback_text, _ = web_search_pro(action_input)
                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({"role": "user", "content": f"【追查情报】：\n{search_feedback_text[:1200]}"})
            except:
                if step >= self.max_steps - 1:
                    return "⚠️ 【铁算盘兜底】格式异常收敛。\nPRICE_DATA: {\"item\": \"" + item_name + "\", \"estimated_price\": 100.0}"
        return "⚠️ 【Harness超时熔断】\nPRICE_DATA: {\"item\": \"" + item_name + "\", \"estimated_price\": 50.0}"

def async_push_notification(content, title=None):
    try:
        push_wechat(content)
        push_dingtalk(content, title=title)
    except Exception as e:
        print(f"后台静默发送失败: {e}")

# ==========================================================
# ⚡ 【消灭卡顿核心逻辑】：在脚本最开头检查并消费通知队列
# ==========================================================
if st.session_state['PENDING_NOTIFY']:
    task = st.session_state['PENDING_NOTIFY']
    # 彻底与 Rerun 脱离关系：在全新的干净生命周期里丢进后台，秒级完成
    st.session_state['ASYNC_EXECUTOR'].submit(async_push_notification, task["content"], task["title"])
    st.session_state['PENDING_NOTIFY'] = None # 消费完毕，立刻清空

# ==========================================================
# UI 侧边栏与大盘渲染
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

st.title("🛡️ Jerry-Insight Pro v3.5")
dynamic_profile = get_dynamic_profile()
st.markdown(f"""> 💳 **Jerry 的当前实时资产面板** ｜ 本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]""")

query = st.chat_input("输入商品名称...")

if query and query.strip():
    with st.chat_message("user"): st.write(query)

    with st.chat_message("assistant"):
        router = TwoStageIntentRouter(api_key=api_key)
        intent, confidence = router.route(query)
        
        if intent == "INVALID":
            st.error("🚨 监测到非业务输入/无效安全隐患。")
        else:
            with st.status("🛸 Jerry-Scout 正在并行调度多维情报...", expanded=True) as status:
                clean_keyword = clean_query_to_entity(query)
                
                # 【优化点】：改用全局常驻线程池复用提交，杜绝局部开关线程池产生的卡顿
                future_memory = st.session_state['ASYNC_EXECUTOR'].submit(hybrid_retriever.retrieve_and_rerank, query)
                future_web = st.session_state['ASYNC_EXECUTOR'].submit(web_search_pro, clean_keyword)
                
                long_term_context = future_memory.result()
                raw_info_blocks, raw_info_text, price_table_data = future_web.result()

                info_blocks = native_diversity_rerank(raw_info_blocks)
                
                st.session_state['GLOBAL_MEMORY_MANAGER'].add_message("user", query)
                memory_ctx = st.session_state['GLOBAL_MEMORY_MANAGER'].get_compiled_context()
                
                harness_engine = JerryAgentHarness()
                raw_answer = harness_engine.run_harness(clean_keyword, raw_info_text, dynamic_profile, long_term_context, memory_ctx, status_widget=status)
                status.update(label="🚀 情报与 Harness 状态机闭包运行完毕！", state="complete", expanded=False)

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
            
            # 报告生成的初始通知静默丢入全局线程池
            short_conclusion = "建议避坑" if "建议避坑" in display_answer else ("建议购买" if "建议购买" in display_answer else "持币观望")
            push_brief = f"### 🕵️ 铁算盘·消费审计报告\n- **商品目标**：{clean_keyword}\n- **审计结论**：**{short_conclusion}**\n- **预估金额**：{detected_price} 元"
            st.session_state['ASYNC_EXECUTOR'].submit(async_push_notification, push_brief, "🕵️ 消费审计报告")

            try:
                memory_collection.add(documents=[f"Jerry曾咨询过关于'{clean_keyword}'的购买决策。结论是：[{short_conclusion}]"], metadatas=[{"source": "chat_log"}], ids=[f"mem_{os.urandom(4).hex()}"])
                save_audit_log(query, display_answer[:50])
            except: pass

if st.session_state['LAST_AUDIT']:
    st.write("---")
    audit_item = st.session_state['LAST_AUDIT']["item"]
    audit_price = st.session_state['LAST_AUDIT']["price"]
    
    if st.button(f" 确认记入账本 (扣减 {audit_price}元)", type="primary"):
        # 1. 第一步：本地有互斥锁的 JSON 文件读写，耗时极其微弱（几微秒），直接安全处理
        rpc_payload = json.dumps({
            "jsonrpc": "2.0", "method": "tools/call",
            "params": {"name": "record_expense", "arguments": {"amount": audit_price, "item_name": audit_item}},
            "id": 1
        })
        mcp_gateway.handle_json_rpc(rpc_payload)
        
        # 2. 第二步：重新读取更新后的资产画像，用于组装通知
        current_profile = get_dynamic_profile()
        
        # 3. 第三步【防卡顿精髓】：把高延迟的群发通知打包挂载到暂存区，【绝不在 Rerun 之前发送】！
        st.session_state['PENDING_NOTIFY'] = {
            "title": "⚠️ 资产账户变动联合报告",
            "content": (
                f"### 🛡️ 铁算盘·消费审计报告 (资产扣减)\n" # 对齐你的钉钉安全关键词：“审计”、“报告”
                f"- **买入明细**：`{audit_item}`\n"
                f"- **消费扣减**：`- {audit_price} 元`\n\n"
                f"---\n\n"
                f"### ⚠️ 实时大盘风险控制报告\n"
                f"- **当前本月剩余流动资金**：**{current_profile['current_surplus']} 元**\n"
                f"- **风控提示**：系统已强制对齐月度资产预算规划！"
            )
        }
        
        # 4. 第四步：写入 ChromaDB 长期记忆
        try:
            memory_collection.add(documents=[f"Jerry最终确认购买了关于'{audit_item}'的商品。最终状态：[已买入]"], ids=[f"corr_{os.urandom(4).hex()}"])
        except: pass
            
        # 5. 第五步：立刻斩断当前生命周期，按钮瞬间弹回成功状态！
        st.session_state['LAST_AUDIT'] = None
        st.rerun() # 触发页面刷新，通知会在下一个周期的最开头被常驻线程池无感消费，彻底消灭 UI 卡死！