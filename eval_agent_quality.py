import argparse
import csv
import json
import statistics
from datetime import datetime
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent
RESULT_DIR = PROJECT_ROOT / "eval_results"
TRACE_FILE = PROJECT_ROOT / "jerry_trace_logs.jsonl"
PRICE_CASES_FILE = PROJECT_ROOT / "eval_price_cases.csv"


DEFAULT_PRICE_CASES = [
    {"query": "我想买可乐", "item": "可乐", "reference_price": 3.0, "tolerance_pct": 30},
    {"query": "我想买雪碧", "item": "雪碧", "reference_price": 3.0, "tolerance_pct": 30},
    {"query": "我想买矿泉水", "item": "矿泉水", "reference_price": 2.0, "tolerance_pct": 40},
    {"query": "我想买东方树叶", "item": "东方树叶", "reference_price": 5.0, "tolerance_pct": 40},
    {"query": "我想买纸巾", "item": "纸巾", "reference_price": 6.0, "tolerance_pct": 50},
    {"query": "我想买午饭", "item": "午饭", "reference_price": 15.0, "tolerance_pct": 50},
    {"query": "我想买红米耳机", "item": "红米耳机", "reference_price": 100.0, "tolerance_pct": 50},
    {"query": "我想买 iPhone 15", "item": "iPhone 15", "reference_price": 4500.0, "tolerance_pct": 25},
    {"query": "我想买 MacBook", "item": "MacBook", "reference_price": 9000.0, "tolerance_pct": 30},
    {"query": "我想买 2g 内存服务器", "item": "2g 内存服务器", "reference_price": 30.0, "tolerance_pct": 60},
]


def percentile(values, pct):
    if not values:
        return 0.0
    values = sorted(values)
    index = int(round((pct / 100) * (len(values) - 1)))
    return values[index]


def load_traces(trace_path):
    if not trace_path.exists():
        return []

    traces = []
    with open(trace_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                traces.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return traces


def summarize_traces(traces):
    ok_traces = [trace for trace in traces if trace.get("status") == "ok"]
    total_latencies = [float(trace.get("total_latency_ms", 0)) for trace in ok_traces if trace.get("total_latency_ms")]

    stage_map = {}
    for trace in ok_traces:
        for stage in trace.get("stages", []):
            stage_map.setdefault(stage.get("name", "unknown"), []).append(float(stage.get("latency_ms", 0)))

    stage_summary = {}
    for name, values in stage_map.items():
        stage_summary[name] = {
            "count": len(values),
            "avg_ms": round(statistics.mean(values), 2),
            "p95_ms": round(percentile(values, 95), 2),
            "max_ms": round(max(values), 2),
        }

    error_count = sum(len(trace.get("errors", [])) for trace in traces)
    timeout_count = sum(
        1
        for trace in traces
        for stage in trace.get("stages", [])
        if stage.get("status") in {"timeout", "fallback"}
    )

    return {
        "trace_count": len(traces),
        "ok_trace_count": len(ok_traces),
        "error_count": error_count,
        "timeout_or_fallback_count": timeout_count,
        "avg_total_latency_ms": round(statistics.mean(total_latencies), 2) if total_latencies else 0.0,
        "p95_total_latency_ms": round(percentile(total_latencies, 95), 2) if total_latencies else 0.0,
        "max_total_latency_ms": round(max(total_latencies), 2) if total_latencies else 0.0,
        "stage_summary": stage_summary,
    }


def write_price_template(path):
    if path.exists():
        return False
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "query",
                "item",
                "reference_price",
                "system_price",
                "tolerance_pct",
                "notes",
            ],
        )
        writer.writeheader()
        for row in DEFAULT_PRICE_CASES:
            writer.writerow({**row, "system_price": "", "notes": ""})
    return True


def load_price_cases(path):
    if not path.exists():
        write_price_template(path)
        return []

    rows = []
    with open(path, "r", encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            try:
                reference = float(row.get("reference_price") or 0)
                system_price = float(row.get("system_price") or 0)
                tolerance = float(row.get("tolerance_pct") or 20)
            except ValueError:
                continue
            if reference <= 0 or system_price <= 0:
                continue
            error_pct = abs(system_price - reference) / reference * 100
            rows.append({
                "query": row.get("query", ""),
                "item": row.get("item", ""),
                "reference_price": reference,
                "system_price": system_price,
                "tolerance_pct": tolerance,
                "error_pct": round(error_pct, 2),
                "within_tolerance": error_pct <= tolerance,
                "notes": row.get("notes", ""),
            })
    return rows


def summarize_price_cases(rows):
    if not rows:
        return {
            "case_count": 0,
            "within_tolerance_rate": 0.0,
            "avg_error_pct": 0.0,
            "p95_error_pct": 0.0,
            "max_error_pct": 0.0,
        }

    errors = [row["error_pct"] for row in rows]
    within_count = sum(1 for row in rows if row["within_tolerance"])
    return {
        "case_count": len(rows),
        "within_tolerance_rate": round(within_count / len(rows) * 100, 2),
        "avg_error_pct": round(statistics.mean(errors), 2),
        "p95_error_pct": round(percentile(errors, 95), 2),
        "max_error_pct": round(max(errors), 2),
    }


def write_outputs(trace_summary, price_summary, price_rows):
    RESULT_DIR.mkdir(exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    json_path = RESULT_DIR / f"agent_quality_{stamp}.json"
    csv_path = RESULT_DIR / f"price_quality_{stamp}.csv"

    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(
            {
                "generated_at": datetime.now().isoformat(timespec="seconds"),
                "trace_summary": trace_summary,
                "price_summary": price_summary,
                "price_cases": price_rows,
            },
            f,
            ensure_ascii=False,
            indent=2,
        )

    if price_rows:
        with open(csv_path, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=list(price_rows[0].keys()))
            writer.writeheader()
            writer.writerows(price_rows)

    return json_path, csv_path if price_rows else None


def main():
    parser = argparse.ArgumentParser(description="Evaluate Jerry-Insight trace latency and price quality.")
    parser.add_argument("--trace-file", default=str(TRACE_FILE), help="Path to jerry_trace_logs.jsonl.")
    parser.add_argument("--price-cases", default=str(PRICE_CASES_FILE), help="Path to price evaluation CSV.")
    parser.add_argument("--init-price-template", action="store_true", help="Create eval_price_cases.csv template and exit.")
    args = parser.parse_args()

    price_cases_path = Path(args.price_cases)
    if args.init_price_template:
        created = write_price_template(price_cases_path)
        print(f"{'Created' if created else 'Already exists'}: {price_cases_path}")
        return

    write_price_template(price_cases_path)
    traces = load_traces(Path(args.trace_file))
    trace_summary = summarize_traces(traces)
    price_rows = load_price_cases(price_cases_path)
    price_summary = summarize_price_cases(price_rows)
    json_path, csv_path = write_outputs(trace_summary, price_summary, price_rows)

    print("\nJerry-Insight Agent Quality Report")
    print("=" * 40)
    print(f"Trace count: {trace_summary['trace_count']}")
    print(f"OK traces: {trace_summary['ok_trace_count']}")
    print(f"Avg total latency: {trace_summary['avg_total_latency_ms']} ms")
    print(f"P95 total latency: {trace_summary['p95_total_latency_ms']} ms")
    print(f"Timeout/fallback stages: {trace_summary['timeout_or_fallback_count']}")
    print("-" * 40)
    print(f"Price cases with system_price: {price_summary['case_count']}")
    print(f"Within tolerance rate: {price_summary['within_tolerance_rate']}%")
    print(f"Avg price error: {price_summary['avg_error_pct']}%")
    print(f"P95 price error: {price_summary['p95_error_pct']}%")
    print("-" * 40)
    print(f"JSON report: {json_path}")
    if csv_path:
        print(f"Price CSV report: {csv_path}")
    print(f"Price case template/input: {price_cases_path}")


if __name__ == "__main__":
    main()
