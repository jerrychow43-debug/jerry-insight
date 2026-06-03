import re
from dataclasses import dataclass
from typing import Optional


@dataclass
class ParsedIntent:
    intent: str
    item_name: Optional[str] = None
    amount: Optional[float] = None
    reply: Optional[str] = None


GUIDE_REPLY = (
    "我主要负责帮你做消费决策、比价和记账。\n\n"
    "- 想买东西时，可以说：我想买 iPhone 15，帮我看看值不值得。\n"
    "- 已经花钱了，可以说：我买了一块田，花了 500 元。\n"
    "- 我会结合预算、历史记录和价格信息给你建议；如果是明确消费金额，我会直接帮你记账。"
)

HELP_PATTERNS = [
    "怎么用", "如何使用", "使用方法", "你能干嘛", "能做什么", "帮助", "help",
    "说明", "功能", "教程", "怎么操作", "介绍一下", "使用指南",
]

SHOPPING_PATTERNS = [
    "想买", "能买吗", "值得买", "值不值得", "便宜", "贵不贵", "多少钱",
    "价格", "比价", "推荐", "入手", "买不买", "看看", "评测", "哪里买",
    "报价", "划算", "优惠",
]

COMMON_PRODUCT_TERMS = [
    "可乐", "雪碧", "芬达", "饮料", "矿泉水", "咖啡", "奶茶", "茶",
    "耳机", "手机", "电脑", "键盘", "鼠标", "相机", "无人机", "充电器",
    "书", "衣服", "鞋", "包", "零食", "泡面", "纸巾",
]

DIRECT_EXPENSE_PATTERNS = [
    re.compile(
        r"(?:我|俺|刚刚|刚才|今天|昨天|已经)?\s*"
        r"(?:买了|购买了|购入|入手了|花了|消费了|支出|扣款|记账|记一下)\s*"
        r"(?P<item>.*?)\s*"
        r"(?:已经|一共|总共|花了|用了|消费了|支出|付款|扣款)?\s*"
        r"(?P<amount>\d+(?:\.\d+)?)\s*"
        r"(?:元|块|rmb|RMB|￥)"
    ),
    re.compile(
        r"(?:买|买了|购买了|购入|入手了)\s*"
        r"(?P<item>.*?)\s*"
        r"(?:已经)?\s*(?:花了|用了|消费了|支出|付款|扣款)\s*"
        r"(?P<amount>\d+(?:\.\d+)?)\s*"
        r"(?:元|块|rmb|RMB|￥)?"
    ),
    re.compile(
        r"(?P<item>.*?)\s*"
        r"(?:花了|用了|消费了|支出|付款|扣款)?\s*"
        r"(?P<amount>\d+(?:\.\d+)?)\s*"
        r"(?:元|块|rmb|RMB|￥)\s*"
        r"(?:记一下|记账|扣钱|扣款|买了|已买|消费)?"
    ),
    re.compile(
        r"(?:扣|扣掉|记账)\s*"
        r"(?P<amount>\d+(?:\.\d+)?)\s*"
        r"(?:元|块|rmb|RMB|￥)?\s*"
        r"(?:买了|用于|因为)?\s*"
        r"(?P<item>.*)"
    ),
]


def _clean_item_name(item: str) -> str:
    item = item or ""
    item = re.sub(
        r"^(我|俺|刚刚|刚才|今天|昨天|已经|买了|购买了|购入|入手了|花了|消费了|支出|扣款|记账|记一下)+",
        "",
        item,
    )
    item = re.sub(r"(花了|用了|消费了|支出|付款|扣款|价格|金额|一共|总共)$", "", item)
    item = item.strip(" ，。！？；：,.!?;:\"'`()[]{}")
    return item[:40]


def parse_direct_expense(query: str) -> Optional[ParsedIntent]:
    text = (query or "").strip()
    if not text:
        return None

    for pattern in DIRECT_EXPENSE_PATTERNS:
        match = pattern.search(text)
        if not match:
            continue
        amount = float(match.group("amount"))
        item = _clean_item_name(match.groupdict().get("item") or "")
        if amount <= 0 or not item:
            continue
        return ParsedIntent(intent="DIRECT_EXPENSE", item_name=item, amount=amount)
    return None


def classify_user_intent(query: str) -> ParsedIntent:
    text = (query or "").strip()
    if len(text) < 2:
        return ParsedIntent(intent="INVALID", reply=f"我没太看清你的输入。\n\n{GUIDE_REPLY}")

    direct_expense = parse_direct_expense(text)
    if direct_expense:
        return direct_expense

    lowered = text.lower()
    if any(p in lowered or p in text for p in HELP_PATTERNS):
        return ParsedIntent(intent="HELP_OR_META", reply=GUIDE_REPLY)

    if any(p in lowered or p in text for p in SHOPPING_PATTERNS):
        return ParsedIntent(intent="SHOPPING_QUERY")

    if any(term in text for term in COMMON_PRODUCT_TERMS):
        return ParsedIntent(intent="SHOPPING_QUERY")

    return ParsedIntent(
        intent="SMALLTALK_OR_OTHER",
        reply=(
            "这个问题我可以简单回应，但我的主业是帮你做消费判断、比价和记账。\n\n"
            f"{GUIDE_REPLY}"
        ),
    )
