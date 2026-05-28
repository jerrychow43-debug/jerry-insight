import re
from core.brain import ask_llm

def classify_intent(query):
    """
    意图识别：防止 Agent 乱跑。
    具备对大脑连接失败时的【真实自愈放行】机制。
    """
    if len(query.strip()) < 2:
        return "INVALID"

    prompt = f"""
    你是一个任务分拣器。请分析用户的输入，判断其意图。
    如果用户是想查询商品信息、买东西、排雷、对比评价：返回 'SHOPPING'。
    如果用户只是在乱打字、发无意义的数字、或者完全无法理解：返回 'INVALID'。
    
    注意：只返回单词本身，不要标点符号。
    用户输入：{query}
    """
    
    # 调用大脑进行分类
    res = ask_llm([{"role": "user", "content": prompt}])
    
    # 工业级防崩漏洞修复：如果大脑里返回了“失败”，说明 Key 或网络挂了，为了不拦住 Jerry，直接强行放行！
    if "大脑连接失败" in res:
        return "SHOPPING"
        
    res_clean = res.strip().upper()
    
    # 只要包含 SHOPPING 就算过
    if "SHOPPING" in res_clean:
        return "SHOPPING"
        
    return "INVALID"

def clean_query_to_entity(query: str) -> str:
    """
    新增核心函数：商品关键词清洗。
    把“我想买可乐”、“有没有人评测一下润百颜”自动清洗成“可乐”、“润百颜”。
    """
    stop_phrases = ["我想买", "有人买过", "怎么样", "好不好", "求推荐", "评测一下", "有没有人", "想入一个", "测评", "入手"]
    clean_keyword = query
    for phrase in stop_phrases:
        clean_keyword = clean_keyword.replace(phrase, "")
    clean_keyword = re.sub(r'[^\w\s\u4e00-\u9fa5]', '', clean_keyword).strip()
    return clean_keyword if clean_keyword else query