from __future__ import annotations

import re
import time
from dataclasses import asdict, dataclass
from datetime import datetime
from typing import Any
from uuid import uuid4

from db import find_memory_context, get_current_surplus, list_ledger
from mcp_gateway import mcp_gateway
from original_pipeline import run_original_pipeline


@dataclass
class ResearchQuestion:
    question: str
    owner: str
    purpose: str


@dataclass
class EvidenceItem:
    category: str
    title: str
    summary: str
    source: str
    url: str
    confidence: str
    price_text: str = ""


@dataclass
class ResearchStep:
    name: str
    summary: str
    latency_ms: int = 0
    status: str = "ok"


@dataclass
class AgentRun:
    agent: str
    role: str
    status: str
    tool_calls: list[dict[str, Any]]
    summary: str


@dataclass
class DealResearchRun:
    run_id: str
    query: str
    product: str
    status: str
    created_at: str
    questions: list[ResearchQuestion]
    evidence: list[EvidenceItem]
    steps: list[ResearchStep]
    personal_context: dict[str, Any]
    decision: dict[str, Any]
    legacy_audit: dict[str, Any]
    agent_runs: list[AgentRun]
    mcp_calls: list[dict[str, Any]]
    report: str


RUNS: list[DealResearchRun] = []


def _mcp_call(tool: str, arguments: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
    result = mcp_gateway.call_tool(tool, arguments)
    call = {"tool": tool, "arguments": arguments, "result": result}
    trace.append(call)
    return result.get("structuredContent") or {}


def _extract_budget(query: str) -> float | None:
    match = re.search(r"(\d+(?:\.\d+)?)\s*(?:元|块|块钱|rmb|RMB|以内|预算)", query)
    return float(match.group(1)) if match else None


def _plan_questions(product: str) -> list[ResearchQuestion]:
    return [
        ResearchQuestion(
            f"{product} 当前公开价格和可买渠道是什么？",
            "Price Researcher",
            "调用省钱智探核心搜索和价格渠道面板，先拿外部证据。",
        ),
        ResearchQuestion(
            f"{product} 有哪些差评、缺点、售后或低价风险？",
            "Risk Researcher",
            "调用省钱智探的避坑判断，不只看价格便宜。",
        ),
        ResearchQuestion(
            f"有没有同预算替代品或更值得等的购买时机？",
            "Alternative Researcher",
            "把一次购买变成调研任务，而不是直接给一句建议。",
        ),
        ResearchQuestion(
            "结合 Jerry 的余额、账本、历史记忆，这次消费是否合理？",
            "Personal Context Agent",
            "接入账本、记忆召回、购买确认和放弃购买闭环。",
        ),
    ]


def _value_by_position(row: dict[str, Any], index: int, default: str = "") -> str:
    values = list(row.values())
    if index < len(values):
        return str(values[index] or "")
    return default


def _url_from_row(row: dict[str, Any]) -> str:
    for value in row.values():
        text = str(value or "")
        if text.startswith("http://") or text.startswith("https://"):
            return text
    return ""


def _extract_price_text(text: str) -> str:
    if not text:
        return ""
    patterns = [
        r"(?:券后|到手|售价|价格|低至|仅需|约|￥|¥)\s*[￥¥]?\s*\d+(?:\.\d+)?\s*(?:元|块)?",
        r"[￥¥]\s*\d+(?:\.\d+)?",
        r"\d+(?:\.\d+)?\s*(?:元|块)",
    ]
    for pattern in patterns:
        matches = []
        for match in re.findall(pattern, text):
            item = str(match).strip()
            if item and item not in matches:
                matches.append(item)
            if len(matches) >= 3:
                break
        if matches:
            return " / ".join(matches)
    return ""


def _price_value(label: str) -> float | None:
    match = re.search(r"\d+(?:\.\d+)?", label or "")
    return float(match.group(0)) if match else None


def _dedupe_price_labels(labels: list[str]) -> list[str]:
    cleaned = []
    seen_numbers = set()
    for label in labels:
        value = _price_value(label)
        if value is None:
            continue
        key = str(value)
        if key in seen_numbers:
            continue
        seen_numbers.add(key)
        cleaned.append(label.strip())
    return cleaned


def _clean_price_text_for_budget(price_text: str, budget: float | None) -> str:
    if not budget or not price_text:
        return price_text
    labels = [item.strip() for item in price_text.split("/") if item.strip()]
    kept = []
    for label in labels:
        value = _price_value(label)
        if value is None:
            continue
        if budget * 0.25 <= value <= budget * 1.25:
            kept.append(label)
    return " / ".join(_dedupe_price_labels(kept)[:3])


def _price_from_row(row: dict[str, Any]) -> str:
    explicit = str(row.get("识别价格") or row.get("price_text") or "").strip()
    if explicit and "核实" not in explicit:
        return explicit
    for key, value in row.items():
        key_text = str(key)
        value_text = str(value or "")
        if "价格" in key_text or "报价" in key_text:
            extracted = _extract_price_text(value_text)
            if extracted:
                return extracted
    extracted = _extract_price_text(" ".join(str(value or "") for value in row.values()))
    return extracted


def _normalize_price_table(rows: list[dict[str, Any]], budget: float | None = None) -> list[dict[str, str]]:
    normalized = []
    for row in rows or []:
        price_text = _clean_price_text_for_budget(_price_from_row(row), budget)
        if budget and not price_text:
            continue
        info = row.get("参考报价/情报说明") or _value_by_position(row, 1, "")
        if budget and price_text:
            info = f"预算范围内识别到可能价格：{price_text}；最终以来源页实时价格为准。"
        normalized.append(
            {
                "platform": _value_by_position(row, 0, "价格来源"),
                "info": info,
                "price_text": price_text,
                "title": str(row.get("标题") or ""),
                "domain": str(row.get("来源域名") or ""),
                "url": _url_from_row(row),
            }
        )
    return normalized


def _normalize_search_sources(blocks: list[Any]) -> list[dict[str, Any]]:
    sources = []
    for block in blocks or []:
        try:
            text, url, score = block
        except Exception:
            continue
        sources.append(
            {
                "summary": str(text or "")[:260],
                "url": str(url or ""),
                "score": round(float(score), 4) if isinstance(score, (int, float)) else score,
            }
        )
    return sources


def _normalize_crawler_sources(rows: list[dict[str, Any]]) -> list[dict[str, str]]:
    return [
        {
            "platform": str(row.get("platform") or "什么值得买"),
            "info": str(row.get("price_info") or ""),
            "price_text": _extract_price_text(str(row.get("price_info") or "")),
            "url": str(row.get("source") or ""),
        }
        for row in rows or []
    ]

def _evidence_from_legacy(product: str, legacy: dict[str, Any]) -> list[EvidenceItem]:
    evidence: list[EvidenceItem] = []
    for row in legacy["price_table"][:4]:
        if not row.get("price_text"):
            continue
        evidence.append(
            EvidenceItem(
                "price",
                row["platform"] or f"{product} 价格渠道",
                row["info"] or "搜索摘要中识别到价格线索，最终以来源页实时价格为准。",
                "Tavily price panel",
                row["url"],
                "high" if row["url"] else "medium",
                row.get("price_text", ""),
            )
        )
    for row in legacy["crawler_sources"][:3]:
        if not row.get("price_text"):
            continue
        evidence.append(
            EvidenceItem(
                "deal",
                row["platform"],
                row["info"] or "搜索补充来源返回的优惠线索。",
                "search price source",
                row["url"],
                "medium" if row["url"] else "low",
                row.get("price_text", ""),
            )
        )
    for row in legacy["search_sources"][:4]:
        evidence.append(
            EvidenceItem(
                "risk",
                f"{product} 评价/避坑来源",
                row["summary"],
                "Tavily search",
                row["url"],
                "medium" if row.get("url") else "low",
            )
        )
    if not evidence:
        evidence.append(
            EvidenceItem(
                "fallback",
                f"{product} 离线审计结果",
                "搜索证据没有返回可展示来源，本次只保留省钱智探的离线判断和账本上下文。",
                "offline fallback",
                "",
                "low",
            )
        )
    return evidence


def _personal_context(query: str, finance_context: dict[str, Any] | None = None) -> dict[str, Any]:
    finance_context = finance_context or {}
    ledger = finance_context.get("ledger") or list_ledger(limit=12)
    memory_hits = find_memory_context(query, limit=5)
    active_rows = [row for row in ledger if row.get("status") == "active"]
    total_recent = round(sum(float(row.get("amount") or 0) for row in active_rows), 2)
    return {
        "current_surplus": finance_context.get("current_surplus", get_current_surplus()),
        "recent_ledger_count": len(ledger),
        "recent_active_spend": total_recent,
        "memory_hit_count": len(memory_hits),
        "memory_hits": memory_hits,
        "recent_ledger": ledger[:6],
        "blocked_items": (finance_context.get("blocked_items") or [])[:6],
        "history": (finance_context.get("history") or [])[:6],
    }


def _decision(query: str, product: str, price: float, legacy_answer: str, evidence: list[EvidenceItem], context: dict[str, Any]) -> dict[str, Any]:
    budget = _extract_budget(query)
    answer = legacy_answer or ""
    has_linked_evidence = any(item.url for item in evidence)
    confidence = "high" if has_linked_evidence and len(evidence) >= 4 else "medium" if has_linked_evidence else "low"

    if budget and price and price > budget:
        verdict = "暂缓"
        reason = f"旧省钱智探估算价格约 {price} 元，超过你输入的预算 {budget} 元。"
    elif any(word in answer for word in ["建议避坑", "持币观望", "观望", "不建议"]):
        verdict = "先观察"
        reason = "省钱智探给出了避坑或观望倾向，建议先核实来源和替代品。"
    elif any(word in answer for word in ["建议购买", "可以入手", "值得"]):
        verdict = "可考虑"
        reason = "省钱智探倾向可买，但仍建议先看价格来源、差评和个人预算。"
    else:
        verdict = "先观察"
        reason = "证据还没有强到可以直接购买，建议把它放入观察清单。"

    return {
        "verdict": verdict,
        "confidence": confidence,
        "reason": reason,
        "budget": budget,
        "estimated_price": price,
        "next_action": f"先打开证据链接核实 {product} 的实时价格和差评；确认购买时再走人工确认扣款。",
    }


def _build_agent_runs(
    legacy: dict[str, Any],
    context: dict[str, Any],
    decision: dict[str, Any],
    mcp_trace: list[dict[str, Any]],
) -> list[AgentRun]:
    def calls(*names: str) -> list[dict[str, Any]]:
        return [call for call in mcp_trace if call.get("tool") in names]

    return [
        AgentRun(
            "Price Research Agent",
            "负责平台价格搜索、预算区间过滤和价格来源保留。",
            "completed",
            calls("deal.search.evidence"),
            f"整理出 {len(legacy['price_table'])} 条预算相关价格来源。",
        ),
        AgentRun(
            "Risk Evidence Agent",
            "负责从联网搜索摘要中提取差评、避坑和风险证据。",
            "completed",
            calls("deal.search.evidence"),
            f"整理出 {len(legacy['search_sources'])} 条评价/风险来源。",
        ),
        AgentRun(
            "Personal Finance Agent",
            "负责读取账本、余额、历史和放弃购买记录。",
            "completed",
            calls("finance.context.read"),
            f"读取 {context['recent_ledger_count']} 条账本，当前余额 {context['current_surplus']} 元。",
        ),
        AgentRun(
            "Decision Agent",
            "负责融合价格、风险和个人上下文，输出购买建议与人工确认动作。",
            "completed",
            [],
            f"输出结论：{decision['verdict']}，可信度 {decision['confidence']}。",
        ),
    ]


def _report(run_id: str, query: str, product: str, questions: list[ResearchQuestion], evidence: list[EvidenceItem], context: dict[str, Any], decision: dict[str, Any], legacy: dict[str, Any], agent_runs: list[AgentRun]) -> str:
    q_lines = "\n".join(f"- {q.owner}: {q.question}（{q.purpose}）" for q in questions)
    e_lines = "\n".join(
        f"- [{e.category}] {e.title}: {e.summary} 来源：{e.source} {e.url}".strip()
        for e in evidence
    )
    a_lines = "\n".join(f"- {run.agent}: {run.summary}" for run in agent_runs)
    return f"""# Deal Research Report

Run: {run_id}

## 购买意图
{query}

## 研究对象
{product}

## Planner 拆解问题
{q_lines}

## Multi-Agent Orchestration
{a_lines}

## 旧省钱智探复用结果
- 估算价格：{legacy['estimated_price']} 元
- Tavily 搜索来源：{len(legacy['search_sources'])} 条
- 价格渠道来源：{len(legacy['price_table'])} 条
- 搜索补充来源：{len(legacy['crawler_sources'])} 条

## Evidence
{e_lines}

## Personal Context
- 当前余额：{context['current_surplus']} 元
- 最近账本记录：{context['recent_ledger_count']} 条
- 最近 active 支出：{context['recent_active_spend']} 元
- 历史相关记忆：{context['memory_hit_count']} 条

## Decision
- 结论：{decision['verdict']}
- 可信度：{decision['confidence']}
- 预算：{decision['budget'] or '未识别'}
- 估算价格：{decision['estimated_price']} 元
- 原因：{decision['reason']}
- 下一步：{decision['next_action']}

## 省钱智探原始判断
{legacy['display_answer']}
"""


def run_deal_research(query: str) -> dict[str, Any]:
    started = time.perf_counter()
    run_id = f"deal_{uuid4().hex[:10]}"
    steps: list[ResearchStep] = []

    stage = time.perf_counter()
    mcp_trace: list[dict[str, Any]] = []
    questions = _plan_questions("待识别商品")
    steps.append(ResearchStep("planner", "生成价格、风险、替代品、个人预算四类研究问题。", int((time.perf_counter() - stage) * 1000)))

    stage = time.perf_counter()
    search_payload = _mcp_call("deal.search.evidence", {"query": query}, mcp_trace)
    finance_payload = _mcp_call("finance.context.read", {"limit": 20}, mcp_trace)
    original = run_original_pipeline(query)
    budget = _extract_budget(query)
    product = original.get("item") or "待研究商品"
    questions = _plan_questions(product)
    legacy = {
        "display_answer": original.get("display_answer") or "",
        "estimated_price": float(original.get("price") or 0),
        "search_sources": _normalize_search_sources(search_payload.get("info_blocks") or original.get("info_blocks") or []),
        "price_table": _normalize_price_table(search_payload.get("price_table_data") or original.get("price_table_data") or [], budget),
        "crawler_sources": _normalize_crawler_sources(original.get("crawler_results") or []),
        "long_term_context": original.get("long_term_context") or "",
        "memory_hits": original.get("memory_hits") or [],
        "trace": original.get("trace") or {},
    }
    steps.append(
        ResearchStep(
            "legacy_zhitan_pipeline",
            "复用旧省钱智探：Tavily 搜索、平台价格来源、搜索补充来源、记忆召回、LLM 决策和价格解析。",
            int((time.perf_counter() - stage) * 1000),
        )
    )

    stage = time.perf_counter()
    evidence = _evidence_from_legacy(product, legacy)
    context = _personal_context(query, finance_payload)
    decision = _decision(query, product, legacy["estimated_price"], legacy["display_answer"], evidence, context)
    agent_runs = _build_agent_runs(legacy, context, decision, mcp_trace)
    steps.append(ResearchStep("decision_engine", "把外部证据、省钱智探判断和个人账本上下文合并成购买决策。", int((time.perf_counter() - stage) * 1000)))

    stage = time.perf_counter()
    report = _report(run_id, query, product, questions, evidence, context, decision, legacy, agent_runs)
    steps.append(ResearchStep("publisher", "生成可展示的购买研究报告，并保留省钱智探原始判断。", int((time.perf_counter() - stage) * 1000)))

    run = DealResearchRun(
        run_id=run_id,
        query=query,
        product=product,
        status="completed",
        created_at=datetime.now().isoformat(timespec="seconds"),
        questions=questions,
        evidence=evidence,
        steps=steps,
        personal_context=context,
        decision=decision,
        legacy_audit=legacy,
        agent_runs=agent_runs,
        mcp_calls=mcp_trace,
        report=report,
    )
    # Keep total latency visible without changing the stable frontend contract.
    run.steps.append(ResearchStep("total", "完整 Deal Research 运行耗时。", int((time.perf_counter() - started) * 1000)))
    RUNS.insert(0, run)
    del RUNS[20:]
    return asdict(run)


def list_deal_runs() -> list[dict[str, Any]]:
    return [asdict(run) for run in RUNS]
