import argparse
import csv
import json
import os
import re
import statistics
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
RESULT_DIR = PROJECT_ROOT / "eval_results"


TEST_CASES = [
    {"category": "help", "text": "怎么用", "expected_intent": "HELP"},
    {"category": "help", "text": "你能干嘛", "expected_intent": "HELP"},
    {"category": "help", "text": "有什么功能", "expected_intent": "HELP"},
    {"category": "help", "text": "帮助", "expected_intent": "HELP"},
    {"category": "smalltalk", "text": "你好", "expected_intent": "GENERAL_REPLY"},
    {"category": "smalltalk", "text": "谢谢", "expected_intent": "GENERAL_REPLY"},
    {"category": "shopping", "text": "我想买可乐", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "帮我看看 iPhone 15 值不值得买", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "可乐多少钱", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "我想买一瓶雪碧", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "帮我看看这个耳机贵不贵", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "我想买一台服务器 2g 内存的", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "帮我比价一下红米耳机", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "这个 MacBook 值不值得入手", "expected_intent": "SHOPPING"},
    {"category": "shopping", "text": "我想买东方树叶", "expected_intent": "SHOPPING"},
    {"category": "direct_accounting", "text": "买了雪碧花了3块", "expected_intent": "DIRECT_ACCOUNTING", "amount": 3.0},
    {"category": "direct_accounting", "text": "今天花12.5元买午饭", "expected_intent": "DIRECT_ACCOUNTING", "amount": 12.5},
    {"category": "direct_accounting", "text": "消费了8元咖啡", "expected_intent": "DIRECT_ACCOUNTING", "amount": 8.0},
    {"category": "direct_accounting", "text": "买了可乐花了3块钱", "expected_intent": "DIRECT_ACCOUNTING", "amount": 3.0},
    {"category": "direct_accounting", "text": "已经买了纸巾花了6元", "expected_intent": "DIRECT_ACCOUNTING", "amount": 6.0},
    {"category": "direct_accounting", "text": "刚才付了18元打车", "expected_intent": "DIRECT_ACCOUNTING", "amount": 18.0},
    {"category": "direct_accounting", "text": "支出25元买书", "expected_intent": "DIRECT_ACCOUNTING", "amount": 25.0},
    {"category": "refund", "text": "加回来3块", "expected_intent": "REFUND", "amount": 3.0},
    {"category": "refund", "text": "退回雪碧3元", "expected_intent": "REFUND", "amount": 3.0},
    {"category": "refund", "text": "补回500元", "expected_intent": "REFUND", "amount": 500.0},
    {"category": "refund", "text": "把余额加回10块", "expected_intent": "REFUND", "amount": 10.0},
    {"category": "refund", "text": "退钱12.5元", "expected_intent": "REFUND", "amount": 12.5},
    {"category": "undo", "text": "撤销上一笔", "expected_intent": "UNDO"},
    {"category": "undo", "text": "撤销上一条", "expected_intent": "UNDO"},
    {"category": "undo", "text": "撤销上次", "expected_intent": "UNDO"},
    {"category": "undo", "text": "撤销刚才", "expected_intent": "UNDO"},
    {"category": "undo", "text": "退回上一笔", "expected_intent": "UNDO"},
    {"category": "undo", "text": "取消上一条", "expected_intent": "UNDO"},
    {"category": "undo", "text": "上一笔记错了", "expected_intent": "UNDO"},
    {"category": "undo", "text": "加错了", "expected_intent": "UNDO"},
    {"category": "general", "text": "今天心情不好", "expected_intent": "SHOPPING"},
    {"category": "general", "text": "随便问一句天气怎么样", "expected_intent": "SHOPPING"},
    {"category": "general", "text": "111111", "expected_intent": "SHOPPING"},
]


def is_undo_request(text):
    normalized = text.strip()
    undo_words = [
        "撤销上一笔", "撤销上一条", "撤销上次", "撤销刚才",
        "退回上一笔", "退回上一条", "取消上一笔", "取消上一条",
        "上一笔记错了", "上一条记错了", "加错了",
    ]
    return any(word in normalized for word in undo_words)


def parse_refund_input(text):
    normalized = text.strip()
    if not any(word in normalized for word in ["加回来", "加回", "退回", "补回", "返还", "退钱", "退了"]):
        return None
    amount_match = re.search(r"[￥¥]?\s*(\d+(?:\.\d+)?)\s*(?:元|块|块钱|rmb|RMB)", normalized)
    if not amount_match:
        return None
    return {"amount": round(float(amount_match.group(1)), 2)}


def parse_direct_accounting_input(text):
    normalized = text.strip()
    has_done_signal = any(word in normalized for word in ["买了", "花了", "花", "消费了", "付了", "付款", "支出", "用了"])
    has_future_signal = any(word in normalized for word in ["想买", "准备买", "打算买", "要不要买", "值不值得", "多少钱", "问价"])
    if not has_done_signal or has_future_signal:
        return None

    amount_match = re.search(
        r"(?:花了|花|消费了|消费|付了|付款|支出|用了)?\s*[￥¥]?\s*(\d+(?:\.\d+)?)\s*(?:元|块|块钱|rmb|RMB)",
        normalized,
    )
    if not amount_match:
        return None
    return {"amount": round(float(amount_match.group(1)), 2)}


def get_general_reply_intent(text):
    normalized = text.strip().lower()
    help_words = ["怎么用", "如何使用", "使用方法", "你能干嘛", "能做什么", "帮助", "help", "说明", "功能", "教程"]
    greeting_words = ["你好", "hello", "hi", "在吗", "早上好", "晚上好"]
    thanks_words = ["谢谢", "谢了", "thanks", "thank you"]

    if any(word in normalized or word in text for word in help_words):
        return "HELP"
    if any(word in normalized or word in text for word in greeting_words + thanks_words):
        return "GENERAL_REPLY"
    return None


def route_input(text):
    if is_undo_request(text):
        return {"intent": "UNDO"}

    refund = parse_refund_input(text)
    if refund:
        return {"intent": "REFUND", **refund}

    direct = parse_direct_accounting_input(text)
    if direct:
        return {"intent": "DIRECT_ACCOUNTING", **direct}

    general = get_general_reply_intent(text)
    if general:
        return {"intent": general}

    return {"intent": "SHOPPING"}


def simulate_balance_operation(routed, balance, ledger):
    intent = routed["intent"]
    amount = routed.get("amount")

    if intent == "DIRECT_ACCOUNTING":
        balance = round(balance - amount, 2)
        ledger.append({"amount": amount, "status": "active"})
        return balance, True

    if intent == "REFUND":
        balance = round(balance + amount, 2)
        ledger.append({"amount": amount, "status": "refund"})
        return balance, True

    if intent == "UNDO":
        for entry in reversed(ledger):
            if entry.get("status") == "active":
                entry["status"] = "cancelled"
                balance = round(balance + entry["amount"], 2)
                return balance, True
        return balance, False

    return balance, True


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    index = int(round((pct / 100) * (len(values) - 1)))
    return values[index]


def run_case_benchmark(start_balance):
    rows = []
    balance = start_balance
    ledger = []

    for case in TEST_CASES:
        if case["expected_intent"] == "UNDO":
            balance = round(balance - 1.0, 2)
            ledger.append({"amount": 1.0, "status": "active"})

        before_balance = balance
        started = time.perf_counter()
        routed = route_input(case["text"])
        balance, operation_success = simulate_balance_operation(routed, balance, ledger)
        latency_ms = (time.perf_counter() - started) * 1000

        expected_intent = case["expected_intent"]
        actual_intent = routed["intent"]
        intent_correct = expected_intent == actual_intent

        expected_amount = case.get("amount")
        actual_amount = routed.get("amount")
        amount_correct = expected_amount is None or actual_amount == expected_amount

        rows.append({
            "category": case["category"],
            "input": case["text"],
            "expected_intent": expected_intent,
            "actual_intent": actual_intent,
            "intent_correct": intent_correct,
            "expected_amount": expected_amount,
            "actual_amount": actual_amount,
            "amount_correct": amount_correct,
            "operation_success": operation_success,
            "balance_before": before_balance,
            "balance_after": balance,
            "latency_ms": round(latency_ms, 4),
        })

    return rows


def run_async_isolation_benchmark(task_count=10, max_workers=5, simulated_network_ms=200):
    def slow_network_call():
        time.sleep(simulated_network_ms / 1000)
        return True

    executor = ThreadPoolExecutor(max_workers=max_workers)
    started = time.perf_counter()
    futures = [executor.submit(slow_network_call) for _ in range(task_count)]
    enqueue_ms = (time.perf_counter() - started) * 1000

    wait_started = time.perf_counter()
    for future in futures:
        future.result()
    total_wait_ms = (time.perf_counter() - wait_started) * 1000
    executor.shutdown(wait=True)

    return {
        "task_count": task_count,
        "max_workers": max_workers,
        "simulated_network_ms": simulated_network_ms,
        "main_thread_enqueue_ms": round(enqueue_ms, 4),
        "background_total_wait_ms": round(total_wait_ms, 4),
        "main_thread_isolated": enqueue_ms < simulated_network_ms * 0.1,
    }


def write_outputs(rows, async_result):
    RESULT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    csv_path = RESULT_DIR / f"resume_metrics_{stamp}.csv"
    json_path = RESULT_DIR / f"resume_metrics_{stamp}.json"

    latencies = [row["latency_ms"] for row in rows]
    intent_accuracy = sum(1 for row in rows if row["intent_correct"]) / len(rows)
    amount_accuracy = sum(1 for row in rows if row["amount_correct"]) / len(rows)
    operation_rows = [row for row in rows if row["actual_intent"] in {"DIRECT_ACCOUNTING", "REFUND", "UNDO"}]
    operation_success = sum(1 for row in operation_rows if row["operation_success"]) / max(len(operation_rows), 1)

    summary = {
        "case_count": len(rows),
        "intent_accuracy": round(intent_accuracy * 100, 2),
        "amount_accuracy": round(amount_accuracy * 100, 2),
        "operation_case_count": len(operation_rows),
        "operation_success_rate": round(operation_success * 100, 2),
        "avg_route_latency_ms": round(statistics.mean(latencies), 4),
        "p95_route_latency_ms": round(percentile(latencies, 95), 4),
        "max_route_latency_ms": round(max(latencies), 4),
        "async_isolation": async_result,
        "generated_at": datetime.now().isoformat(timespec="seconds"),
    }

    with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump({"summary": summary, "cases": rows}, f, ensure_ascii=False, indent=2)

    return csv_path, json_path, summary


def main():
    parser = argparse.ArgumentParser(description="Generate resume-ready evaluation metrics for Jerry-Insight.")
    parser.add_argument("--start-balance", type=float, default=1000.0, help="Initial balance for simulated ledger operations.")
    args = parser.parse_args()

    rows = run_case_benchmark(args.start_balance)
    async_result = run_async_isolation_benchmark()
    csv_path, json_path, summary = write_outputs(rows, async_result)

    print("\nJerry-Insight Resume Metrics")
    print("=" * 36)
    print(f"Cases: {summary['case_count']}")
    print(f"Intent accuracy: {summary['intent_accuracy']}%")
    print(f"Amount extraction accuracy: {summary['amount_accuracy']}%")
    print(f"Ledger operation success rate: {summary['operation_success_rate']}%")
    print(f"Average routing latency: {summary['avg_route_latency_ms']} ms")
    print(f"P95 routing latency: {summary['p95_route_latency_ms']} ms")
    print(f"Async enqueue latency: {summary['async_isolation']['main_thread_enqueue_ms']} ms")
    print(f"CSV: {csv_path}")
    print(f"JSON: {json_path}")


if __name__ == "__main__":
    main()
