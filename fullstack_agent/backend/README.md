# Jerry-Insight Pro Backend

FastAPI backend for the Jerry-Insight Pro Agent workspace.

The current version contains two engineering-style Agent flows instead of a generic chat page:

1. Deal Research Agent
2. ProjectOps Incident Agent

## 1. Deal Research Agent

Type: Data Agent + Search Agent + MCP tool calling

This flow upgrades the original "省钱智探" project into a purchase decision research workflow:

```text
purchase intent -> search/ledger/memory evidence -> evidence layer -> decision report -> human confirmation
```

Core capabilities:

- Reuses `original_pipeline.py` for Tavily search, price clues, LLM audit and price parsing.
- Reads local ledger, current surplus, history and blocked items.
- Produces evidence cards, price sources, personal budget context and a purchase recommendation.
- Keeps purchase confirmation and skip-purchase as explicit human actions.

## 2. ProjectOps Incident Agent

Type: project-aware AIOps Agent + MCP tool calling

This flow does not guess without context. The user imports a project directory, then the Agent reads real files, configs, logs and runbooks through MCP-style tools:

```text
import project -> project.scan -> ProjectMap -> incident input -> MCP tool calls -> evidence panel -> diagnosis report -> safety gate
```

MCP tools include:

- `project.scan`: scan a real project directory and build a ProjectMap.
- `project.code.search`: search real code and config files.
- `project.logs.search`: search log files in the imported project.
- `project.config.scan`: scan Docker, env and dependency config.
- `project.runbook.search`: search runbooks and incident documents.
- `finance.context.read`: read the Deal Research ledger context.

## MCP API

- `GET /api/mcp/tools`: list MCP tools.
- `POST /api/mcp`: JSON-RPC style MCP call.

Example:

```json
{
  "jsonrpc": "2.0",
  "id": "1",
  "method": "tools/call",
  "params": {
    "name": "project.scan",
    "arguments": {
      "project_path": "C:\\Users\\Jerry\\Desktop\\AIstudy\\Jerry-Insight-Pro"
    }
  }
}
```

## Business API

- `POST /api/deal-research/run`
- `GET /api/deal-research/runs`
- `POST /api/project-ops/import`
- `GET /api/project-ops/projects`
- `POST /api/project-ops/incident`
- `GET /api/project-ops/incidents`
- `POST /api/chat`
- `GET /api/ledger`
- `GET /api/profile`

## Local Run

```bash
cd fullstack_agent/backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

Open health check:

```text
http://127.0.0.1:8000/api/health
```

## Environment Variables

```env
DEEPSEEK_API_KEY=your_key
DEEPSEEK_BASE_URL=https://api.deepseek.com
TAVILY_API_KEY=your_search_key
DINGTALK_WEBHOOK=your_optional_dingtalk_webhook
```
