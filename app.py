import os
import time
import json
import re
import threading  # 🛠️ 缺陷1修复：引入线程包实现高并发文件锁
import chromadb
import numpy as np
import pandas as pd
import streamlit as st
from openai import OpenAI  # 使用 OpenAI 库兼容调用 DeepSeek
from concurrent.futures import ThreadPoolExecutor
from core.router import classify_intent, clean_query_to_entity
from core.brain import ask_llm
from tools.search import web_search_pro
from data.sql_db import save_audit_log
from dotenv import load_dotenv

# 🚀 引入经过防代理污染、带自清洗功能的通知零件
try:
    from tools.notify import push_wechat, push_dingtalk
except ImportError:
    def push_wechat(content): return "未检测到 notify 微信零件"
    def push_dingtalk(content, title=None): return "未检测到 notify 钉钉零件"

# 加载本地环境
load_dotenv()

st.set_page_config(page_title="Jerry-Insight Pro v3.5", layout="wide", page_icon="🛡️")

# 🔒 缺陷1修复：初始化一个全局互斥锁，确保多线程下修改账单文件绝对安全，不漏扣/多扣一分钱
FILE_LOCK = threading.Lock()

# ==========================================================
# 1. 长期向量库初始化并自动灌入静态画像
# ==========================================================
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
                metadatas=[
                    {"category": "profile_rule", "tag": "耳机"},
                    {"category": "profile_rule", "tag": "相机"},
                    {"category": "profile_rule", "tag": "无人机"},
                    {"category": "profile_rule", "tag": "通用"}
                ],
                ids=["rule_earphone", "rule_camera", "rule_drone", "rule_general"]
            )
    except Exception as e:
        print(f"画像基底向量初始化提示: {e}")
        
    return collection

memory_collection = init_chroma_and_inject_profiles()

# ==========================================================
# 2. 动态账单配置与实时写入更新引擎（引入并发文件锁）
# ==========================================================
PROFILE_FILE = "jerry_profile.json"

def get_dynamic_profile():
    # 读操作同样上锁，防止读写冲突引发的 JSONDecodeError
    with FILE_LOCK:
        if not os.path.exists(PROFILE_FILE):
            default_profile = {
                "user_name": "Jerry",
                "monthly_budget": 2000.0,
                "current_surplus": 850.0,  
                "fixed_expenses": {"饮食": 1200, "话费交通": 300},
                "recent_purchases": ["维他柠檬茶", "蓝牙耳机"]
            }
            with open(PROFILE_FILE, "w", encoding="utf-8") as f:
                json.dump(default_profile, f, ensure_ascii=False, indent=4)
            return default_profile
        
        with open(PROFILE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)

def update_profile_balance(amount, item_name):
    # 🛠️ 缺陷1修复：写操作强制拉满文件互斥锁，确保并发记账时原子性，杜绝多线程竞态条件
    with FILE_LOCK:
        if os.path.exists(PROFILE_FILE):
            with open(PROFILE_FILE, "r", encoding="utf-8") as f:
                profile = json.load(f)
        else:
            profile = {
                "user_name": "Jerry",
                "monthly_budget": 2000.0,
                "current_surplus": 850.0,
                "fixed_expenses": {"饮食": 1200, "话费交通": 300},
                "recent_purchases": []
            }
        
        profile["current_surplus"] = round(profile["current_surplus"] - amount, 2)
        if item_name not in profile["recent_purchases"]:
            profile["recent_purchases"].append(item_name)
            
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=4)

# ==========================================
# 3. 短期记忆管理 (Session State)
# ==========================================
if 'SHORT_TERM_MEMORY' not in st.session_state:
    st.session_state['SHORT_TERM_MEMORY'] = []
if 'LAST_AUDIT' not in st.session_state:
    st.session_state['LAST_AUDIT'] = None
# 🛠️ 缺陷2辅助：开辟独立的可观测性 Trace 状态机执行树看板缓存
if 'HARNESS_TRACE' not in st.session_state:
    st.session_state['HARNESS_TRACE'] = []

def update_short_term_memory(user_input, agent_output):
    st.session_state['SHORT_TERM_MEMORY'].append({"role": "user", "content": user_input})
    st.session_state['SHORT_TERM_MEMORY'].append({"role": "assistant", "content": agent_output})
    if len(st.session_state['SHORT_TERM_MEMORY']) > 6:
        st.session_state['SHORT_TERM_MEMORY'] = st.session_state['SHORT_TERM_MEMORY'][-6:]

def log_harness_trace(step, node_type, action, details):
    """🛠️ 缺陷2辅助：结构化追加一条状态机追踪链快照"""
    st.session_state['HARNESS_TRACE'].append({
        "timestamp": time.strftime("%H:%M:%S", time.localtime()),
        "step": step,
        "node_type": node_type, # THINK | ACT | OBSERVE | FALLBACK
        "action": action,
        "details": details
    })

# ==========================================================
# 4. 真实重排算法：对原始文本去重清洗 (Matrix Reranker)
# ==========================================================
def native_diversity_rerank(info_blocks):
    if not info_blocks:
        return []
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
        if not is_duplicate:
            unique_blocks.append(current)
    return unique_blocks[:4]

# ==========================================================
# 🧠 5. 大厂硬核完全体：自研 Harness 有限状态机引擎 (全面覆盖可观测Trace)
# ==========================================================
class JerryAgentHarness:
    def __init__(self, max_steps=4):
        api_key = os.getenv("DEEPSEEK_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            st.error("🚨 错误：系统未检测到 DeepSeek API Key，请检查环境变量。")
            st.stop()

        self.client = OpenAI(
            api_key=api_key,
            base_url="https://api.deepseek.com"
        )
        self.model = "deepseek-chat" 
        self.max_steps = max_steps

    def _compress_memory(self, history, step):
        """🎯 自动化窗口压缩摘要机制 + 注入 Trace"""
        st.write("🧹 _[Harness 监控]_ 正在执行上下文窗口滑窗压缩...")
        log_harness_trace(step, "OBSERVE", "Memory Condense", "由于会话历史达到临界值，自动调用大模型执行流式脱水压缩...")
        
        compress_prompt = f"请将以下对话历史中，关于用户的‘核心财务状况’、‘购买过的商品’或‘雷点偏好’压缩成一段100字以内的摘要，不要丢失核心关键信息。历史内容：\n{json.dumps(history[1:-1], ensure_ascii=False)}"
        try:
            res = self.client.chat.completions.create(
                model=self.model,
                messages=[{"role": "user", "content": compress_prompt}],
                temperature=0.3
            )
            summary = res.choices[0].message.content.strip()
            log_harness_trace(step, "ACT", "Memory Condense End", f"压缩成功！生成摘要摘要头: {summary[:30]}...")
            
            compressed_history = [
                history[0],
                {"role": "system", "content": f"【前序对话核心记忆摘要】：{summary}"},
                history[-1]
            ]
            return compressed_history
        except Exception as e:
            log_harness_trace(step, "FALLBACK", "Memory Condense Fail", f"压缩执行失败，使用硬截断切片挂起: {str(e)}")
            return history[:2] + history[-2:]

    def run_harness(self, item_name, raw_info_text, profile_data, long_term_context):
        """🎯 【真实工具调度闭环机制】+【三层健壮降级容错】"""
        system_instruction = (
            "你是 Jerry-Insight 系统的【首席风控审计官】，代号“铁算盘”。\n"
            "我们要审计的商品是：【" + item_name + "】。\n\n"
            "你必须严格遵循以下【状态机运转协议】控制分析闭环，输出标准 JSON 块：\n"
            "1. 【状态：继续补充网络情报】—— 如果你认为当前网络情报不足或需要深度搜索，输出：\n"
            "   {\"action\": \"Call_Web_Search\", \"action_input\": \"需要进一步搜索补充的商品关键词\"}\n"
            "2. 【状态：输出最终审计】—— 如果你认为证据充足，必须输出：\n"
            "   {\"action\": \"Final Answer\", \"action_input\": \"你的深度风控审计报告文本...\\n\\nPRICE_DATA: {\\\"item\\\": \\\"" + item_name + "\\\", \\\"estimated_price\\\": 预估单价浮点数}\"}\n\n"
            "【报告文本硬性标准】:\n"
            "- 必须检查历史档案是否含有 Jerry 的同类商品避坑规则。\n"
            "- 结论必须明确包含 [建议购买]、[持币观望] 或 [建议避坑] 之一。\n"
            "- Final Answer 的末尾必须严格包含：PRICE_DATA: {\"item\": \"...\", \"estimated_price\": ...}"
        )

        user_input_context = (
            f"【ChromaDB 向量库检索出的历史档案】：\n{long_term_context}\n\n"
            f"【Jerry 实时财务画像】：\n- 剩余流动资金: {profile_data['current_surplus']} 元\n\n"
            f"【第一轮抓取到的初始情报】：\n{raw_info_text[:1000]}"
        )

        conversation_history = [
            {"role": "system", "content": system_instruction},
            {"role": "user", "content": user_input_context}
        ]

        st.session_state['HARNESS_TRACE'] = [] # 初始化 Trace 链路
        log_harness_trace(0, "THINK", "Harness Engine Boot", f"手写状态机初始化完毕。目标实体: 【{item_name}】，初始向量库文本已注入。")

        step = 0
        while step < self.max_steps:
            step += 1
            
            if len(conversation_history) >= 6:
                conversation_history = self._compress_memory(conversation_history, step)

            try:
                log_harness_trace(step, "THINK", "LLM Analysis Request", f"调用核心大脑 {self.model} 进行多维风控决策推理中...")
                response = self.client.chat.completions.create(
                    model=self.model, messages=conversation_history, temperature=0.3
                )
                raw_output = response.choices[0].message.content.strip()

                if "```json" in raw_output:
                    raw_output = re.search(r'```json\s*({.*?})\s*```', raw_output, re.DOTALL).group(1)

                parsed_json = json.loads(raw_output)
                action = parsed_json.get("action")
                action_input = parsed_json.get("action_input")

                # 【分支 A：进入最终答案状态】
                if action == "Final Answer":
                    log_harness_trace(step, "ACT", "Final Answer Resolved", f"状态机成功收尾！已抓取到 Final Answer 及规范记账价格块。")
                    return action_input

                # 【分支 B：触发动态自主工具调度】
                elif action == "Call_Web_Search":
                    st.write(f"🔍 _[Harness 状态机自我决策]_：发现初始数据不足，正在二轮追查关键词: `{action_input}`")
                    log_harness_trace(step, "ACT", "Call_Web_Search Triggered", f"大脑决策：发现原始情报不透彻，主动下发【外挂搜索零件】追查关键词: `{action_input}`")
                    
                    try:
                        _, search_feedback_text, _ = web_search_pro(action_input)
                        log_harness_trace(step, "OBSERVE", "Tool Response Received", f"搜索零件二轮追查成功，获取到长度为 {len(search_feedback_text)} 的非结构化文本，成功逆向喂回大模型上下文。")
                    except Exception as err:
                        search_feedback_text = f"二轮补充工具调用失败，原因为: {str(err)}"
                        log_harness_trace(step, "FALLBACK", "Tool Invocation Error", f"外挂工具执行遭遇阻碍: {str(err)}")

                    conversation_history.append({"role": "assistant", "content": raw_output})
                    conversation_history.append({
                        "role": "user", 
                        "content": f"【系统反馈二轮追查情报】：\n{search_feedback_text[:1500]}\n请结合补充情报，立刻进行收尾，并输出最终的 Final Answer 状态。"
                    })

                else:
                    raise ValueError(f"不合规的 Action 状态指令: {action}")

            except (json.JSONDecodeError, ValueError, Exception) as e:
                st.write(f"⚠️ _[Harness 健壮性防崩溃提示]_：检测到格式异常（{str(e)[:30]}...），触发实时自愈纠偏...")
                log_harness_trace(step, "FALLBACK", "Format Exception Intercepted", f"由于大模型输出不合规或JSON断裂引发异常: {str(e)}。系统启动自愈拦截机制。")
                
                if step < self.max_steps - 1:
                    conversation_history.append({
                        "role": "user", 
                        "content": f"【格式纠偏警告】：你刚刚输出的内容未能通过系统的验证，或者并非标准JSON。请务必输出满足规范的 JSON 块，或者直接进行 Final Answer 状态收尾。"
                    })
                else:
                    st.write("💥 _[Harness 极限降级防护]_：模型持续状态异常，启动极致文本级 Fallback 降级机制。")
                    log_harness_trace(step, "FALLBACK", "Critical Fallback Executed", "格式死锁或思考轮次用尽，强行启动文本级底层安全防护链兜底生成...")
                    try:
                        fallback_res = self.client.chat.completions.create(
                            model=self.model,
                            messages=[
                                {"role": "system", "content": "请针对商品给出一份通俗的纯文本审计回复，末尾单独一行打印 PRICE_DATA: {\"item\": \"商品\", \"estimated_price\": 50.0}"},
                                {"role": "user", "content": f"对【{item_name}】做个快速评判。"}
                            ]
                        )
                        return fallback_res.choices[0].message.content
                    except:
                        msg = "⚠️ 【铁算盘安全熔断】状态机系统由于多次格式跑偏且降级链断裂。为保 Jerry 资产安全，强制拦截购买！\n"
                        msg += f'PRICE_DATA: {{"item": "{item_name}", "estimated_price": 100.0}}'
                        return msg

        msg_timeout = f'⚠️ 【Harness执行超时】铁算盘进入死循环保护性熔断。\nPRICE_DATA: {{"item": "{item_name}", "estimated_price": 50.0}}'
        log_harness_trace(step, "FALLBACK", "Harness Timeout Triggered", "状态流转超时断开，强制启动硬安全阈值进行熔断拦截。")
        return msg_timeout

# ==========================================================
# 6. 侧边栏：排雷红黑榜可视化与 Trace 控制中心 (智能状态纠偏版)
# ==========================================================
with st.sidebar:
    st.header("🕵️ Jerry-Insight 调度中心")
    st.info("当前引擎：DeepSeek-R1 + Tavily")
    st.caption("核心升级：多渠道双路强推、全网实时比价、红绿榜动态状态纠偏")
    
    st.write("---")
    st.subheader("📊 铁算盘·资产风控中心")
    
    try:
        all_mems = memory_collection.get()
        item_status_map = {}
        
        if all_mems and all_mems['documents']:
            for doc in all_mems['documents']:
                part = None
                status_type = None
                
                if "强行确认购买了关于'" in doc:
                    part = doc.split("强行确认购买了关于'")[1].split("'的商品")[0]
                    status_type = "WHITELIST"
                elif "关于'" in doc:
                    part = doc.split("关于'")[1].split("'的购买决策")[0]
                    if "建议避坑" in doc:
                        status_type = "BLACKLIST"
                    elif "建议购买" in doc or "放放" in doc or "放行" in doc:
                        status_type = "WHITELIST"
                
                if part:
                    clean_part = part.strip().replace("'", "").replace('"', "")
                    if item_status_map.get(clean_part) == "WHITELIST" and status_type == "BLACKLIST":
                        continue
                    item_status_map[clean_part] = status_type
        
        blacklist = [k for k, v in item_status_map.items() if v == "BLACKLIST"]
        whitelist = [k for k, v in item_status_map.items() if v == "WHITELIST"]
        
        with st.expander("🔴 查看被强制拦截的坑位", expanded=True):
            if blacklist:
                for item in blacklist[-5:]:
                    st.markdown(f"❌ `{item}`")
            else:
                st.caption("暂无历史拦截记录")
                
        with st.expander("🟢 查看已安全放行的好物", expanded=True):
            if whitelist:
                for item in whitelist[-5:]:
                    st.markdown(f"✅ `{item}`")
            else:
                st.caption("暂无历史放行记录")
    except Exception as e:
        st.caption("历史红黑快照数据解析中...")

    st.write("---")
    st.subheader("🧠 调试级数据底层追踪")
    with st.expander("⏱️ 短期会话记忆 (滑动窗口)", expanded=False):
        if st.session_state['SHORT_TERM_MEMORY']:
            for turn in st.session_state['SHORT_TERM_MEMORY']:
                role_label = "Jerry" if turn['role'] == "user" else "铁算盘"
                st.caption(f"**{role_label}**: {turn['content'][:30]}...")
        else:
            st.caption("暂无短期会话缓存")
            
    with st.expander("💾 长期向量库原始快照 (ChromaDB)", expanded=False):
        try:
            db_data = memory_collection.peek(limit=3)
            if db_data and db_data['documents']:
                for doc in db_data['documents']: st.caption(f"📌 {doc[:40]}...")
        except:
            st.caption("长期记忆读取中...")
            
    st.write("---")
    st.subheader("⚙️ 数据重置控制台")
    
    if st.button("🧹 清空当前聊天会话", width="stretch"):
        st.session_state['SHORT_TERM_MEMORY'] = []
        st.session_state['HARNESS_TRACE'] = []
        st.session_state['LAST_AUDIT'] = None
        st.success("短期临时缓存已切断！")
        time.sleep(0.5)
        st.rerun()
        
    if st.button("🚨 强行清空长期记忆银行", type="secondary", width="stretch"):
        try:
            chroma_client = chromadb.PersistentClient(path="./memory_bank")
            try:
                chroma_client.delete_collection(name="jerry_history")
            except:
                pass
            st.cache_resource.clear() 
            init_chroma_and_inject_profiles()
            st.session_state['LAST_AUDIT'] = None
            st.session_state['HARNESS_TRACE'] = []
            st.success("💥 长期数据库已初始化，陈年老账已完全抹除！")
            time.sleep(1)
            st.rerun()
        except Exception as e:
            st.error(f"清空失败，原因: {e}")

# ==========================================
# 7. 核心业务处理链路
# ==========================================
st.title("🛡️ Jerry-Insight Pro v3.5")
st.markdown("##### 工业级消费排雷 Agent（手写 Harness 状态机引擎版）")

# 获取并展示钱包数据（已内部挂锁）
dynamic_profile = get_dynamic_profile()
st.markdown(f"""
> 💳 **Jerry 的当前实时资产面板** ｜ 
> 月总预算: `{dynamic_profile['monthly_budget']} 元` ｜ 
> **本月卡里剩余流动资金: :orange[{dynamic_profile['current_surplus']} 元]** ｜ 
> 近期记账清单: `{', '.join(dynamic_profile['recent_purchases'][-4:])}`
""")

query = st.chat_input("输入商品名称，开启 360 度多维排雷审计...")

if query:
    if not query.strip():
        st.warning("⚠️ 请输入有效的商品名称后再开启审计。")
    else:
        with st.chat_message("user"):
            st.write(query)

        with st.chat_message("assistant"):
            intent = classify_intent(query)
            if intent == "INVALID":
                st.error("🚨 监测到非业务输入，系统已自动拦截。")
            else:
                with st.status("🛸 Jerry-Scout 正在并行调度多维情报...", expanded=True) as status:
                    st.write("🎯 意图识别：消费决策审计任务")
                    
                    with st.expander("🛠️ 查看系统执行元数据 (Backend Metrics)", expanded=False):
                        st.code(f"""
[RUNTIME] Logic-Chain: Router -> Context消解 -> Hybrid Vector Search -> Custom Agent Harness (DeepSeek) -> Matrix Rerank -> Dual Enforced Notify
[DATABASE] Storage: SQLite3 & ChromaDB Hybrid Engine (Active)
[SECURITY] Thread-Safe Mutex Lock (Active) & Harness Trace Engine v2.0
                        """, language="yaml")
                    
                    refined_query = query
                    if len(st.session_state['SHORT_TERM_MEMORY']) > 0:
                        rewrite_prompt = f"""
                        你是一个意图解析器。请结合之前的对话历史，判断用户当前输入的词是否有指代不明。如果有，请将其补全为具体的商品名词。
                        【对话历史】: {json.dumps(st.session_state['SHORT_TERM_MEMORY'], ensure_ascii=False)}
                        【当前输入】: "{query}"
                        请直接输出补全后的干净商品名：
                        """
                        try:
                            rewrite_res = ask_llm([{"role": "user", "content": rewrite_prompt}])
                            if rewrite_res: refined_query = rewrite_res.strip().replace('"', '')
                        except: refined_query = query
                    
                    clean_keyword = clean_query_to_entity(refined_query)

                    st.write("⚡ 正在并行启动：ChromaDB检索 & 全网去重抓取 & 电商价格比对...")
                    def fetch_long_term_memory(q):
                        try:
                            db_res = memory_collection.query(query_texts=[q], n_results=3)
                            if db_res and db_res['documents'] and db_res['documents'][0]: return "\n".join(db_res['documents'][0])
                        except: pass
                        return ""

                    def fetch_web_data(k): return web_search_pro(k)

                    with ThreadPoolExecutor(max_workers=2) as executor:
                        future_memory = executor.submit(fetch_long_term_memory, refined_query)
                        future_web = executor.submit(fetch_web_data, clean_keyword)
                        long_term_context = future_memory.result()
                        raw_info_blocks, raw_info_text, price_table_data = future_web.result()

                    # 矩阵 Jaccard 去重与清洗
                    info_blocks = native_diversity_rerank(raw_info_blocks)
                    
                    st.write("🧠 🎛️ 正在做最终财务核算与对齐生成...")
                    
                    # 🔥 触发自研完全体状态机！
                    harness_engine = JerryAgentHarness()
                    raw_answer = harness_engine.run_harness(
                        clean_keyword, raw_info_text, dynamic_profile, long_term_context
                    )
                    status.update(label="🚀 并行全网去重情报与 Harness 状态机拓扑加速链闭包运行完毕！", state="complete", expanded=False)
                
                if refined_query != query:
                    st.info(f"💡 记忆消解对齐：检测到上下文指代，‘铁算盘’已自动把模糊词翻译为真实目标：【{refined_query}】进行精确审计")

                detected_price = None
                if price_table_data:
                    try:
                        detected_price = float(price_table_data[0]["实时全网价格"].replace("元", "").strip())
                    except:
                        pass
                
                display_answer = raw_answer
                if "PRICE_DATA:" in raw_answer:
                    try:
                        parts = raw_answer.split("PRICE_DATA:")
                        display_answer = parts[0]
                        json_str = parts[1].strip()
                        parsed_price_data = json.loads(json_str)
                        if detected_price is None:
                            detected_price = float(parsed_price_data["estimated_price"])
                    except:
                        pass
                
                if detected_price is None:
                    detected_price = 3.0 if "可乐" in clean_keyword else 50.0

                # 1. 全网实时 price 监控看板
                st.markdown("### 💰 全网实时价格监控看板")
                if price_table_data:
                    df = pd.DataFrame(price_table_data)
                    st.dataframe(df, use_container_width=True, hide_index=True)
                else:
                    st.warning("⚠️ 监测到当前全网独立情报源遭受非相关数据污染，已自动启动本地智能估价机制。")

                # 2. 4 个过滤重排后的独立情报源展示
                if info_blocks:
                    with st.expander("🌐 实时全网去重情报源快照 (Rerank Filtered x4)", expanded=False):
                        for idx, (p_text, url, score) in enumerate(info_blocks):
                            st.markdown(f"> **独立情报通道 {idx+1}** (语义去重得分: `{score:.2f}`)\n> “{p_text}”\n> 🔗 *独立情报来源:* [{url}]({url})\n---")

                # 3. 正式审计报告展示
                st.markdown("### 🛡️ Jerry-Insight 深度审计报告")
                st.markdown(display_answer)
                
                # 🛠️ 缺陷2修复：前端流式可视化 Trace 链路追踪调用树组件渲染
                if st.session_state['HARNESS_TRACE']:
                    st.write("---")
                    with st.expander("📊 🔍 展开查看‘铁算盘’核心状态机全链路思考树 (Trace Timeline Insight)", expanded=False):
                        st.caption("系统自动追踪捕获：当前对话已被 LLM 可观测性探针截获，以下展示状态机内部流转真实现状：")
                        for node in st.session_state['HARNESS_TRACE']:
                            color_map = {"THINK": ":blue[🧠 THINK]", "ACT": ":green[⚡ ACT]", "OBSERVE": ":orange[👁️ OBSERVE]", "FALLBACK": ":red[🚨 FALLBACK]"}
                            node_tag = color_map.get(node["node_type"], node["node_type"])
                            st.markdown(f"""
                            **[{node['timestamp']}]** ｜ 思考步数: `Step {node['step']}` ｜ 内部拓扑状态: {node_tag}
                            * **动作意图**: `{node['action']}`
                            * **细节跟踪**: *{node['details']}*
                            ---
                            """)
                
                st.session_state['LAST_AUDIT'] = {"price": detected_price, "item": clean_keyword}
                
                # --- 🔗 触发点 A：【微信 + 钉钉】独立双路清洗强推 ---
                try:
                    short_conclusion = "建议避坑" if "建议避坑" in display_answer else ("建议购买" if "建议购买" in display_answer else "持币观望")
                    push_brief = f"### 🕵️ Jerry-Insight 报告出炉\n- **商品目标**：{clean_keyword}\n- **铁算盘结论**：**{short_conclusion}**\n- **预估涉及金额**：{detected_price} 元\n- **当前流动资金**：{dynamic_profile['current_surplus']} 元\n\n> 报告概要已录入本地。Jerry 冲动消费前请务必三思！"
                    
                    try: push_wechat(push_brief)
                    except Exception as we_err: print(f"微信通知延迟: {we_err}")
                    
                    try: push_dingtalk(push_brief, title="🕵️ 铁算盘 · 消费审计报告")
                    except Exception as dt_err: print(f"钉钉通知延迟: {dt_err}")
                        
                except Exception as total_err:
                    print(f"审计消息分发失败: {total_err}")
                
                try:
                    memory_id = f"mem_{os.urandom(4).hex()}"
                    memory_collection.add(
                        documents=[f"Jerry曾咨询过关于'{clean_keyword}'的购买决策。当时的审计最终结论是：[{short_conclusion}]"],
                        metadatas=[{"source": "chat_log", "query": clean_keyword}],
                        ids=[memory_id]
                    )
                    update_short_term_memory(query, display_answer)
                    save_audit_log(query, display_answer[:50] + "...")
                except: pass

# ==========================================================
# 8. 资产负债联动闭环：渲染动态记账购买按钮
# ==========================================================
if st.session_state['LAST_AUDIT']:
    st.write("---")
    st.markdown("##### 🛒 铁算盘·资产负债联动闭环")
    audit_item = st.session_state['LAST_AUDIT']["item"]
    audit_price = st.session_state['LAST_AUDIT']["price"]
    
    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        if st.button(f" 确认记入账本 (扣减 {audit_price}元)", type="primary"):
            # 内部已加锁锁死，多线程下安全扣减
            update_profile_balance(audit_price, audit_item)
            
            try:
                current_profile = get_dynamic_profile()
                st.success(f" 记账成功！已从流动资金中扣除 {audit_price} 元。")
                
                notify_bill_content = f"### ⚠️ Jerry-Insight 真实资产扣减通告\n- **确认买入**：`{audit_item}`\n- **本次扣除**：`{audit_price} 元`\n- **卡里实时剩余流动资金**：**{current_profile['current_surplus']} 元**\n\n> 铁算盘：账本已真实入库，并同步修正长期风控红绿榜。请确保下半月勒紧裤腰带！"
                
                try: push_wechat(notify_bill_content)
                except Exception as we_b_err: print(f"微信记账账单发送延迟: {we_b_err}")
                    
                try: push_dingtalk(notify_bill_content, title="⚠️ 资产真实扣减通告")
                except Exception as dt_b_err: print(f"钉钉群机器人记账账单发送延迟: {dt_b_err}")
                    
            except Exception as total_b_err:
                print(f"扣款账单分发失败: {total_b_err}")
                
            try:
                corr_id = f"corr_{os.urandom(4).hex()}"
                memory_collection.add(
                    documents=[f"Jerry最终决定无视风险，强行确认购买了关于'{audit_item}'的商品。最终状态：[放行记账/已买入]"],
                    metadatas=[{"source": "override_log", "query": audit_item}],
                    ids=[corr_id]
                )
            except: pass
                
            st.session_state['LAST_AUDIT'] = None
            st.session_state['HARNESS_TRACE'] = [] # 清理当前执行链 Trace
            time.sleep(1)
            st.rerun()
    with col_btn2:
        st.caption(f"点击该按钮将触发带有并发保护（Thread-Safe Mutex Lock）的资产记账处理，并自动更新系统底层的红黑快照。")