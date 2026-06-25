from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from agent_service import run_agent
from db import (
    adjust_surplus,
    clear_history,
    get_current_surplus,
    init_db,
    insert_blocked_item,
    insert_chat,
    insert_ledger_entry,
    list_blocked_items,
    list_history,
    list_ledger,
)
from deal_research_service import list_deal_runs, run_deal_research
from mcp_gateway import mcp_gateway
from notifier import notify_async
from project_ops_service import import_project, list_incident_runs, list_projects, run_incident
from lifeops_service import list_runs as list_lifeops_runs
from lifeops_service import list_specs as list_lifeops_specs
from lifeops_service import run_lifeops


app = FastAPI(
    title="Jerry-Insight Agent API",
    description="Vue + FastAPI fullstack backend for Jerry-Insight Agent.",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=1000)


class ConfirmPurchaseRequest(BaseModel):
    item: str = Field(..., min_length=1, max_length=100)
    amount: float = Field(..., gt=0)
    raw_query: str = ""


class SkipPurchaseRequest(BaseModel):
    item: str = Field(..., min_length=1, max_length=100)
    reason: str = "用户放弃购买"
    raw_query: str = ""


class LifeOpsRunRequest(BaseModel):
    event_type: str = Field(..., min_length=1, max_length=80)
    goal: str = Field(..., min_length=1, max_length=1200)


class DealResearchRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=1200)


class McpJsonRpcRequest(BaseModel):
    jsonrpc: str = "2.0"
    id: str | int | None = None
    method: str
    params: dict = Field(default_factory=dict)


class ProjectImportRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=120)
    project_path: str = Field(..., min_length=1, max_length=500)


class IncidentRunRequest(BaseModel):
    project_id: str = Field(..., min_length=1, max_length=80)
    incident_type: str = Field(default="", max_length=80)
    service: str = Field(default="", max_length=120)
    error_log: str = Field(default="", max_length=4000)
    recent_change: str = Field(default="", max_length=1600)
    impact: str = Field(default="", max_length=1200)
    alert: str = Field(default="", max_length=1600)


@app.on_event("startup")
def startup():
    init_db()


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "service": "jerry-insight-agent-api",
        "current_surplus": get_current_surplus(),
    }


@app.get("/api/lifeops/spec")
def lifeops_spec():
    return list_lifeops_specs()


@app.get("/api/lifeops/runs")
def lifeops_runs():
    return {"items": list_lifeops_runs()}


@app.post("/api/lifeops/run")
def lifeops_run(req: LifeOpsRunRequest):
    return run_lifeops(req.event_type, req.goal)


@app.post("/api/deal-research/run")
def deal_research_run(req: DealResearchRequest):
    return run_deal_research(req.query)


@app.get("/api/deal-research/runs")
def deal_research_runs():
    return {"items": list_deal_runs()}


@app.post("/api/mcp")
def mcp_json_rpc(req: McpJsonRpcRequest):
    return mcp_gateway.handle_json_rpc(req.dict())


@app.get("/api/mcp/tools")
def mcp_tools():
    return {"tools": mcp_gateway.list_tools()}


@app.post("/api/project-ops/import")
def project_ops_import(req: ProjectImportRequest):
    try:
        return import_project(req.name, req.project_path)
    except ValueError as err:
        raise HTTPException(status_code=400, detail=str(err)) from err


@app.get("/api/project-ops/projects")
def project_ops_projects():
    return {"items": list_projects()}


@app.post("/api/project-ops/incident")
def project_ops_incident(req: IncidentRunRequest):
    if not any([req.alert.strip(), req.error_log.strip(), req.service.strip(), req.recent_change.strip(), req.impact.strip()]):
        raise HTTPException(status_code=400, detail="请至少填写服务、错误日志、最近变更或影响范围中的一项。")
    return run_incident(
        req.project_id,
        {
            "incident_type": req.incident_type,
            "service": req.service,
            "error_log": req.error_log,
            "recent_change": req.recent_change,
            "impact": req.impact,
            "alert": req.alert,
        },
    )


@app.get("/api/project-ops/incidents")
def project_ops_incidents():
    return {"items": list_incident_runs()}


@app.post("/api/chat")
def chat(req: ChatRequest):
    result = run_agent(req.message)
    chat_id = insert_chat(
        user_message=req.message,
        assistant_reply=result.reply,
        intent=result.intent,
        latency_ms=result.latency_ms,
    )
    return {
        "id": chat_id,
        "reply": result.reply,
        "intent": result.intent,
        "latency_ms": result.latency_ms,
        "trace": result.trace,
        "payload": result.payload,
    }


@app.get("/api/history")
def history(limit: int = 50):
    return {"items": list_history(limit=limit)}


@app.delete("/api/history")
def delete_history():
    clear_history()
    return {"status": "cleared"}


@app.get("/api/ledger")
def ledger(limit: int = 50):
    return {"items": list_ledger(limit=limit)}


@app.get("/api/blocked")
def blocked(limit: int = 50):
    return {"items": list_blocked_items(limit=limit)}


@app.get("/api/profile")
def profile():
    return {"current_surplus": get_current_surplus()}


@app.post("/api/confirm-purchase")
def confirm_purchase(req: ConfirmPurchaseRequest):
    current_surplus = adjust_surplus(-req.amount)
    entry_id = insert_ledger_entry(
        item=req.item,
        amount=req.amount,
        source="fastapi_audit_confirm",
        raw_query=req.raw_query or f"确认购买 {req.item}",
    )
    notify_async(
        "Jerry-Insight 确认购入",
        f"- 商品：`{req.item}`\n- 扣除：`{req.amount}` 元\n- 当前余额：`{current_surplus}` 元\n- 来源：全栈版确认购入",
    )
    return {
        "status": "ok",
        "entry_id": entry_id,
        "item": req.item,
        "amount": req.amount,
        "current_surplus": current_surplus,
    }


@app.post("/api/skip-purchase")
def skip_purchase(req: SkipPurchaseRequest):
    item_id = insert_blocked_item(
        item=req.item,
        reason=req.reason,
        raw_query=req.raw_query or req.item,
    )
    notify_async(
        "Jerry-Insight 放弃购买",
        f"- 商品：`{req.item}`\n- 原因：{req.reason}\n- 本次未扣除余额",
    )
    return {
        "status": "ok",
        "id": item_id,
        "item": req.item,
        "reason": req.reason,
    }
