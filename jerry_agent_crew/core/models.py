from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional
from uuid import uuid4


@dataclass
class AgentStep:
    agent: str
    action: str
    status: str
    summary: str
    detail: Dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


@dataclass
class Artifact:
    title: str
    kind: str
    content: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class CrewTask:
    template_id: str
    title: str
    goal: str
    run_id: str = field(default_factory=lambda: f"run_{uuid4().hex[:10]}")
    status: str = "created"
    created_at: str = field(default_factory=lambda: datetime.now().isoformat(timespec="seconds"))
    steps: List[AgentStep] = field(default_factory=list)
    artifacts: List[Artifact] = field(default_factory=list)
    final_answer: str = ""
    needs_approval: bool = False
    warnings: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class TaskTemplate:
    template_id: str
    name: str
    description: str
    example_goal: str
    output_hint: str


@dataclass(frozen=True)
class SkillSpec:
    name: str
    description: str
    risk_level: str
    requires_confirmation: bool
    input_schema: Dict[str, Any]
    output_schema: Dict[str, Any]


@dataclass
class PriceCandidate:
    product: str
    price_text: str
    source_title: str
    source_url: str
    confidence: str
    snippet: str = ""


@dataclass
class LedgerSummary:
    total_spend: float
    current_surplus: Optional[float]
    recent_items: List[str]
    note: str

