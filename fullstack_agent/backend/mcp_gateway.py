from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable

from db import get_current_surplus, list_blocked_items, list_history, list_ledger


ROOT = Path(__file__).resolve().parents[2]
PROJECT_ROOT = ROOT.resolve()
TEXT_SUFFIXES = {
    ".py",
    ".js",
    ".ts",
    ".vue",
    ".json",
    ".yaml",
    ".yml",
    ".toml",
    ".ini",
    ".env",
    ".md",
    ".txt",
    ".log",
    ".jsonl",
    ".csv",
}
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build", ".next"}
NOISE_NAME_MARKERS = {
    "interview",
    "cheatsheet",
    "notepad",
    "course_notes",
    "lesson_",
    "artifacts",
    "prep",
    "面试",
    "速记",
}


@dataclass
class ToolResult:
    content: list[dict[str, Any]]
    structuredContent: dict[str, Any]
    isError: bool = False


@dataclass
class McpTool:
    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], ToolResult]


def _text_result(text: str, payload: dict[str, Any] | None = None, is_error: bool = False) -> ToolResult:
    return ToolResult(
        content=[{"type": "text", "text": text}],
        structuredContent=payload or {},
        isError=is_error,
    )


def _resolve_project_path(raw_path: str | None) -> Path:
    if not raw_path:
        return PROJECT_ROOT
    normalized = os.path.expandvars(str(raw_path).strip().strip("\"'"))
    path = Path(normalized).expanduser()
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    resolved = path.resolve()
    if not resolved.exists() or not resolved.is_dir():
        raise ValueError(f"project_path does not exist or is not a directory: {resolved}")
    forbidden_roots = {
        Path(resolved.anchor).resolve(),
        Path.home().resolve(),
        Path(os.environ.get("WINDIR", "C:\\Windows")).resolve(),
    }
    if resolved in forbidden_roots:
        raise ValueError("project_path must be a project folder, not a drive/user/system root directory")
    return resolved


def _iter_text_files(base: Path, limit: int = 600) -> list[Path]:
    files: list[Path] = []
    for path in base.rglob("*"):
        if any(part in SKIP_DIRS for part in path.relative_to(base).parts):
            continue
        if path.is_file() and (path.suffix.lower() in TEXT_SUFFIXES or path.name.startswith(".env")):
            files.append(path)
            if len(files) >= limit:
                break
    return files


def _safe_read(path: Path, max_chars: int = 12000) -> str:
    return path.read_text(encoding="utf-8", errors="ignore")[:max_chars]


def _rel(base: Path, path: Path) -> str:
    return path.relative_to(base).as_posix()


def _path_text(base: Path, path: Path) -> str:
    return _rel(base, path).lower()


def _is_noise_doc(base: Path, path: Path) -> bool:
    rel = _path_text(base, path)
    return any(marker in rel for marker in NOISE_NAME_MARKERS)


def _is_log_candidate(base: Path, path: Path) -> bool:
    rel = _path_text(base, path)
    if path.suffix.lower() in {".log", ".jsonl"}:
        return True
    return any(part in {"logs", "log"} for part in path.relative_to(base).parts)


def _is_runbook_candidate(base: Path, path: Path) -> bool:
    if path.suffix.lower() != ".md" or _is_noise_doc(base, path):
        return False
    rel = _path_text(base, path)
    name = path.name.lower()
    return (
        any(part in {"docs", "doc", "runbooks", "runbook"} for part in path.relative_to(base).parts)
        or any(token in rel for token in ["runbook", "incident", "troubleshoot", "troubleshooting", "deploy", "ops", "故障", "排障", "告警", "回滚"])
        or name in {"readme.md", "deploy.md", "operations.md"}
    )


def _project_scan(args: dict[str, Any]) -> ToolResult:
    base = _resolve_project_path(args.get("project_path"))
    files = _iter_text_files(base)
    suffix_counts: dict[str, int] = {}
    important: list[str] = []
    services: set[str] = set()
    api_routes: list[dict[str, Any]] = []
    dependencies: list[dict[str, str]] = []

    service_patterns = [
        re.compile(r"service_name\s*[:=]\s*['\"]?([a-zA-Z0-9_-]+)"),
        re.compile(r"name\s*[:=]\s*['\"]?([a-zA-Z0-9_-]+-service)"),
        re.compile(r"([a-zA-Z0-9_-]+-service)"),
    ]
    route_pattern = re.compile(r"@(?:app|router)\.(get|post|put|delete|patch)\(['\"]([^'\"]+)['\"]")
    depends_pattern = re.compile(r"(depends_on|dependency|dependencies|REDIS|MYSQL|POSTGRES|KAFKA|RABBIT|MQ)", re.I)

    for path in files:
        rel = _rel(base, path)
        if _is_noise_doc(base, path):
            continue
        suffix_counts[path.suffix.lower() or "no_ext"] = suffix_counts.get(path.suffix.lower() or "no_ext", 0) + 1
        if path.name.lower() in {"docker-compose.yml", "docker-compose.yaml", "package.json", "pyproject.toml", "requirements.txt"}:
            important.append(rel)
        text = _safe_read(path, 6000)
        for method, route in route_pattern.findall(text):
            api_routes.append({"file": rel, "method": method.upper(), "route": route})
        for pattern in service_patterns:
            for match in pattern.findall(text):
                if len(match) >= 3:
                    services.add(match)
        if depends_pattern.search(text):
            dependencies.append({"file": rel, "signal": "dependency/config reference"})

    payload = {
        "project_path": str(base),
        "scanned_files": len(files),
        "file_types": suffix_counts,
        "important_files": important[:30],
        "services": sorted(services)[:40],
        "api_routes": api_routes[:80],
        "dependency_signals": dependencies[:40],
    }
    return _text_result(f"Scanned {len(files)} text files under {base.name}.", payload)


def _code_search(args: dict[str, Any]) -> ToolResult:
    base = _resolve_project_path(args.get("project_path"))
    query = str(args.get("query") or "").strip()
    max_results = int(args.get("limit") or 30)
    if not query:
        raise ValueError("query is required")
    terms = [term.lower() for term in re.split(r"\s+", query) if term.strip()]
    results = []
    for path in _iter_text_files(base):
        text = _safe_read(path, 24000)
        lowered = text.lower()
        if not all(term in lowered for term in terms):
            continue
        for line_no, line in enumerate(text.splitlines(), start=1):
            line_lower = line.lower()
            if any(term in line_lower for term in terms):
                results.append({"file": _rel(base, path), "line": line_no, "snippet": line.strip()[:220]})
                break
        if len(results) >= max_results:
            break
    return _text_result(f"Found {len(results)} code matches for {query}.", {"query": query, "matches": results})


def _log_search(args: dict[str, Any]) -> ToolResult:
    base = _resolve_project_path(args.get("project_path"))
    keywords = args.get("keywords") or []
    if isinstance(keywords, str):
        keywords = [keywords]
    terms = [str(item).lower() for item in keywords if str(item).strip()]
    service = str(args.get("service") or "").lower()
    weak_terms = {"error", "exception", "timeout", "latency_high", "unknown"}
    strong_terms = [term for term in terms if term not in weak_terms]
    results = []
    candidates = [p for p in _iter_text_files(base) if _is_log_candidate(base, p)]
    for path in candidates:
        text = _safe_read(path, 36000)
        for line_no, line in enumerate(text.splitlines(), start=1):
            lower = line.lower()
            if service and service not in lower and service not in path.as_posix().lower():
                continue
            if strong_terms and not any(term in lower or term in path.as_posix().lower() for term in strong_terms):
                continue
            if terms and not any(term in lower for term in terms):
                continue
            results.append({"file": _rel(base, path), "line": line_no, "snippet": line.strip()[:260]})
            if len(results) >= 40:
                return _text_result(f"Found {len(results)} log matches.", {"matches": results})
    return _text_result(f"Found {len(results)} log matches.", {"matches": results})


def _config_scan(args: dict[str, Any]) -> ToolResult:
    base = _resolve_project_path(args.get("project_path"))
    config_names = {"docker-compose.yml", "docker-compose.yaml", "Dockerfile", "kubernetes.yml", "k8s.yml", "package.json", "pyproject.toml", "requirements.txt"}
    results = []
    for path in _iter_text_files(base):
        if path.name in config_names or path.suffix.lower() in {".yaml", ".yml", ".toml", ".env"}:
            text = _safe_read(path, 8000)
            signals = []
            for token in ["redis", "mysql", "postgres", "kafka", "rabbit", "prometheus", "loki", "sentry", "timeout", "retry"]:
                if token in text.lower():
                    signals.append(token)
            results.append({"file": _rel(base, path), "signals": signals[:12]})
    return _text_result(f"Scanned {len(results)} config files.", {"configs": results[:80]})


def _runbook_search(args: dict[str, Any]) -> ToolResult:
    base = _resolve_project_path(args.get("project_path"))
    query = str(args.get("query") or "").lower()
    terms = [term for term in re.split(r"\s+", query) if term]
    results = []
    for path in _iter_text_files(base):
        if not _is_runbook_candidate(base, path):
            continue
        text = _safe_read(path, 20000)
        lower = text.lower()
        if not any(token in lower for token in ["runbook", "incident", "故障", "排障", "告警", "rollback", "回滚"]) and not any(term in lower for term in terms):
            continue
        results.append({"file": _rel(base, path), "snippet": text[:360].replace("\n", " ")})
        if len(results) >= 20:
            break
    return _text_result(f"Found {len(results)} runbook candidates.", {"runbooks": results})


def _finance_context(args: dict[str, Any]) -> ToolResult:
    limit = int(args.get("limit") or 20)
    payload = {
        "current_surplus": get_current_surplus(),
        "ledger": list_ledger(limit=limit),
        "blocked_items": list_blocked_items(limit=limit),
        "history": list_history(limit=limit),
    }
    return _text_result("Loaded finance context from SQLite.", payload)


def _deal_search_evidence(args: dict[str, Any]) -> ToolResult:
    query = str(args.get("query") or "").strip()
    if not query:
        raise ValueError("query is required")
    from original_pipeline import run_web_search

    info_blocks, raw_info_text, price_table_data = run_web_search(query)
    payload = {
        "query": query,
        "info_blocks": info_blocks,
        "raw_info_text": raw_info_text,
        "price_table_data": price_table_data,
    }
    return _text_result(f"Loaded search evidence for {query}.", payload)


class JerryMcpGateway:
    def __init__(self) -> None:
        self.tools: dict[str, McpTool] = {}
        self._register_core_tools()

    def _register(self, tool: McpTool) -> None:
        self.tools[tool.name] = tool

    def _register_core_tools(self) -> None:
        self._register(
            McpTool(
                "finance.context.read",
                "Read local finance ledger, balance, blocked items and recent history.",
                {"type": "object", "properties": {"limit": {"type": "integer", "default": 20}}},
                _finance_context,
            )
        )
        self._register(
            McpTool(
                "deal.search.evidence",
                "Search product price/risk evidence through the existing Tavily-backed deal research adapter.",
                {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
                _deal_search_evidence,
            )
        )
        self._register(
            McpTool(
                "project.scan",
                "Scan an imported local project and build a ProjectMap from real files.",
                {"type": "object", "properties": {"project_path": {"type": "string"}}, "required": ["project_path"]},
                _project_scan,
            )
        )
        self._register(
            McpTool(
                "project.code.search",
                "Search real project source/config files for keywords.",
                {
                    "type": "object",
                    "properties": {"project_path": {"type": "string"}, "query": {"type": "string"}, "limit": {"type": "integer"}},
                    "required": ["project_path", "query"],
                },
                _code_search,
            )
        )
        self._register(
            McpTool(
                "project.logs.search",
                "Search real imported log files for a service and keywords.",
                {
                    "type": "object",
                    "properties": {
                        "project_path": {"type": "string"},
                        "service": {"type": "string"},
                        "keywords": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["project_path"],
                },
                _log_search,
            )
        )
        self._register(
            McpTool(
                "project.config.scan",
                "Scan real project config files and dependency signals.",
                {"type": "object", "properties": {"project_path": {"type": "string"}}, "required": ["project_path"]},
                _config_scan,
            )
        )
        self._register(
            McpTool(
                "project.runbook.search",
                "Search project markdown docs for runbooks and incident notes.",
                {"type": "object", "properties": {"project_path": {"type": "string"}, "query": {"type": "string"}}, "required": ["project_path"]},
                _runbook_search,
            )
        )

    def list_tools(self) -> list[dict[str, Any]]:
        return [
            {"name": tool.name, "description": tool.description, "input_schema": tool.input_schema}
            for tool in self.tools.values()
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> dict[str, Any]:
        if name not in self.tools:
            raise ValueError(f"Unknown MCP tool: {name}")
        return asdict(self.tools[name].handler(arguments or {}))

    def handle_json_rpc(self, request: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(request, str):
            request = json.loads(request)
        req_id = request.get("id")
        method = request.get("method")
        try:
            if method == "tools/list":
                return {"jsonrpc": "2.0", "id": req_id, "result": {"tools": self.list_tools()}}
            if method == "tools/call":
                params = request.get("params") or {}
                result = self.call_tool(params.get("name"), params.get("arguments") or {})
                return {"jsonrpc": "2.0", "id": req_id, "result": result}
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": f"Unknown method: {method}"}}
        except Exception as err:
            return {"jsonrpc": "2.0", "id": req_id, "error": {"code": -32603, "message": str(err)}}


mcp_gateway = JerryMcpGateway()
