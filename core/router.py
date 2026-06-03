import re
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.append(str(ROOT_DIR))


def _ask_llm(messages, json_mode=False):
    try:
        from core.brain import ask_llm
        return ask_llm(messages, json_mode=json_mode)
    except Exception as exc:
        return f"大脑连接失败: {exc}"


def fallback_clean_query_to_entity(query: str) -> str:
    """Deterministic fallback when the LLM extractor is unavailable or too strict."""
    if not query:
        return "NONE"

    clean_keyword = query.strip()
    stop_phrases = [
        "我想买", "想买", "想入", "想入手", "买一个", "买个", "买一台",
        "帮我看看", "帮我看下", "帮我查查", "看看", "看下",
        "值不值得", "值不值", "能买吗", "买不买", "贵不贵", "多少钱",
        "价格", "比价", "推荐", "评测一下", "评测", "测评", "有没有人",
        "有没有", "有人买过", "好不好", "怎么样", "便宜不", "划算不",
        "一下", "这个", "那个",
    ]
    for phrase in stop_phrases:
        clean_keyword = clean_keyword.replace(phrase, " ")
    clean_keyword = re.sub(r"[^\w\s\u4e00-\u9fa5]", " ", clean_keyword)
    clean_keyword = re.sub(r"\s+", " ", clean_keyword).strip()
    return clean_keyword[:40] if clean_keyword else "NONE"


def classify_intent(query):
    if not query or len(query.strip()) < 2:
        return "INVALID"

    prompt = f"""
你是一个任务分拣器。请分析用户的输入，判断其意图。
如果用户是想查询商品信息、买东西、排雷、对比评价：返回 'SHOPPING'。
如果用户只是在乱打字、发无意义的数字、或者完全无法理解：返回 'INVALID'。

注意：只返回单词本身，不要标点符号。
用户输入：{query}
"""

    res = _ask_llm([{"role": "user", "content": prompt}])
    if "大脑连接失败" in res:
        return "SHOPPING"

    res_clean = res.strip().upper()
    if "SHOPPING" in res_clean:
        return "SHOPPING"
    return "INVALID"


def clean_query_to_entity(query: str) -> str:
    if not query or len(query.strip()) < 2:
        return "NONE"

    fallback = fallback_clean_query_to_entity(query)
    prompt = f"""
你是一个极其精准的【商品名称/实体提取器】。
请从用户输入中仅提取最核心、可用于电商平台搜索的商品名称或型号。

规则：
1. 只能返回商品名称本身，不要解释。
2. 如果不是商品，返回 NONE。

示例：
输入：我想买个苹果15手机，帮我看看便宜不
输出：iPhone 15

输入：帮我看看雪碧
输出：雪碧

用户输入：
{query}
"""

    try:
        res = _ask_llm([{"role": "user", "content": prompt}])
        entity = res.strip().replace('"', "").replace("'", "")
        if "NONE" in entity.upper() or "失败" in entity or len(entity) > 24:
            return fallback
        return entity
    except Exception as exc:
        print(f"商品实体提取异常，使用本地兜底: {exc}")
        return fallback
