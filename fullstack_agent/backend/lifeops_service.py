from __future__ import annotations

import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List
from uuid import uuid4

from db import find_memory_context


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
class StepResult:
    step: str
    description: str
    tool_calls: List[ToolCall]
    finding: str


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
class RunSummary:
    status_label: str
    confidence: str
    conclusion: str
    recommended_action: str
    evidence_count: int


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
    summary: RunSummary
    step_results: List[StepResult]
    tool_calls: List[ToolCall]
    safety: SafetyDecision
    report: str
    sections: Dict[str, Any]
    artifacts: List[Dict[str, Any]]


RUNS: List[LifeOpsRun] = []


PROJECT_PROFILES: Dict[str, Dict[str, Any]] = {
    "aider": {
        "name": "Aider",
        "tagline": "AI Coding agent with repo map.",
        "core_mechanism": "repo map：用 tree-sitter 解析仓库符号，再用图算法挑出和任务最相关的代码上下文。",
        "what_to_learn": [
            "不要把整个仓库塞给模型，先做上下文筛选。",
            "把代码符号、文件关系和任务相关性显式建模。",
            "Git 自动提交/回滚可以作为 agent undo 机制。",
        ],
        "fit_for_jerry": "可以借鉴为“项目资料 map”：自动扫描 README、后端、前端、笔记，选出面试回答最相关的材料。",
        "implementation_targets": [
            "新增 ProjectMap 页面：展示 README、backend、frontend、notes 的关系图。",
            "新增 context_selector 工具：根据研究目标只选相关文件片段。",
            "在面试材料生成前，先输出“本次引用了哪些项目文件”。",
        ],
        "questions": [
            "repo map 为什么比直接全文塞给模型好？",
            "如何判断哪些文件和当前任务相关？",
            "自动 commit / undo 在 agent 系统里解决什么问题？",
        ],
    },
    "gpt_researcher": {
        "name": "GPT-Researcher",
        "tagline": "Planner / executor / publisher style research agent.",
        "core_mechanism": "planner 拆研究问题，execution agents 收集资料，publisher 聚合为带引用的报告。",
        "what_to_learn": [
            "复杂问题不要直接回答，先拆成子问题。",
            "收集资料和写报告要分离。",
            "报告质量要看 citation、覆盖面、冲突信息处理和失败 fallback。",
        ],
        "fit_for_jerry": "可以借鉴为“Agent 项目研究 runbook”：先拆解开源项目，再提炼可借鉴机制，最后生成面试材料。",
        "implementation_targets": [
            "把研究流程拆成 Planner、Collector、Publisher 三段。",
            "报告里增加 evidence/source 区域，说明每个结论来自哪里。",
            "增加“研究问题清单”，先拆问题再生成最终材料。",
        ],
        "questions": [
            "planner 和 executor 为什么要分开？",
            "如何避免搜索结果堆砌成低质量报告？",
            "引用质量如何评估？",
        ],
    },
    "holmesgpt": {
        "name": "HolmesGPT",
        "tagline": "AIOps ReAct agent with toolsets and runbooks.",
        "core_mechanism": "按 runbook 查询 Prometheus、Loki、Grafana、PagerDuty 等 toolset，并通过权限层控制生产风险。",
        "what_to_learn": [
            "工具按 toolset 管理，每个数据源可以独立开关。",
            "runbook 用自然语言描述 SOP，agent 按步骤执行。",
            "安全不是靠 prompt，而是在权限层不给危险能力。",
        ],
        "fit_for_jerry": "可以借鉴为“面试/项目复盘 runbook”：不同研究对象走不同 SOP，危险动作只生成草稿。",
        "implementation_targets": [
            "把不同研究对象做成 runbook，而不是一段 prompt。",
            "把工具分成 project_profile、local_context、report 三组 toolset。",
            "所有会改代码/提交/部署的动作只进入 approval，不自动执行。",
        ],
        "questions": [
            "runbook 和普通 prompt 有什么区别？",
            "为什么安全边界要放在权限层？",
            "什么时候自动处理，什么时候必须人工介入？",
        ],
    },
    "letta": {
        "name": "Letta / MemGPT",
        "tagline": "Agent runtime centered around memory architecture.",
        "core_mechanism": "三层 memory：core memory 常驻，recall memory 检索历史，archival memory 通过 tool call 访问长期资料。",
        "what_to_learn": [
            "记忆不是简单聊天历史，而是分层管理。",
            "agent 要能决定什么时候写入、召回、清理记忆。",
            "长期资料应该通过工具访问，而不是常驻上下文。",
        ],
        "fit_for_jerry": "可以借鉴为“面试准备记忆”：常驻目标岗位和项目定位，召回答不顺的问题，归档开源项目资料。",
        "implementation_targets": [
            "新增 Memory 面板：core memory 放目标岗位和项目定位。",
            "recall memory 记录面试追问和答不顺的问题。",
            "archival memory 归档开源项目资料和 README 片段。",
        ],
        "questions": [
            "core / recall / archival memory 分别放什么？",
            "如何避免旧记忆污染当前回答？",
            "什么时候应该写记忆，什么时候不应该写？",
        ],
    },
}


EVENT_TYPES = [
    {
        "id": "gpt_researcher",
        "name": "GPT-Researcher",
        "description": "研究 planner / executor / publisher，以及 citation 和报告质量。",
        "example": "研究 GPT-Researcher 的核心机制，看看哪些点能借鉴到我的项目里。",
    },
    {
        "id": "letta",
        "name": "Letta / MemGPT",
        "description": "研究三层 memory architecture：core、recall、archival。",
        "example": "研究 Letta 的记忆系统，看看怎么用于我的面试准备和项目复盘。",
    },
    {
        "id": "holmesgpt",
        "name": "HolmesGPT",
        "description": "研究 AIOps agent 的 runbook、toolset、权限安全和 fallback。",
        "example": "研究 HolmesGPT 的 runbook 和 toolset 设计，看看我的项目能怎么借鉴。",
    },
    {
        "id": "aider",
        "name": "Aider",
        "description": "研究 repo map、代码上下文筛选和 Git undo 机制。",
        "example": "研究 Aider 的 repo map，看看能不能做我的项目资料 map。",
    },
]


TOOLSETS = [
    {
        "name": "project_profile_toolset",
        "tools": ["load_project_profile", "extract_core_mechanism"],
        "inspiration": "把开源项目的核心机制结构化，而不是泛泛总结。",
    },
    {
        "name": "local_context_toolset",
        "tools": ["read_my_project_context", "search_recall_memory"],
        "inspiration": "把可借鉴点映射到 Jerry 自己的项目和面试目标。",
    },
    {
        "name": "adaptation_toolset",
        "tools": ["map_borrowable_points", "generate_interview_questions"],
        "inspiration": "不硬写二改方案，重点输出可借鉴机制和追问。",
    },
    {
        "name": "report_toolset",
        "tools": ["publish_research_report", "safety_check"],
        "inspiration": "输出可读报告，并避免泄露密钥或自动修改项目。",
    },
]


RUNBOOKS: Dict[str, List[RunbookStep]] = {
    project_id: [
        RunbookStep("load_profile", "读取开源项目的定位、核心机制和典型追问。", ["project_profile_toolset"]),
        RunbookStep("read_my_context", "读取我的项目/笔记上下文，找到可以映射的地方。", ["local_context_toolset"]),
        RunbookStep("extract_borrowable_points", "提取可借鉴点，避免写成生硬二改方案。", ["adaptation_toolset"]),
        RunbookStep("publish_report", "生成研究报告、面试追问和结合建议。", ["report_toolset"]),
    ]
    for project_id in PROJECT_PROFILES
}


def list_specs() -> Dict[str, Any]:
    return {
        "event_types": EVENT_TYPES,
        "toolsets": TOOLSETS,
        "runbooks": {key: [asdict(step) for step in steps] for key, steps in RUNBOOKS.items()},
    }


def _profile(event_type: str) -> Dict[str, Any]:
    return PROJECT_PROFILES.get(event_type, PROJECT_PROFILES["gpt_researcher"])


def _core_memory(goal: str) -> MemoryLayer:
    return MemoryLayer(
        name="core_memory",
        role="常驻上下文：Jerry 的当前目标、项目定位和面试准备方向。",
        items=[
            {"key": "goal", "value": "准备 Agent 岗面试，做出能讲清楚机制的项目"},
            {"key": "current_project", "value": "Jerry-Insight / 省钱智探 + Vue/FastAPI fullstack"},
            {"key": "research_goal", "value": goal},
        ],
    )


def _recall_memory(goal: str) -> MemoryLayer:
    return MemoryLayer(
        name="recall_memory",
        role="可搜索历史：之前问过的问题、账本/项目记录和面试准备对话。",
        items=find_memory_context(goal, limit=5),
    )


def _archival_memory(event_type: str) -> MemoryLayer:
    resources = {
        "gpt_researcher": ["博主截图：GPT-Researcher planner/executor/publisher", "interview_agent_prep.md", "README.md"],
        "letta": ["博主截图：Letta 三层 memory", "ai_native_agent_interview_prep.md", "README.md"],
        "holmesgpt": ["博主截图：HolmesGPT runbook/toolset/RBAC", "fullstack_agent/backend/lifeops_service.py", "README.md"],
        "aider": ["博主截图：Aider repo map", "fullstack_agent/backend", "fullstack_agent/frontend"],
    }
    return MemoryLayer(
        name="archival_memory",
        role="长期资料：截图、README、项目文件、面试笔记等，通过工具访问。",
        items=[{"resource": item, "access": "tool_call"} for item in resources.get(event_type, [])],
    )


def _call_tool(tool: str, event_type: str, goal: str) -> ToolCall:
    started = time.perf_counter()
    profile = _profile(event_type)
    output: Dict[str, Any] = {}

    if tool == "load_project_profile":
        output = {"project": profile["name"], "tagline": profile["tagline"]}
        summary = f"读取 {profile['name']} 的项目定位。"
    elif tool == "extract_core_mechanism":
        output = {"core_mechanism": profile["core_mechanism"]}
        summary = f"提取核心机制：{profile['core_mechanism']}"
    elif tool == "read_my_project_context":
        output = {"contexts": _read_my_context(event_type)}
        summary = f"读取到 {len(output['contexts'])} 个我的项目/笔记上下文。"
    elif tool == "search_recall_memory":
        hits = find_memory_context(goal, limit=4)
        output = {"hits": hits}
        summary = f"召回 {len(hits)} 条历史相关记忆。"
    elif tool == "map_borrowable_points":
        output = {"borrowable_points": profile["what_to_learn"], "fit_for_jerry": profile["fit_for_jerry"]}
        summary = "已把开源项目特点映射到我的项目可借鉴点。"
    elif tool == "generate_interview_questions":
        output = {"questions": profile["questions"]}
        summary = f"生成 {len(profile['questions'])} 个面试追问。"
    elif tool == "publish_research_report":
        output = {"artifact": "agent_project_research_report"}
        summary = "生成 Agent 项目研究报告。"
    elif tool == "safety_check":
        output = {"safe": True, "policy": "只读资料和生成建议，不自动改代码、不提交、不泄露密钥。"}
        summary = "完成安全检查：本次没有外部副作用。"
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


def _read_my_context(event_type: str) -> List[Dict[str, str]]:
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
    targets = ["README.md", "fullstack_agent/backend/README.md", "interview_agent_prep.md"]
    if event_type == "aider":
        targets.extend(["fullstack_agent/backend/main.py", "fullstack_agent/frontend/src/App.vue"])
    if event_type == "holmesgpt":
        targets.append("fullstack_agent/backend/lifeops_service.py")
    contexts: List[Dict[str, str]] = []
    for rel in targets:
        path = os.path.join(root, rel)
        if not os.path.exists(path):
            continue
        try:
            with open(path, "r", encoding="utf-8", errors="ignore") as file:
                snippet = file.read(500)
        except OSError:
            continue
        contexts.append({"path": rel, "snippet": snippet})
    return contexts


def _finding_for_step(step: RunbookStep, calls: List[ToolCall]) -> str:
    if any(call.tool == "extract_core_mechanism" for call in calls):
        return "已定位该开源项目最值得学习的核心机制。"
    if any(call.tool == "read_my_project_context" for call in calls):
        return "已读取我的项目上下文，用于判断能借鉴到哪里。"
    if any(call.tool == "map_borrowable_points" for call in calls):
        return "已提取可借鉴点，并映射到我的项目。"
    if any(call.tool == "publish_research_report" for call in calls):
        return "已生成研究报告和面试追问。"
    return "本步骤执行完成。"


def _safety() -> SafetyDecision:
    return SafetyDecision(
        level="low",
        requires_human=False,
        reason="本系统只读取资料、生成研究报告和建议，不自动修改代码、不提交、不泄露密钥。",
        blocked_actions=["auto_commit", "secret_exposure", "auto_deploy"],
    )


def _summary(event_type: str, memory: List[MemoryLayer]) -> RunSummary:
    profile = _profile(event_type)
    evidence_count = sum(len(layer.items) for layer in memory)
    return RunSummary(
        status_label="已完成研究",
        confidence="medium" if evidence_count else "low",
        conclusion=f"{profile['name']} 最值得借鉴的是：{profile['core_mechanism']}",
        recommended_action=f"把它转化为我的项目里的机制：{profile['fit_for_jerry']}",
        evidence_count=evidence_count,
    )


def _report(event_type: str, goal: str, memory: List[MemoryLayer], step_results: List[StepResult], safety: SafetyDecision, summary: RunSummary) -> str:
    profile = _profile(event_type)
    borrow_lines = "\n".join(f"- {item}" for item in profile["what_to_learn"])
    question_lines = "\n".join(f"- {item}" for item in profile["questions"])
    memory_lines = "\n".join(f"- {layer.name}: {len(layer.items)} items，{layer.role}" for layer in memory)
    step_lines = []
    for step in step_results:
        tools = ", ".join(call.tool for call in step.tool_calls)
        step_lines.append(f"- {step.step}: {step.finding}（tools: {tools}）")
    return f"""# {profile['name']} 研究报告

## 研究目标
{goal}

## 核心机制
{profile['core_mechanism']}

## 最值得借鉴的点
{borrow_lines}

## 怎么结合到我的项目
{profile['fit_for_jerry']}

## 面试可能追问
{question_lines}

## Memory Evidence
{memory_lines}

## Runbook Trace
{chr(10).join(step_lines)}

## Safety
- 风险等级：{safety.level}
- 原因：{safety.reason}

## 一句话讲法
我不是直接复刻 {profile['name']}，而是研究它的核心机制：{profile['core_mechanism']}，再把这个机制抽象出来，结合到我的 Jerry-Insight 项目里。
"""


def _sections(event_type: str) -> Dict[str, Any]:
    profile = _profile(event_type)
    mechanism = profile["core_mechanism"].rstrip("。.")
    return {
        "project_name": profile["name"],
        "one_liner": profile["tagline"],
        "core_mechanism": profile["core_mechanism"],
        "borrowable_points": profile["what_to_learn"],
        "fit_for_jerry": profile["fit_for_jerry"],
        "implementation_targets": profile["implementation_targets"],
        "interview_questions": profile["questions"],
        "plain_summary": (
            f"{profile['name']} 值得看的不是表面功能，而是它背后的机制："
            f"{mechanism}。我可以把这个机制抽出来，用在自己的 Jerry-Insight 项目里。"
        ),
    }


def run_lifeops(event_type: str, goal: str) -> LifeOpsRun:
    if event_type not in RUNBOOKS:
        event_type = "gpt_researcher"
    runbook = RUNBOOKS[event_type]
    memory = [_core_memory(goal), _recall_memory(goal), _archival_memory(event_type)]

    all_tool_calls: List[ToolCall] = []
    step_results: List[StepResult] = []
    for step in runbook:
        tools: List[str] = []
        for toolset in step.toolset:
            spec = next((item for item in TOOLSETS if item["name"] == toolset), None)
            if spec:
                tools.extend(spec["tools"])
        calls = [_call_tool(tool, event_type, goal) for tool in tools]
        all_tool_calls.extend(calls)
        step_results.append(
            StepResult(
                step=step.name,
                description=step.description,
                tool_calls=calls,
                finding=_finding_for_step(step, calls),
            )
        )

    safety = _safety()
    summary = _summary(event_type, memory)
    report = _report(event_type, goal, memory, step_results, safety, summary)
    profile = _profile(event_type)
    run = LifeOpsRun(
        run_id=f"agentforge_{uuid4().hex[:10]}",
        event_type=event_type,
        title=f"{profile['name']} 研究",
        goal=goal,
        status="completed",
        created_at=datetime.now().isoformat(timespec="seconds"),
        runbook=runbook,
        memory=memory,
        summary=summary,
        step_results=step_results,
        tool_calls=all_tool_calls,
        safety=safety,
        report=report,
        sections=_sections(event_type),
        artifacts=[
            {"kind": "markdown", "title": f"{profile['name']} 研究报告", "content": report},
            {"kind": "json", "title": "research_trace", "content": [asdict(call) for call in all_tool_calls]},
        ],
    )
    RUNS.insert(0, run)
    del RUNS[20:]
    return run


def list_runs() -> List[Dict[str, Any]]:
    return [asdict(run) for run in RUNS]
