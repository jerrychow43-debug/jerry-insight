import re
import sys
import os

# ✨ 动态确保项目根目录在 Python 搜索路径第一位
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from core.brain import ask_llm

def classify_intent(query):
    """
    意图识别：防止 Agent 乱跑。
    具备对大脑连接失败时的【真实自愈放行】机制。
    """
    if not query or len(query.strip()) < 2:
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
    ✨【核心升级重构】：商品关键词智能清洗。
    通过调用 DeepSeek 大模型配合工业级规则，彻底斩断长句子污染和非商品输入。
    """
    if not query or len(query.strip()) < 2:
        return "NONE"

    # 1. 强力提示词：逼迫 AI 只返回最纯粹的商品名称
    prompt = f"""
    你是一个极其精准的【商品名称/实体提取器】。
    请分析用户的输入，从中仅提取出最核心的、可以去电商平台搜索的【商品型号或名称】，去除所有无意义的修饰词、动作、语气词或场景。
    
    ⚠️【核心死命令】：
    1. 只能返回清洗后的商品名称本身，绝对不能包含任何标点符号、连字符或多余解释。
    2. 如果用户的输入不是一件商品（例如是某种行为分析、日常聊天、漏洞审计、大额转账风控），请直接返回大写单词："NONE"。

    【示例】
    输入：我想买个苹果15手机，帮我看看便宜不
    输出：iPhone 15

    输入：某二手平台高风险二手大疆无人机大额转账审计
    输出：NONE

    输入：帮我看看雪碧
    输出：雪碧

    现在请处理以下用户输入：
    {query}
    """
    
    try:
        res = ask_llm([{"role": "user", "content": prompt}])
        entity = res.strip().replace('"', '').replace("'", "")
        
        # 2. 拦截安全阀：将长度限制放宽到 24 字符。
        # 很多商品带上型号和规格（例如：MacBook Pro 16寸 M3）很容易超过12个字，改为24更安全。
        if "NONE" in entity.upper() or "失败" in entity or len(entity) > 24:
            return "NONE"
            
        return entity
    except Exception as e:
        print(f"⚠️ [提取商品实体异常] 降级处理: {e}")
        # 如果大模型崩了，用基础正则兜底
        stop_phrases = ["我想买", "有人买过", "怎么样", "好不好", "求推荐", "评测一下", "有没有人", "想入一个", "测评", "入手"]
        clean_keyword = query
        for phrase in stop_phrases:
            clean_keyword = clean_keyword.replace(phrase, "")
        clean_keyword = re.sub(r'[^\w\s\u4e00-\u9fa5]', '', clean_keyword).strip()
        return clean_keyword if len(clean_keyword) <= 24 else "NONE"