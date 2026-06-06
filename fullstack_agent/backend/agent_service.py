import re
import time
from dataclasses import dataclass

from db import (
    adjust_surplus,
    find_memory_context,
    get_current_surplus,
    insert_ledger_entry,
    undo_last_ledger_entry,
)
from original_pipeline import run_original_pipeline
from notifier import notify_async


@dataclass
class AgentResult:
    reply: str
    intent: str
    latency_ms: float
    trace: dict
    payload: dict


def classify_intent(message):
    text = message.strip()
    if any(word in text for word in ["怎么用", "你能干嘛", "帮助", "功能", "使用"]):
        return "help"
    if any(word in text for word in ["撤销", "加错了", "记错了", "撤销上一条", "上一条错了"]):
        return "undo"
    if any(word in text for word in ["加回来", "加回", "退回", "补回", "返还", "退钱", "退了"]):
        return "refund"
    if any(word in text for word in ["买了", "花了", "消费了", "付了", "支出"]):
        return "accounting"
    return "shopping_audit"


def extract_amount(message):
    match = re.search(r"[¥￥]?\s*(\d+(?:\.\d+)?)\s*(?:元|块|块钱|rmb|RMB)", message)
    if not match:
        match = re.search(r"(?:花了|付了|支出|消费了|加回|退回|补回|退了)\s*(\d+(?:\.\d+)?)", message)
    return round(float(match.group(1)), 2) if match else None


def extract_item(message):
    text = message.strip()
    text = re.sub(r"[¥￥]?\s*\d+(?:\.\d+)?\s*(?:元|块|块钱|rmb|RMB)?", "", text)
    stop_words = [
        "我想买",
        "想买",
        "帮我看看",
        "帮我看下",
        "这个",
        "买了",
        "花了",
        "消费了",
        "付了",
        "支出",
        "加回来",
        "加回",
        "退回",
        "补回",
        "返还",
        "退钱",
        "退了",
        "多少钱",
        "值不值得买",
        "值不值得入手",
    ]
    for word in stop_words:
        text = text.replace(word, "")
    text = re.sub(r"[，。！？,.!?、\s]+", "", text)
    return text[:30] or "未知商品"


def normalize_search_sources(info_blocks):
    rows = []
    for block in info_blocks or []:
        try:
            text, url, score = block
        except Exception:
            continue
        rows.append(
            {
                "summary": str(text)[:180],
                "url": str(url),
                "score": round(float(score), 4) if isinstance(score, (int, float)) else score,
            }
        )
    return rows


def normalize_price_table(price_table):
    rows = []
    for row in price_table or []:
        rows.append(
            {
                "platform": row.get("平台") or row.get("渠道平台") or row.get("🛒 渠道平台") or "价格来源",
                "info": row.get("参考报价/情报说明")
                or row.get("参考报价 情报说明")
                or row.get("💰 实时报价与情报")
                or "",
                "url": row.get("数据出处") or row.get("🔗 原始链接") or "",
            }
        )
    return rows


def normalize_crawler_sources(crawler_results):
    return [
        {
            "platform": row.get("platform", "什么值得买"),
            "info": row.get("price_info", ""),
            "url": row.get("source", ""),
        }
        for row in (crawler_results or [])
    ]


def simple_trace(started, intent, stage_name, status="ok"):
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return {
        "stages": [
            {
                "name": "intent_route",
                "status": "ok",
                "latency_ms": 0.0,
                "intent": intent,
            },
            {
                "name": stage_name,
                "status": status,
                "latency_ms": latency_ms,
            },
        ],
        "status": status,
        "total_latency_ms": latency_ms,
    }


def run_accounting(message):
    amount = extract_amount(message)
    item = extract_item(message)
    if amount is None:
        return "我识别到你想记账，但没有找到金额。可以这样输入：买了雪碧花了3块。", {
            "item": item,
            "amount": None,
        }
    current_surplus = adjust_surplus(-amount)
    entry_id = insert_ledger_entry(item=item, amount=amount, source="fastapi_accounting", raw_query=message)
    notify_async(
        "Jerry-Insight 直接记账",
        f"- 商品：`{item}`\n- 扣除：`{amount}` 元\n- 当前余额：`{current_surplus}` 元\n- 原始输入：{message}",
    )
    return (
        f"已记账：{item}，扣除 {amount} 元。当前余额 {current_surplus} 元。流水编号：{entry_id}。",
        {"item": item, "amount": amount, "entry_id": entry_id, "current_surplus": current_surplus},
    )


def run_refund(message):
    amount = extract_amount(message)
    item = extract_item(message) or "余额修正"
    if amount is None:
        return "我识别到你想加回余额，但没有找到金额。可以这样输入：加回来3块。", {
            "item": item,
            "amount": None,
        }
    current_surplus = adjust_surplus(amount)
    entry_id = insert_ledger_entry(item=item, amount=amount, source="fastapi_refund", raw_query=message, status="refund")
    notify_async(
        "Jerry-Insight 余额加回",
        f"- 项目：`{item}`\n- 加回：`{amount}` 元\n- 当前余额：`{current_surplus}` 元\n- 原始输入：{message}",
    )
    return (
        f"已加回余额：{item}，加回 {amount} 元。当前余额 {current_surplus} 元。流水编号：{entry_id}。",
        {"item": item, "amount": amount, "entry_id": entry_id, "current_surplus": current_surplus},
    )


def run_undo():
    entry = undo_last_ledger_entry()
    if not entry:
        return "当前没有可撤销的账本流水。", {"undone": False}
    current_surplus = adjust_surplus(entry["amount"])
    notify_async(
        "Jerry-Insight 撤销上一笔",
        f"- 撤销项目：`{entry['item']}`\n- 退回金额：`{entry['amount']}` 元\n- 当前余额：`{current_surplus}` 元",
    )
    return (
        f"已撤销上一笔：{entry['item']}，金额 {entry['amount']} 元，已退回余额。当前余额 {current_surplus} 元。",
        {"undone": True, "entry": entry, "current_surplus": current_surplus},
    )


def run_help():
    return (
        "你可以直接问商品值不值得买，比如“我想买东方树叶”；也可以直接记账，比如“买了雪碧花了3块”；"
        "记错了可以输入“撤销上一条”或“加错了”。"
    )


def run_shopping_audit(message):
    result = run_original_pipeline(message)
    payload = {
        "item": result["item"],
        "price": result["price"],
        "display_answer": result["display_answer"],
        "info_blocks": result["info_blocks"],
        "search_sources": normalize_search_sources(result["info_blocks"]),
        "price_table": normalize_price_table(result["price_table_data"]),
        "crawler_results": result["crawler_results"],
        "crawler_sources": normalize_crawler_sources(result["crawler_results"]),
        "long_term_context": result["long_term_context"],
        "memory_hits": result["memory_hits"],
        "current_surplus": result["current_surplus"],
    }
    notify_async(
        "Jerry-Insight 审计结果",
        f"- 用户问题：{message}\n- 商品：`{result['item']}`\n- 估算单价：`{result['price']}` 元\n\n{result['display_answer'][:900]}",
    )
    return result["display_answer"], payload, result["trace"]


def run_agent(message):
    started = time.perf_counter()
    intent = classify_intent(message)
    payload = {}

    if intent == "accounting":
        reply, payload = run_accounting(message)
        trace = simple_trace(started, intent, "ledger_write")
    elif intent == "undo":
        reply, payload = run_undo()
        trace = simple_trace(started, intent, "ledger_undo")
    elif intent == "refund":
        reply, payload = run_refund(message)
        trace = simple_trace(started, intent, "ledger_refund")
    elif intent == "help":
        reply = run_help()
        payload = {"current_surplus": get_current_surplus(), "memory_hits": find_memory_context(message, limit=3)}
        trace = simple_trace(started, intent, "help_reply")
    else:
        reply, payload, trace = run_shopping_audit(message)

    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    trace["total_latency_ms"] = latency_ms
    trace["status"] = trace.get("status", "ok")
    return AgentResult(reply=reply, intent=intent, latency_ms=latency_ms, trace=trace, payload=payload)
