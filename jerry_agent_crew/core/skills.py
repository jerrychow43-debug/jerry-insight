from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List

from .models import LedgerSummary, PriceCandidate, SkillSpec


WORKSPACE_ROOT = Path(__file__).resolve().parents[2]
LEDGER_FILE = WORKSPACE_ROOT / "jerry_ledger.json"
PROFILE_FILE = WORKSPACE_ROOT / "jerry_profile.json"


SKILLS: Dict[str, SkillSpec] = {
    "web_price_search": SkillSpec(
        name="web_price_search",
        description="Use a search API to collect public price candidates and source links. Replaces hard crawling.",
        risk_level="low",
        requires_confirmation=False,
        input_schema={"type": "object", "required": ["query"], "properties": {"query": {"type": "string"}}},
        output_schema={"type": "array", "items": {"type": "object"}},
    ),
    "ledger_summary": SkillSpec(
        name="ledger_summary",
        description="Read local ledger/profile files and summarize recent spending.",
        risk_level="low",
        requires_confirmation=False,
        input_schema={"type": "object", "properties": {}},
        output_schema={"type": "object"},
    ),
    "report_artifact": SkillSpec(
        name="report_artifact",
        description="Create a structured markdown report artifact.",
        risk_level="low",
        requires_confirmation=False,
        input_schema={"type": "object", "required": ["title", "content"], "properties": {"title": {"type": "string"}, "content": {"type": "string"}}},
        output_schema={"type": "object"},
    ),
    "ledger_write_plan": SkillSpec(
        name="ledger_write_plan",
        description="Prepare a ledger write action. The MVP does not write automatically; it creates an approval item.",
        risk_level="medium",
        requires_confirmation=True,
        input_schema={"type": "object", "required": ["item", "amount"], "properties": {"item": {"type": "string"}, "amount": {"type": "number"}}},
        output_schema={"type": "object"},
    ),
}


def list_skills() -> List[SkillSpec]:
    return list(SKILLS.values())


def _safe_load_json(path: Path, default: Any) -> Any:
    try:
        if path.exists():
            return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default
    return default


def summarize_ledger() -> LedgerSummary:
    profile = _safe_load_json(PROFILE_FILE, {})
    ledger = _safe_load_json(LEDGER_FILE, [])

    total = 0.0
    recent_items: List[str] = []
    if isinstance(ledger, list):
        for row in ledger[-20:]:
            if not isinstance(row, dict):
                continue
            amount = row.get("amount") or row.get("金额") or row.get("price") or 0
            try:
                total += float(amount)
            except (TypeError, ValueError):
                pass
            item = row.get("item") or row.get("item_name") or row.get("商品") or row.get("name")
            if item:
                recent_items.append(str(item))

    current_surplus = profile.get("current_surplus") if isinstance(profile, dict) else None
    try:
        current_surplus = float(current_surplus) if current_surplus is not None else None
    except (TypeError, ValueError):
        current_surplus = None

    if not ledger:
        note = "未发现旧账本文件，当前使用空账本摘要。"
    else:
        note = f"读取到 {len(ledger)} 条账本记录，已汇总最近 20 条。"

    return LedgerSummary(
        total_spend=round(total, 2),
        current_surplus=current_surplus,
        recent_items=recent_items[-8:],
        note=note,
    )


PRICE_PATTERN = re.compile(r"(?:¥|￥|RMB\s*)?\s*(\d+(?:\.\d{1,2})?)\s*(?:元|块|rmb|RMB|CNY)?")


def _extract_price_text(text: str) -> str:
    matches = PRICE_PATTERN.findall(text or "")
    prices = []
    for match in matches:
        try:
            value = float(match)
        except ValueError:
            continue
        if 0.5 <= value <= 50000:
            prices.append(value)
    if not prices:
        return "未稳定抽取到价格"
    unique = sorted(set(prices))[:3]
    return " / ".join(f"{price:g} 元" for price in unique)


def search_price_candidates(query: str, max_results: int = 5) -> List[PriceCandidate]:
    """Search-based price intelligence.

    This intentionally avoids direct crawling. If Tavily is configured, it only uses
    public search result title/snippet/url and marks extracted prices as candidates.
    """
    tavily_key = os.getenv("TAVILY_API_KEY")
    if not tavily_key:
        return [
            PriceCandidate(
                product=query,
                price_text="未配置 TAVILY_API_KEY，暂未联网搜索",
                source_title="Search API not configured",
                source_url="",
                confidence="low",
                snippet="配置 TAVILY_API_KEY 后，本模块会用搜索结果摘要提取候选价格，不再硬爬电商页面。",
            )
        ]

    try:
        from tavily import TavilyClient
    except Exception:
        return [
            PriceCandidate(
                product=query,
                price_text="当前环境未安装 tavily 包",
                source_title="Missing tavily package",
                source_url="",
                confidence="low",
                snippet="可先 pip install tavily-python，或复用主项目 requirements。",
            )
        ]

    client = TavilyClient(api_key=tavily_key)
    search_query = f"{query} 价格 官方 渠道 值得买 参考价"
    try:
        response = client.search(query=search_query, search_depth="basic", max_results=max_results)
    except Exception as exc:
        return [
            PriceCandidate(
                product=query,
                price_text="搜索失败",
                source_title="Search error",
                source_url="",
                confidence="low",
                snippet=str(exc),
            )
        ]

    candidates: List[PriceCandidate] = []
    for item in response.get("results", []):
        title = item.get("title") or "未命名来源"
        snippet = item.get("content") or ""
        url = item.get("url") or ""
        price_text = _extract_price_text(f"{title}\n{snippet}")
        confidence = "medium" if price_text != "未稳定抽取到价格" else "low"
        candidates.append(
            PriceCandidate(
                product=query,
                price_text=price_text,
                source_title=title,
                source_url=url,
                confidence=confidence,
                snippet=snippet[:240],
            )
        )
    return candidates or [
        PriceCandidate(
            product=query,
            price_text="未找到候选价格",
            source_title="No result",
            source_url="",
            confidence="low",
            snippet="搜索 API 没有返回可用结果。",
        )
    ]


def read_local_knowledge(goal: str, limit: int = 6) -> List[Dict[str, str]]:
    keywords = []
    for token in ["agent", "面试", "mcp", "openclaw", "dify", "coze", "linux", "c++", "网络", "省钱"]:
        if token.lower() in goal.lower():
            keywords.append(token)

    candidates = [
        "README.md",
        "interview_agent_prep.md",
        "ai_native_agent_interview_prep.md",
        "linux_network_interview_notepad.md",
        "linux_command_abbreviations_cheatsheet.md",
    ]
    notes: List[Dict[str, str]] = []
    for rel in candidates:
        path = WORKSPACE_ROOT / rel
        if not path.exists():
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if keywords and not any(k.lower() in text.lower() or k.lower() in rel.lower() for k in keywords):
            continue
        snippet = text[:700].replace("\n\n", "\n")
        notes.append({"path": rel, "snippet": snippet})
        if len(notes) >= limit:
            break
    return notes

