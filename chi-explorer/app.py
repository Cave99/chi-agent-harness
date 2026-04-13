"""
app.py — FastAPI entry point for Chi Explorer.

Routes:
  POST /chat              → submit a question (triggers Business Agent + approval gate)
  POST /refine            → refine the current plan with an instruction
  POST /patch             → Apply manual edits to the current plan
  POST /validate-sql      → Lightweight server-side SQL WHERE-clause linter using sqlglot
  POST /run               → approve and run the full pipeline
  GET  /stream/{sid}      → SSE stream for real-time status updates
  POST /reset             → clear session and start fresh
"""
from __future__ import annotations

import json
import logging
import uuid
import asyncio

from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

import config
from agents import business_agent
from pipeline import db
import session.state as state
from services.sse_manager import sse_manager
from services.orchestrator import (
    run_business_agent_task,
    run_pipeline_task,
    run_followup_task,
    estimate_cost
)

import sqlglot

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI(title="Chi Explorer API")

# Allow CORS for React frontend (Vite runs on 5173 usually)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_session_id(sid: str | None = None) -> str:
    if not sid:
        return str(uuid.uuid4())
    return sid

# ── Routes ────────────────────────────────────────────────────────────────────

@app.post("/chat")
async def chat(background_tasks: BackgroundTasks, question: str = Form(...), session_id: str | None = Form(None)):
    """
    User submitted a question.
    Immediately returns {ok, session_id} and kicks off either the Business Agent
    (for a new plan) or the Data Agent (for a follow-up).
    """
    sid = _get_or_create_session_id(session_id)
    if not question:
        raise HTTPException(status_code=400, detail="Question cannot be empty.")

    s = state.get(sid)
    has_data = len(s.get("enriched_records", [])) > 0
    
    # ── 1. Route the question ────────────────────────────────────────────────
    if has_data:
        job = s.get("current_job", {})
        context = {
            "previous_question": job.get("question", ""),
            "field_manifest": job.get("field_manifest", {}),
            "summary": s.get("last_summary_dict", {}),
            "has_data": True,
        }
        route = await asyncio.to_thread(business_agent.route_question, question, context)
    else:
        route = "new_analysis"

    # ── 2. Dispatch the appropriate task ─────────────────────────────────────
    sse_manager.ensure_queue(sid)

    if route == "follow_up":
        state.append_message(sid, "user", question)
        background_tasks.add_task(run_followup_task, sid, question)
    else:
        state.append_message(sid, "user", question)
        state.clear_job(sid)
        state.update(sid, last_summary_dict={}, last_charts=[], enriched_records=[])
        state.update_job(sid, question=question, status="pending")
        background_tasks.add_task(run_business_agent_task, sid, question)

    return JSONResponse({"ok": True, "session_id": sid})


@app.post("/run")
async def run_pipeline(background_tasks: BackgroundTasks, session_id: str = Form(...)):
    """
    User approved the batch. Kick off the full pipeline.
    """
    s = state.get(session_id)
    job = s.get("current_job", {})

    if job.get("status") not in ("pending", "failed"):
        raise HTTPException(status_code=400, detail="No pending job.")

    sse_manager.ensure_queue(session_id)
    state.update_job(session_id, status="running")

    background_tasks.add_task(
        run_pipeline_task,
        session_id,
        job["question"],
        job["where_clause"],
        job["system_prompt"],
        job["field_manifest"]
    )
    return JSONResponse({"ok": True, "session_id": session_id})


@app.post("/refine")
async def refine_plan(background_tasks: BackgroundTasks, session_id: str = Form(...), instruction: str = Form(...)):
    """
    User wants to refine the current analysis plan via AI.
    """
    if not instruction:
        raise HTTPException(status_code=400, detail="Instruction cannot be empty.")

    s = state.get(session_id)
    job = s.get("current_job", {})
    original_question = job.get("question", "")

    if not original_question:
        raise HTTPException(status_code=400, detail="No active analysis plan to refine.")

    current_plan = {
        "where_clause": job.get("where_clause", ""),
        "system_prompt": job.get("system_prompt", ""),
        "field_manifest": job.get("field_manifest", {}),
    } if job.get("where_clause") is not None else None

    sse_manager.ensure_queue(session_id)
    background_tasks.add_task(run_business_agent_task, session_id, original_question, instruction, current_plan)
    return JSONResponse({"ok": True, "session_id": session_id})


@app.post("/patch")
async def patch_plan(request: Request):
    """
    Apply manual edits to the current plan.
    """
    data = await request.json()
    sid = data.get("session_id")
    if not sid:
        raise HTTPException(status_code=400, detail="session_id required.")
        
    s = state.get(sid)
    job = s.get("current_job", {})
    if not job.get("question"):
        raise HTTPException(status_code=400, detail="No active job to patch.")

    updates = {}
    if "where_clause" in data: updates["where_clause"] = data["where_clause"]
    if "system_prompt" in data: updates["system_prompt"] = data["system_prompt"]
    if "field_manifest" in data:
        if not isinstance(data["field_manifest"], dict) or "fields" not in data["field_manifest"]:
            raise HTTPException(status_code=400, detail="field_manifest must be a dict with a 'fields' key.")
        updates["field_manifest"] = data["field_manifest"]

    if not updates:
        raise HTTPException(status_code=400, detail="No changes provided.")

    state.update_job(sid, **updates)
    job = state.get(sid)["current_job"]

    where_clause   = job["where_clause"]
    system_prompt  = job["system_prompt"]
    field_manifest = job["field_manifest"]
    question       = job["question"]

    count_result  = db.count_calls(where_clause)
    call_count    = count_result["count"]
    field_count   = len(field_manifest.get("fields", []))
    cost_estimate = estimate_cost(call_count, field_count)
    warn_count    = call_count > config.CALL_COUNT_WARN_THRESHOLD
    warn_cost     = cost_estimate > config.COST_WARN_THRESHOLD_USD

    sample_call_ids = db.fetch_sample_call_ids(where_clause, limit=3)
    sample_transcripts = db.fetch_sample_transcripts(sample_call_ids)

    return JSONResponse({
        "ok": True,
        "data": {
            "question": question,
            "where_clause": where_clause,
            "system_prompt": system_prompt,
            "field_manifest": field_manifest,
            "call_count": call_count,
            "cost_estimate": cost_estimate,
            "warn_count": warn_count,
            "warn_cost": warn_cost,
            "sample_transcripts": sample_transcripts,
        }
    })


# Known columns for SQL linting
_KNOWN_COLUMNS = {
    "call_id", "agent_name", "team_name", "call_datetime",
    "call_duration", "call_queue", "agent_leader_name", "agent_team_id",
}

@app.post("/validate-sql")
async def validate_sql(payload: dict = Body(...)):
    """
    Lightweight server-side SQL WHERE-clause linter using sqlglot.
    Returns {ok: bool, errors: [str]}.
    """
    clause = (payload.get("where_clause") or "").strip()
    errors = []
    
    if clause:
        try:
            ast = sqlglot.parse_one(f"SELECT * FROM tbl WHERE {clause}")
            for c in ast.find_all(sqlglot.exp.Column):
                col_name = c.name.lower()
                if col_name not in _KNOWN_COLUMNS:
                    errors.append(f"Unknown column: '{col_name}'")
        except Exception as e:
            errors.append(f"SQL Syntax Error: {str(e)}")

    return JSONResponse({"ok": len(errors) == 0, "errors": errors})


@app.get("/stream/{session_id}")
async def stream(session_id: str, request: Request):
    """SSE endpoint."""
    async def generate():
        q = sse_manager.ensure_queue(session_id)
        while True:
            if await request.is_disconnected():
                break
            try:
                item = await asyncio.wait_for(q.get(), timeout=30)
                yield {"event": item["event"], "data": json.dumps(item["data"])}
                if item["event"] in ("complete", "gate", "error"):
                    break
            except asyncio.TimeoutError:
                yield {"event": "ping", "data": "{}"}
                
    return EventSourceResponse(generate())


@app.post("/reset")
async def reset():
    sid = _get_or_create_session_id()
    state.update(sid, messages=[], current_job={}, last_summary_dict={}, last_charts=[], enriched_records=[])
    sse_manager.remove_session(sid)
    return JSONResponse({"ok": True}, status_code=204)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=config.API_PORT, reload=True)
