import os
import json
import chromadb
from openai import OpenAI
from dotenv import load_dotenv

# 确保在后端强行加载环境变量
load_dotenv()

# ==========================================
# 1. 初始化长期记忆银行（ChromaDB 向量库）
# ==========================================
def get_memory_collection():
    """ 独立初始化向量库 """
    chroma_client = chromadb.PersistentClient(path="./memory_bank")
    return chroma_client.get_or_create_collection(name="jerry_history")

# ==========================================
# 2. 模拟动态账单/结构化财务画像数据库
# ==========================================
PROFILE_FILE = "jerry_profile.json"

def get_dynamic_profile():
    if not os.path.exists(PROFILE_FILE):
        default_profile = {
            "user_name": "Jerry",
            "monthly_budget": 2000.0,
            "current_surplus": 850.0,  # 当月剩余可用资金
            "fixed_expenses": {"饮食": 1200, "话费交通": 300},
            "recent_purchases": ["维他柠檬茶", "蓝牙耳机"]
        }
        with open(PROFILE_FILE, "w", encoding="utf-8") as f:
            json.dump(default_profile, f, ensure_ascii=False, indent=4)
        return default_profile
    
    with open(PROFILE_FILE, "r", encoding="utf-8") as f:
        return json.load(f)

# ==========================================
# 3. 核心计算大脑：处理记忆与指代消解
# ==========================================
def process_jerry_memory_and_profile(raw_user_input, short_term_memory_list):
    """
    此函数只负责进行【短期指代消解】和【长期/动态画像数据组装】，
    完全不参与、也不干扰你的 Streamlit UI 渲染。
    """
    client = OpenAI(
        api_key=os.getenv("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1"
    )
    
    dynamic_profile = get_dynamic_profile()
    memory_collection = get_memory_collection()
    
    # ---- 1. 短期记忆指代消解 ----
    refined_query = raw_user_input
    if len(short_term_memory_list) > 0:
        rewrite_prompt = f"""
        你是一个意图解析器。请结合之前的对话历史，判断用户当前输入的词是否有指代不明（如“那个”、“它”、“刚说的那个”）。
        如果有，请将其补全为具体的商品名词。如果没有，请原样返回用户的输入。
        
        【对话历史】:
        {json.dumps(short_term_memory_list, ensure_ascii=False)}
        
        【当前输入】: "{raw_user_input}"
        
        请直接输出补全后的干净商品名或原始输入，不要夹带任何解释和标点符号：
        """
        try:
            rewrite_res = client.chat.completions.create(
                model="deepseek-chat",
                messages=[{"role": "user", "content": rewrite_prompt}],
                temperature=0.0
            )
            refined_query = rewrite_res.choices[0].message.content.strip().replace('"', '')
        except:
            refined_query = raw_user_input

    # ---- 2. 长期记忆检索 ----
    long_term_context = ""
    try:
        db_res = memory_collection.query(
            query_texts=[refined_query],
            n_results=2
        )
        if db_res and db_res['documents'] and db_res['documents'][0]:
            long_term_context = "\n".join(db_res['documents'][0])
    except Exception as e:
        print(f"长期记忆读取跳过: {e}")

    # ---- 3. 组装最终喂给 DeepSeek 的系统级 Prompt 上下文 ----
    injected_system_prompt = f"""
    你是一个冷酷、毒舌但绝对忠诚的消费审计 Agent，代号“铁算盘”。
    你的任务是死死卡住 Jerry 的钱包，根据他的实时财务画像和全网情报进行多维审计。
    
    【Jerry 的实时财务画像 (动态流水数据)】:
    - 月生活费/总预算: {dynamic_profile['monthly_budget']} 元
    - 本月当前剩余可用资金: {dynamic_profile['current_surplus']} 元
    - 固定开销: {json.dumps(dynamic_profile['fixed_expenses'], ensure_ascii=False)}
    - 近期已购入非必需品: {json.dumps(dynamic_profile['recent_purchases'], ensure_ascii=False)}
    
    【Jerry 过去的消费记忆 (长期向量库 ChromaDB)】:
    {long_term_context if long_term_context else "暂无相关历史消费记忆"}
    """
    
    return refined_query, injected_system_prompt

def save_long_term_memory(refined_query, final_report):
    """ 对话成功后，异步将记忆写入 ChromaDB """
    try:
        memory_collection = get_memory_collection()
        memory_id = f"mem_{os.urandom(4).hex()}"
        memory_collection.add(
            documents=[f"Jerry曾咨询过关于'{refined_query}'的购买建议。当时的最终审计结论是：{final_report[:60]}..."],
            metadatas=[{"source": "chat_history", "query": refined_query}],
            ids=[memory_id]
        )
    except:
        pass