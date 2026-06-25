from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any
from uuid import uuid4

from mcp_gateway import mcp_gateway


@dataclass
class ProjectProfile:
    project_id: str
    name: str
    project_path: str
    created_at: str
    project_map: dict[str, Any]
    mcp_calls: list[dict[str, Any]] = field(default_factory=list)


PROJECTS: dict[str, ProjectProfile] = {}
INCIDENT_RUNS: list[dict[str, Any]] = []


def _mcp_call(tool: str, arguments: dict[str, Any], trace: list[dict[str, Any]]) -> dict[str, Any]:
    result = mcp_gateway.call_tool(tool, arguments)
    trace.append({"tool": tool, "arguments": arguments, "result": result})
    return result.get("structuredContent") or {}


def _calls(trace: list[dict[str, Any]], *names: str) -> list[dict[str, Any]]:
    return [call for call in trace if call.get("tool") in names]


def import_project(name: str, project_path: str) -> dict[str, Any]:
    trace: list[dict[str, Any]] = []
    project_map = _mcp_call("project.scan", {"project_path": project_path}, trace)
    config_map = _mcp_call("project.config.scan", {"project_path": project_path}, trace)
    runbooks = _mcp_call("project.runbook.search", {"project_path": project_path, "query": "incident runbook rollback timeout error"}, trace)
    profile = ProjectProfile(
        project_id=f"proj_{uuid4().hex[:8]}",
        name=name.strip() or project_map.get("project_path", "Imported Project").split("\\")[-1],
        project_path=project_map["project_path"],
        created_at=datetime.now().isoformat(timespec="seconds"),
        project_map={**project_map, "configs": config_map.get("configs", []), "runbooks": runbooks.get("runbooks", [])},
        mcp_calls=trace,
    )
    PROJECTS[profile.project_id] = profile
    return _profile_payload(profile)


def list_projects() -> list[dict[str, Any]]:
    return [_profile_payload(profile) for profile in PROJECTS.values()]


def _profile_payload(profile: ProjectProfile) -> dict[str, Any]:
    return {
        "project_id": profile.project_id,
        "name": profile.name,
        "project_path": profile.project_path,
        "created_at": profile.created_at,
        "project_map": profile.project_map,
        "mcp_calls": profile.mcp_calls,
    }


def _incident_text(incident: dict[str, Any]) -> str:
    return "\n".join(
        str(incident.get(key) or "")
        for key in ["alert", "incident_type", "service", "error_log", "recent_change", "impact"]
        if incident.get(key)
    )


def _extract_signals(incident: dict[str, Any], project_map: dict[str, Any]) -> dict[str, Any]:
    alert = _incident_text(incident)
    text = alert.lower()
    services = project_map.get("services") or []
    service = str(incident.get("service") or "").strip()
    for item in services:
        if not service and item.lower() in text:
            service = item
            break
    if not service:
        for token in re.findall(r"[a-zA-Z0-9_-]+-service", alert):
            service = token
            break
    symptoms = []
    keyword_map = {
        "5xx": ["5xx", "500", "502", "503"],
        "latency_high": ["latency", "p95", "p99", "slow", "慢", "超时", "timeout"],
        "redis_error": ["redis"],
        "db_error": ["mysql", "postgres", "database", "db", "sql", "数据库"],
        "mq_lag": ["kafka", "rabbit", "mq", "queue", "lag", "积压"],
        "crashloop": ["crash", "crashloop", "启动失败", "restart", "重启"],
        "deploy_related": ["deploy", "release", "发版", "上线", "回滚"],
    }
    for symptom, words in keyword_map.items():
        if any(word in text for word in words):
            symptoms.append(symptom)
    keywords = sorted({word for word in re.findall(r"[a-zA-Z0-9_-]{3,}", alert) if word.lower() not in {"the", "and", "with", "service"}})
    incident_type = str(incident.get("incident_type") or "").strip()
    if incident_type and incident_type not in symptoms:
        symptoms.insert(0, incident_type)
    return {"service": service, "symptoms": symptoms or ["unknown"], "keywords": keywords[:12]}


def _build_plan(signals: dict[str, Any]) -> list[dict[str, Any]]:
    service = signals.get("service") or ""
    symptoms = set(signals.get("symptoms") or [])
    plan = [
        {"step": "scan_project_map", "tool": "project.scan", "why": "确认导入项目里有哪些服务、路由和依赖信号。"},
        {"step": "search_runbooks", "tool": "project.runbook.search", "why": "查项目文档里是否已有故障处置说明。"},
        {"step": "search_logs", "tool": "project.logs.search", "why": "查真实导入日志里的错误、超时和相关服务。"},
        {"step": "search_code", "tool": "project.code.search", "why": "查代码/配置里和故障关键词相关的位置。"},
    ]
    if {"redis_error", "db_error", "mq_lag", "deploy_related"} & symptoms:
        plan.append({"step": "scan_config", "tool": "project.config.scan", "why": "检查 Redis/DB/MQ/部署相关配置。"})
    if service:
        plan.append({"step": "service_focus", "tool": "project.code.search", "why": f"围绕 {service} 做一次服务级代码搜索。"})
    return plan


def _build_next_checks(signals: dict[str, Any], evidence: dict[str, Any], diagnosis: dict[str, Any]) -> list[dict[str, str]]:
    service = signals.get("service") or "相关服务"
    checks = []
    if not evidence.get("logs"):
        checks.append({
            "title": "补充真实错误日志",
            "detail": "当前没有命中具体错误栈。把后端终端 traceback 或 logs/*.log 放进项目后重新运行。",
            "target": "logs/*.log 或终端 traceback",
        })
    if not evidence.get("code"):
        checks.append({
            "title": "缩小代码搜索范围",
            "detail": f"当前没有命中代码位置。把服务/模块名填写为 {service} 的真实目录或关键词。",
            "target": "main.py / app.py / service module",
        })
    if "import" in signals.get("keywords", []):
        checks.append({
            "title": "检查启动入口和 import",
            "detail": "优先检查启动目录、main.py 顶部 import、requirements.txt 是否缺依赖或模块路径错误。",
            "target": "fullstack_agent/backend/main.py",
        })
    if any(item in signals.get("symptoms", []) for item in ["timeout", "latency_high"]):
        checks.append({
            "title": "确认超时发生位置",
            "detail": "区分是前端请求超时、后端外部搜索超时，还是模型/API 调用超时。",
            "target": "trace log / network panel / backend terminal",
        })
    checks.append({
        "title": "人工确认风险动作",
        "detail": "重启服务、回滚部署、修改依赖和环境变量之前，先确认影响范围和最近变更。",
        "target": "Safety Gate",
    })
    return checks[:5]


def _build_resolution_summary(signals: dict[str, Any], evidence: dict[str, Any], diagnosis: dict[str, Any]) -> dict[str, Any]:
    logs = len(evidence.get("logs", []))
    code = len(evidence.get("code", []))
    configs = len(evidence.get("configs", []))
    runbooks = len(evidence.get("runbooks", []))
    if logs and code:
        evidence_state = "证据较充分：同时命中日志和代码。"
    elif logs:
        evidence_state = "证据部分充分：命中日志，但还没有定位到代码位置。"
    elif code:
        evidence_state = "证据部分充分：命中代码，但缺少运行时日志验证。"
    else:
        evidence_state = "证据不足：没有命中真实错误日志或代码位置。"

    return {
        "headline": diagnosis["primary"],
        "evidence_state": evidence_state,
        "evidence_counts": {"logs": logs, "code": code, "configs": configs, "runbooks": runbooks},
        "confidence": diagnosis["confidence"],
        "service": signals.get("service") or "未知",
    }


def _infer_root_cause(signals: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    symptoms = set(signals.get("symptoms") or [])
    log_rows = evidence.get("logs", [])
    code_rows = evidence.get("code", [])
    config_rows = evidence.get("configs", [])
    runbook_rows = evidence.get("runbooks", [])
    log_text = " ".join(item.get("snippet", "") for item in evidence.get("logs", []))
    code_text = " ".join(item.get("snippet", "") for item in evidence.get("code", []))
    all_text = f"{log_text} {code_text}".lower()
    candidates = []
    if "redis_error" in symptoms or "redis" in all_text:
        candidates.append("Redis/cache dependency issue: connection timeout/refused or pool exhaustion.")
    if "db_error" in symptoms or any(token in all_text for token in ["sql", "mysql", "postgres", "slow query"]):
        candidates.append("Database query/config issue: slow query, connection exhaustion or migration mismatch.")
    if "mq_lag" in symptoms or any(token in all_text for token in ["kafka", "rabbit", "queue", "lag"]):
        candidates.append("Message queue backlog or consumer failure.")
    if "crashloop" in symptoms or any(token in all_text for token in ["missing", "env", "config", "crash"]):
        candidates.append("Startup/configuration failure after deployment.")
    if "deploy_related" in symptoms:
        candidates.append("Recent deployment is a strong suspect; compare changed config/code with error timeline.")
    if not candidates:
        if not log_rows and not code_rows:
            candidates.append("Evidence is insufficient: no matching runtime logs or code locations were found for this alert.")
        elif log_rows and not code_rows:
            candidates.append("Runtime symptom found in logs, but no matching code location yet; narrow the service/module keyword and rerun.")
        else:
            candidates.append("Insufficient evidence for a specific root cause; continue with service logs, config and recent changes.")
    evidence_count = sum(len(v) for v in evidence.values() if isinstance(v, list))
    has_runtime_evidence = bool(log_rows or code_rows)
    has_supporting_context = bool(config_rows or runbook_rows)
    if log_rows and code_rows and len(candidates) == 1 and evidence_count >= 6:
        confidence = "high"
    elif has_runtime_evidence or has_supporting_context:
        confidence = "medium"
    else:
        confidence = "low"
    return {
        "primary": candidates[0],
        "candidates": candidates,
        "confidence": confidence,
        "evidence_count": evidence_count,
        "needs_human_confirmation": True,
        "safe_actions": ["collect more logs", "compare recent config/code changes", "open linked evidence"],
        "risky_actions": ["rollback deployment", "restart service", "change connection pool", "run data repair"],
    }


def _build_agent_runs(
    plan: list[dict[str, Any]],
    evidence: dict[str, Any],
    diagnosis: dict[str, Any],
    trace: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    return [
        {
            "agent": "Project Mapper Agent",
            "role": "导入项目并构建 ProjectMap，识别文件、API、服务和依赖信号。",
            "status": "completed",
            "tool_calls": _calls(trace, "project.scan", "project.config.scan"),
            "summary": f"生成 {len(plan)} 步排障计划，配置证据 {len(evidence.get('configs', []))} 条。",
        },
        {
            "agent": "Runbook Agent",
            "role": "搜索项目文档中的故障、回滚、告警和处置说明。",
            "status": "completed",
            "tool_calls": _calls(trace, "project.runbook.search"),
            "summary": f"找到 {len(evidence.get('runbooks', []))} 条 runbook 候选。",
        },
        {
            "agent": "Log Investigator Agent",
            "role": "基于服务名、症状和关键词搜索真实日志。",
            "status": "completed",
            "tool_calls": _calls(trace, "project.logs.search"),
            "summary": f"找到 {len(evidence.get('logs', []))} 条日志证据。",
        },
        {
            "agent": "Code Investigator Agent",
            "role": "搜索真实代码/配置，定位和故障关键词相关的位置。",
            "status": "completed",
            "tool_calls": _calls(trace, "project.code.search"),
            "summary": f"找到 {len(evidence.get('code', []))} 条代码证据。",
        },
        {
            "agent": "Diagnosis Agent",
            "role": "融合 runbook、日志、代码和配置证据，输出候选根因和安全边界。",
            "status": "completed",
            "tool_calls": [],
            "summary": f"根因可信度 {diagnosis['confidence']}，证据 {diagnosis['evidence_count']} 条。",
        },
    ]


def run_incident(project_id: str, incident: dict[str, Any] | str) -> dict[str, Any]:
    if project_id not in PROJECTS:
        raise ValueError("Please import a project before running incident response.")
    if isinstance(incident, str):
        incident = {"alert": incident}
    profile = PROJECTS[project_id]
    trace: list[dict[str, Any]] = []
    alert_text = _incident_text(incident)
    signals = _extract_signals(incident, profile.project_map)
    plan = _build_plan(signals)
    project_path = profile.project_path
    query = " ".join([signals.get("service") or "", *signals.get("keywords", []), *signals.get("symptoms", [])]).strip() or alert_text
    log_keywords = list({*signals.get("keywords", []), *signals.get("symptoms", []), "error", "timeout", "exception"})

    _mcp_call("project.scan", {"project_path": project_path}, trace)
    runbooks = _mcp_call("project.runbook.search", {"project_path": project_path, "query": alert_text}, trace).get("runbooks", [])
    logs = _mcp_call("project.logs.search", {"project_path": project_path, "service": signals.get("service", ""), "keywords": log_keywords}, trace).get("matches", [])
    code = _mcp_call("project.code.search", {"project_path": project_path, "query": query, "limit": 30}, trace).get("matches", [])
    configs = _mcp_call("project.config.scan", {"project_path": project_path}, trace).get("configs", [])

    evidence = {"runbooks": runbooks, "logs": logs, "code": code, "configs": configs[:20]}
    diagnosis = _infer_root_cause(signals, evidence)
    resolution = _build_resolution_summary(signals, evidence, diagnosis)
    next_checks = _build_next_checks(signals, evidence, diagnosis)
    agent_runs = _build_agent_runs(plan, evidence, diagnosis, trace)
    report = _build_report(profile, alert_text, signals, plan, evidence, diagnosis)
    run = {
        "run_id": f"inc_{uuid4().hex[:10]}",
        "project_id": project_id,
        "project_name": profile.name,
        "status": "completed",
        "created_at": datetime.now().isoformat(timespec="seconds"),
        "alert": alert_text,
        "incident": incident,
        "signals": signals,
        "plan": plan,
        "evidence": evidence,
        "diagnosis": diagnosis,
        "resolution": resolution,
        "next_checks": next_checks,
        "agent_runs": agent_runs,
        "mcp_calls": trace,
        "report": report,
    }
    INCIDENT_RUNS.insert(0, run)
    del INCIDENT_RUNS[20:]
    return run


def list_incident_runs() -> list[dict[str, Any]]:
    return INCIDENT_RUNS


def _build_report(profile: ProjectProfile, alert: str, signals: dict[str, Any], plan: list[dict[str, Any]], evidence: dict[str, Any], diagnosis: dict[str, Any]) -> str:
    plan_lines = "\n".join(f"- {item['step']}: {item['why']}" for item in plan)
    evidence_lines = []
    for group, rows in evidence.items():
        evidence_lines.append(f"- {group}: {len(rows)} items")
    candidate_lines = "\n".join(f"- {item}" for item in diagnosis["candidates"])
    return f"""# ProjectOps Incident Report

## Project
{profile.name}

## Alert
{alert}

## Parsed Signals
- service: {signals.get('service') or 'unknown'}
- symptoms: {', '.join(signals.get('symptoms') or [])}
- keywords: {', '.join(signals.get('keywords') or [])}

## Runbook Plan
{plan_lines}

## Evidence Summary
{chr(10).join(evidence_lines)}

## Diagnosis
- primary: {diagnosis['primary']}
- confidence: {diagnosis['confidence']}
- evidence_count: {diagnosis['evidence_count']}

## Evidence Caveat
If logs/code evidence is 0, the result is a triage direction rather than a confirmed root cause. Import a real logs directory or paste the exact error stack to improve confidence.

## Candidates
{candidate_lines}

## Safety Gate
Risky actions such as rollback, restart, config changes and data repair require human confirmation. This agent only prepares the evidence and action draft.
"""
