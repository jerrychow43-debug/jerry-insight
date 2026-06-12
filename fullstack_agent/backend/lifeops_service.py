from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

from db import find_memory_context, get_current_surplus, list_history, list_ledger


@dataclass
class RunbookStep:
    name: str
    description: str
    toolset: List[str]


@dataclass
class ToolCall:
    tool: str
    status: str
    summary: str
    output: Dict[str, Any] = field(default_factory=dict)
    latency_ms: int = 0


@dataclass
class MemoryLayer:
    name: str
    role: str
    items: List[Dict[str, Any]]


@dataclass
class SafetyDecision:
    level: str
    requires_human: bool
    reason: str
    blocked_actions: List[str] = field(default_factory=list)


@dataclass
class LifeOpsRun:
    run_id: str
    event_type: str
    title: str
    goal: str
    status: str
    created_at: str
    runbook: List[RunbookStep]
    memory: List[MemoryLayer]
    tool_calls: List[ToolCall]
    safety: SafetyDecision
    report: str
    artifacts: List[Dict[str, Any]]


RUNS: List[LifeOpsRun] = []


EVENT_TYPES = [
    {
        "id": "budget_anomaly",
        "name": "消费异常事件",
        "description": "检测预算、冲动消费、订阅和异常支出，按 runbook 给出处置建议。",
        "example": "最近我感觉外卖和饮料花太多了，帮我查一下哪里异常。",
    },
    {
        "id": "procurement_decision",
        "name": "采购决策事件",
        "description": "把一次购买变成调研事件：查预算、查候选价格、生成观察清单。",
        "example": "我想买一个 1000 元以内适合写代码的显示器。",
    },
    {
        "id": "interview_countdown",
        "name": "面试冲刺事件",
        "description": "读取项目和面试笔记，生成冲刺计划、追问清单和项目讲法。",
        "example": "我三天后面 Agent 岗，帮我做冲刺计划。",
    },
    {
        "id": "learning_delay",
        "name": "学习延期事件",
        "description": "检查学习资料和当前薄弱点，重新规划可执行学习任务。",
        "example": "Linux 网络和 C++ 笔记还没复习完，帮我重新安排。",
    },
]


TOOLSETS = [
    {
        "name": "finance_toolset",
        "tools": ["ledger_query", "budget_status", "price_memory_lookup"],
        "inspiration": "HolmesGPT toolset: data sources are explicit and independently switchable.",
    },
    {
        "name": "research_toolset",
        "tools": ["search_candidates", "read_local_notes", "source_rank"],
        "inspiration": "GPT-Researcher planner/executor: collect evidence before writing report.",
    },
    {
        "name": "memory_toolset",
        "tools": ["core_memory_read", "recall_memory_search", "archival_memory_read"],
        "inspiration": "Letta/MemGPT: core, recall and archival memory are separate layers.",
    },
    {
        "name": "ops_toolset",
        "tools": ["report_publish", "approval_queue", "dingtalk_dry_run"],
        "inspiration": "AIOps runbook: separate advice, automation and human confirmation.",
    },
]


RUNBOOKS: Dict[str, List[RunbookStep]] = {
    "budget_anomaly": [
        RunbookStep("classify_event", "确认这是消费异常，而不是普通聊天。", ["memory_toolset"]),
        RunbookStep("collect_finance_context", "读取账本、余额、历史消费和近期咨询。", ["finance_toolset"]),
        RunbookStep("diagnose_pattern", "找出高频消费、异常类别和可节省点。", ["finance_toolset"]),
        RunbookStep("safety_gate", "涉及扣款/删除/通知时进入人工确认。", ["ops_toolset"]),
        RunbookStep("publish_report", "输出处置报告和下一步动作。", ["ops_toolset"]),
    ],
    "procurement_decision": [
        RunbookStep("classify_event", "确认采购目标、预算和约束。", ["memory_toolset"]),
        RunbookStep("collect_context", "读取预算、历史购买和相关偏好。", ["finance_toolset"]),
        RunbookStep("research_candidates", "搜索公开候选价格和来源链接。", ["research_toolset"]),
        RunbookStep("safety_gate", "禁止自动购买，只允许生成观察清单。", ["ops_toolset"]),
        RunbookStep("publish_report", "输出采购建议、观察清单和人工确认项。", ["ops_toolset"]),
    ],
    "interview_countdown": [
        RunbookStep("classify_event", "确认目标岗位和倒计时。", ["memory_toolset"]),
        RunbookStep("read_project_context", "读取项目 README、面试笔记和历史问答。", ["research_toolset"]),
        RunbookStep("plan_sprint", "生成三天冲刺计划和模拟追问。", ["research_toolset"]),
        RunbookStep("safety_gate", "不自动投递简历/发送邮件，只产出材料。", ["ops_toolset"]),
        RunbookStep("publish_report", "输出面试冲刺包。", ["ops_toolset"]),
    ],
    "learning_delay": [
        RunbookStep("classify_event", "确认延期主题和可用时间。", ["memory_toolset"]),
        RunbookStep("read_learning_notes", "读取本地学习笔记和历史薄弱点。", ["research_toolset"]),
        RunbookStep("replan_tasks", "拆成今天/本周可执行学习任务。", ["research_toolset"]),
        RunbookStep("safety_gate", "只生成计划，不自动改外部日历。", ["ops_toolset"]),
        RunbookStep("publish_report", "输出复习计划和复习卡片。", ["ops_toolset"]),
    ],
}


def list_specs() -> Dict[str, Any]:
    return {"event_types": EVENT_TYPES, "toolsets": TOOLSETS, "runbooks": {k: [asdict(s) for s in v] for k, v in RUNBOOKS.items()}}


def _core_memory(goal: str) -> MemoryLayer:
    return MemoryLayer(
        name="core_memory",
        role="常驻上下文：用户长期画像、当前目标和安全偏好。",
        items=[
            {"key": "user", "value": "Jerry"},
            {"key": "current_surplus", "value": get_current_surplus()},
            {"key": "safety_policy", "value": "不自动删除、不自动购买、不自动发送外部消息；高风险动作先进 approval。"},
            {"key": "current_goal", "value": goal},
        ],
    )


def _recall_memory(goal: str) -> MemoryLayer:
    return MemoryLayer(
        name="recall_memory",
        role="可搜索历史：聊天、账本和过去任务记录。",
        items=find_memory_context(goal, limit=5),
    )


def _archival_memory(event_type: str) -> MemoryLayer:
    hints = {
        "budget_anomaly": ["README.md", "jerry_ledger", "历史消费记录"],
        "procurement_decision": ["省钱智探搜索逻辑", "价格候选来源", "观察清单"],
        "interview_countdown": ["interview_agent_prep.md", "ai_native_agent_interview_prep.md", "README.md"],
        "learning_delay": ["linux_network_interview_notepad.md", "linux_cpp_course_notes", "学习笔记"],
    }
    return MemoryLayer(
        name="archival_memory",
        role="长期资料：通过工具访问的项目文件、笔记和领域资料。",
        items=[{"resource": item, "access": "tool_call"} for item in hints.get(event_type, ["README.md"])],
    )


def _call_tool(tool: str, event_type: str, goal: str) -> ToolCall:
    started = time.perf_counter()
    output: Dict[str, Any] = {}
    summary = ""

    if tool == "ledger_query":
        rows = list_ledger(limit=12)
        output = {"recent_ledger": rows}
        summary = f"读取最近 {len(rows)} 条账本记录。"
    elif tool == "budget_status":
        output = {"current_surplus": get_current_surplus()}
        summary = f"当前余额/预算上下文：{output['current_surplus']} 元。"
    elif tool == "price_memory_lookup":
        hits = find_memory_context(goal, limit=3)
        output = {"price_memory_hits": hits}
        summary = f"检索到 {len(hits)} 条相关历史记忆。"
    elif tool == "search_candidates":
        output = {"query": goal, "mode": "search_api_or_mock", "tavily_configured": bool(os.getenv("TAVILY_API_KEY"))}
        summary = "已准备搜索候选来源；未配置搜索 Key 时走 mock evidence。"
    elif tool == "read_local_notes":
        output = {"notes": _read_note_index(event_type)}
        summary = f"读取到 {len(output['notes'])} 个本地资料入口。"
    elif tool == "source_rank":
        output = {"ranking_rule": "prefer official docs, project README, recent notes, explicit source links"}
        summary = "已生成来源排序规则。"
    elif tool == "core_memory_read":
        output = {"layer": "core_memory"}
        summary = "读取常驻记忆。"
    elif tool == "recall_memory_search":
        output = {"hits": find_memory_context(goal, limit=3)}
        summary = "搜索历史对话/账本。"
    elif tool == "archival_memory_read":
        output = {"resources": _read_note_index(event_type)}
        summary = "读取长期资料索引。"
    elif tool == "report_publish":
        output = {"artifact": "markdown_report"}
        summary = "生成 Markdown 处置报告。"
    elif tool == "approval_queue":
        output = {"queued": _requires_approval(event_type, goal)}
        summary = "检查是否需要人工确认。"
    elif tool == "dingtalk_dry_run":
        output = {"dry_run": True}
        summary = "钉钉通知仅生成草稿，不自动发送。"
    else:
        output = {"message": "unknown tool"}
        summary = "未知工具，已跳过。"

    return ToolCall(
        tool=tool,
        status="success",
        summary=summary,
        output=output,
        latency_ms=int((time.perf_counter() - started) * 1000),
    )


def _read_note_index(event_type: str) -> List[Dict[str, str]]:
    base = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    targets = {
        "interview_countdown": ["interview_agent_prep.md", "ai_native_agent_interview_prep.md", "README.md"],
        "learning_delay": ["linux_network_interview_notepad.md", "linux_command_abbreviations_cheatsheet.md", "README.md"],
        "procurement_decision": ["README.md"],
        "budget_anomaly": ["README.md"],
    }.get(event_type, ["README.md"])
    notes: List[Dict[str, str]] = []
    for rel in targets:
        path = os.path.join(base, rel)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                text = f.read(420)
        except OSError:
            continue
        notes.append({"path": rel, "snippet": text})
    return notes


def _requires_approval(event_type: str, goal: str) -> bool:
    risky_words = ["记账", "扣", "删除", "发送", "通知", "购买", "下单", "撤销"]
    return event_type in {"budget_anomaly", "procurement_decision"} and any(word in goal for word in risky_words)


def _safety(event_type: str, goal: str) -> SafetyDecision:
    if _requires_approval(event_type, goal):
        return SafetyDecision(
            level="medium",
            requires_human=True,
            reason="检测到可能涉及账本写入、通知、购买或撤销；当前只生成确认项，不自动执行。",
            blocked_actions=["auto_purchase", "auto_delete", "auto_notify", "auto_ledger_write"],
        )
    return SafetyDecision(level="low", requires_human=False, reason="本次只读数据并生成报告，没有外部副作用。")


def _report(event_type: str, goal: str, memory: List[MemoryLayer], tool_calls: List[ToolCall], safety: SafetyDecision) -> str:
    titles = {
        "budget_anomaly": "消费异常处置报告",
        "procurement_decision": "采购决策 runbook 报告",
        "interview_countdown": "面试冲刺 runbook 报告",
        "learning_delay": "学习延期处置报告",
    }
    tool_lines = "\n".join(f"- {call.tool}: {call.summary}" for call in tool_calls)
    memory_lines = "\n".join(f"- {layer.name}: {len(layer.items)} items，{layer.role}" for layer in memory)
    return f"""# {titles.get(event_type, "LifeOps 处置报告")}

## 事件目标
{goal}

## Memory Layers
{memory_lines}

## Tool Calls
{tool_lines}

## Safety Gate
- 风险等级：{safety.level}
- 需要人工确认：{"是" if safety.requires_human else "否"}
- 原因：{safety.reason}

## 下一步
1. 先人工查看报告和来源。
2. 如果涉及记账、通知、删除、购买，下发到 Approval Queue。
3. 如果只是学习/面试资料，直接进入执行计划。
"""


def run_lifeops(event_type: str, goal: str) -> LifeOpsRun:
    if event_type not in RUNBOOKS:
        event_type = "budget_anomaly"
    runbook = RUNBOOKS[event_type]
    memory = [_core_memory(goal), _recall_memory(goal), _archival_memory(event_type)]

    tool_calls: List[ToolCall] = []
    for step in runbook:
        for toolset in step.toolset:
            spec = next((item for item in TOOLSETS if item["name"] == toolset), None)
            if not spec:
                continue
            for tool in spec["tools"]:
                tool_calls.append(_call_tool(tool, event_type, goal))

    safety = _safety(event_type, goal)
    report = _report(event_type, goal, memory, tool_calls, safety)
    run = LifeOpsRun(
        run_id=f"lifeops_{uuid4().hex[:10]}",
        event_type=event_type,
        title=next((item["name"] for item in EVENT_TYPES if item["id"] == event_type), event_type),
        goal=goal,
        status="needs_approval" if safety.requires_human else "completed",
        created_at=datetime.now().isoformat(timespec="seconds"),
        runbook=runbook,
        memory=memory,
        tool_calls=tool_calls,
        safety=safety,
        report=report,
        artifacts=[
            {"kind": "markdown", "title": "处置报告", "content": report},
            {"kind": "json", "title": "tool_trace", "content": [asdict(call) for call in tool_calls]},
        ],
    )
    RUNS.insert(0, run)
    del RUNS[20:]
    return run


def list_runs() -> List[Dict[str, Any]]:
    return [asdict(run) for run in RUNS]

