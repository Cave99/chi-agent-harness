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
import time
import threading
import uuid
import asyncio

from fastapi import FastAPI, Request, Form, BackgroundTasks, HTTPException, Body
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

import config
from agents import business_agent, vision_agent, data_agent
from pipeline import batch, db, parser, provider, sandbox
import session.state as state

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

# In FastAPI, we'll store async Queues for SSE instead of threading.Queue
_sse_queues: dict[str, asyncio.Queue] = {}

# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_session_id(sid: str | None = None) -> str:
    if not sid:
        return str(uuid.uuid4())
    return sid

async def _push_event(session_id: str, event: str, data: dict) -> None:
    """Push a server-sent event to the session's queue."""
    q = _sse_queues.get(session_id)
    if q:
        await q.put({"event": event, "data": data})

def _estimate_cost(call_count: int, field_count: int) -> float:
    """Rough input token cost estimate at ~$3 per million tokens."""
    tokens_per_call = 800 + field_count * 50
    total_tokens = call_count * tokens_per_call
    return round(total_tokens / 1_000_000 * 3.0, 2)


async def _stream_business_agent(sid: str, question: str) -> dict:
    """
    Stream the Business Agent's first LLM attempt, pushing background_token events
    for each chunk so the UI can show live generation progress.
    Returns the parsed plan dict.
    """
    loop = asyncio.get_running_loop()
    async_q: asyncio.Queue = asyncio.Queue()

    def _produce() -> None:
        def on_token(chunk: str) -> None:
            loop.call_soon_threadsafe(async_q.put_nowait, ("token", chunk))
        try:
            plan = business_agent.analyse_stream(question, on_token=on_token)
            loop.call_soon_threadsafe(async_q.put_nowait, ("done", plan))
        except Exception as exc:
            loop.call_soon_threadsafe(async_q.put_nowait, ("error", exc))

    threading.Thread(target=_produce, daemon=True).start()

    while True:
        kind, value = await async_q.get()
        if kind == "token":
            await _push_event(sid, "background_token", {"text": value})
        elif kind == "done":
            return value  # type: ignore[return-value]
        elif kind == "error":
            raise value


async def _stream_via_thread(sid: str, messages: list, system: str, model: str) -> str:
    """
    Run provider.stream() (a sync generator) in a background thread, forwarding
    each text chunk as a 'token' SSE event to the session queue.

    Returns the full concatenated response text.
    """
    loop = asyncio.get_running_loop()
    async_q: asyncio.Queue = asyncio.Queue()

    def _produce() -> None:
        try:
            for chunk in provider.stream(messages, system, model):
                loop.call_soon_threadsafe(async_q.put_nowait, chunk)
        except Exception as exc:
            loop.call_soon_threadsafe(async_q.put_nowait, exc)
        finally:
            loop.call_soon_threadsafe(async_q.put_nowait, None)  # sentinel

    threading.Thread(target=_produce, daemon=True).start()

    full_text = ""
    while True:
        item = await async_q.get()
        if item is None:
            break
        if isinstance(item, Exception):
            raise item
        full_text += item
        await _push_event(sid, "token", {"text": item})

    return full_text


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
        # Business Agent decides: is this a follow-up or a fresh analysis?
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
    _sse_queues[sid] = asyncio.Queue()

    if route == "follow_up":
        state.append_message(sid, "user", question)
        # Note: we DON'T clear_job(sid) here because we need the current job's field_manifest
        background_tasks.add_task(_run_followup_task, sid, question)
    else:
        state.append_message(sid, "user", question)
        # Clear previous analysis data
        state.clear_job(sid)
        state.update(sid, last_summary_dict={}, last_charts=[], enriched_records=[])
        state.update_job(sid, question=question, status="pending")
        background_tasks.add_task(_run_business_agent_task, sid, question)

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

    if session_id not in _sse_queues:
        _sse_queues[session_id] = asyncio.Queue()

    state.update_job(session_id, status="running")

    background_tasks.add_task(
        _run_pipeline_task,
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

    if session_id not in _sse_queues:
        _sse_queues[session_id] = asyncio.Queue()

    background_tasks.add_task(_run_business_agent_task, session_id, original_question, instruction, current_plan)
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
    cost_estimate = _estimate_cost(call_count, field_count)
    warn_count    = call_count > config.CALL_COUNT_WARN_THRESHOLD
    warn_cost     = cost_estimate > config.COST_WARN_THRESHOLD_USD

    sample_call_ids = db.fetch_sample_call_ids(where_clause, limit=3)
    sample_transcripts = db.fetch_sample_transcripts(sample_call_ids)

    # Return pure JSON context to the frontend so it renders the gate properly
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
            # We parse this as a full SELECT to wrap the WHERE clause so sqlglot can parse it
            ast = sqlglot.parse_one(f"SELECT * FROM tbl WHERE {clause}")
            
            # Find all column references
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
        q = _sse_queues.get(session_id, asyncio.Queue())
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
    return JSONResponse({"ok": True}, status_code=204)


# ── Tasks ───────────────────────────────────────────────────────────────────

async def _run_business_agent_task(sid: str, question: str, refinement: str | None = None, current_plan: dict | None = None) -> None:
    try:
        t0 = time.perf_counter()
        if refinement:
            await _push_event(sid, "status", {"message": f"Refining your plan: {refinement[:60]}…"})
            plan = await asyncio.to_thread(
                business_agent.analyse_with_refinement, question, refinement, current_plan
            )
        else:
            await _push_event(sid, "status", {"message": "Reading your question and building an analysis plan…"})
            # Stream the first attempt — background_token events feed the UI indicator
            plan = await _stream_business_agent(sid, question)

        logger.info("[TIMING] Business Agent LLM: %.2fs", time.perf_counter() - t0)
        
        where_clause   = plan["where_clause"]
        system_prompt  = plan["system_prompt"]
        field_manifest = plan["field_manifest"]

        state.update_job(sid, where_clause=where_clause, system_prompt=system_prompt, field_manifest=field_manifest)

        await _push_event(sid, "status", {"message": "Fetching metadata and counting matched calls…"})
        count_result  = await asyncio.to_thread(db.count_calls, where_clause)
        call_count    = count_result["count"]
        field_count   = len(field_manifest.get("fields", []))
        cost_estimate = _estimate_cost(call_count, field_count)

        warn_count = call_count > config.CALL_COUNT_WARN_THRESHOLD
        warn_cost  = cost_estimate > config.COST_WARN_THRESHOLD_USD

        sample_call_ids = await asyncio.to_thread(db.fetch_sample_call_ids, where_clause, 3)
        sample_transcripts = await asyncio.to_thread(db.fetch_sample_transcripts, sample_call_ids)

        state.append_message(sid, "assistant", "", msg_type="approval_gate")

        gate_data = {
            "html": None,  # Legacy fallback flag
            "question": question,
            "where_clause": where_clause,
            "system_prompt": system_prompt,
            "field_manifest": field_manifest,
            "call_count": call_count,
            "cost_estimate": cost_estimate,
            "warn_count": warn_count,
            "warn_cost": warn_cost,
            "session_id": sid,
            "sample_transcripts": sample_transcripts,
        }
        await _push_event(sid, "gate", gate_data)

    except Exception as exc:
        logger.exception("Business Agent task failed")
        state.update_job(sid, status="failed")
        await _push_event(sid, "error", {"message": f"The analysis planner ran into an issue: {exc}"})


async def _run_pipeline_task(sid: str, question: str, where_clause: str, system_prompt: str, field_manifest: dict) -> None:
    try:
        t_pipeline = time.perf_counter()

        # ── 1. Count + fetch call IDs ──────────────────────────────────────────
        await _push_event(sid, "status", {"message": "Dispatching batch job…"})
        t = time.perf_counter()
        count_result = await asyncio.to_thread(db.count_calls, where_clause)
        call_count   = min(count_result["count"], 200)
        logger.info("[TIMING] DB count: %.2fs  (%d calls matched)", time.perf_counter() - t, call_count)

        call_ids = await asyncio.to_thread(db.fetch_call_ids, where_clause, call_count)

        # ── 2. Fetch metadata ──────────────────────────────────────────────────
        await _push_event(sid, "status", {"message": f"Fetching metadata for {call_count} calls…"})
        t = time.perf_counter()
        metadata = await asyncio.to_thread(db.fetch_call_metadata, call_ids)
        metadata_by_id = {m["call_id"]: m for m in metadata}
        state.update_job(sid, metadata=metadata)
        logger.info("[TIMING] Metadata fetch: %.2fs", time.perf_counter() - t)

        # ── 3. Batch LLM analysis ──────────────────────────────────────────────
        await _push_event(sid, "status", {"message": f"Analysing {call_count} call transcripts…"})
        t = time.perf_counter()
        batch_result = await asyncio.to_thread(batch.dispatch, call_ids, system_prompt, field_manifest)
        state.update_job(sid, job_id=batch_result["job_id"])
        logger.info("[TIMING] Batch dispatch: %.2fs", time.perf_counter() - t)

        # ── 4. Parse results ───────────────────────────────────────────────────
        await _push_event(sid, "status", {"message": "Parsing and structuring AI responses…"})
        t = time.perf_counter()
        summary, records = await asyncio.to_thread(parser.parse, batch_result["jsonl"], field_manifest, metadata_by_id)
        state.update(sid, last_summary_dict=summary, enriched_records=records)
        logger.info("[TIMING] Parser: %.2fs", time.perf_counter() - t)

        # ── 5. Data Agent → chart specs ────────────────────────────────────────
        await _push_event(sid, "status", {"message": "Generating visualizations via Data Agent…"})
        t = time.perf_counter()
        script = await asyncio.to_thread(data_agent.generate_script, question, field_manifest, records[:3])
        _, charts = await asyncio.to_thread(sandbox.execute_data_script, script, records)
        state.update(sid, last_charts=charts)
        logger.info("[TIMING] Data Agent + Sandbox: %.2fs", time.perf_counter() - t)

        # ── 7. Vision agent → executive summary (streamed) ────────────────────
        await _push_event(sid, "status", {"message": "Writing executive summary…"})
        t = time.perf_counter()

        field_names = [f["name"] for f in field_manifest.get("fields", [])]
        chart_descriptions = [
            f"Chart {i+1}: visualization of call analysis data ({', '.join(field_names[:3])})"
            for i in range(len(charts))
        ]
        chart_json_str = [json.dumps(c) for c in charts]
        va_messages = vision_agent.build_messages(question, chart_json_str, chart_descriptions)

        summary_text = await _stream_via_thread(
            sid, va_messages, vision_agent.SYSTEM_PROMPT, config.VISION_AGENT_MODEL
        )
        logger.info("[TIMING] Vision Agent LLM (streamed): %.2fs", time.perf_counter() - t)
        logger.info("[TIMING] Total pipeline: %.2fs", time.perf_counter() - t_pipeline)

        state.append_message(sid, "assistant", summary_text, msg_type="results")
        state.update_job(sid, status="complete")

        await _push_event(sid, "complete", {
            "html": None,
            "summary": summary_text,
            "charts": charts,
        })

    except Exception as exc:
        logger.exception("Pipeline task failed")
        state.update_job(sid, status="failed")
        await _push_event(sid, "error", {"message": str(exc)})

async def _run_followup_task(sid: str, question: str) -> None:
    try:
        t0 = time.perf_counter()
        s = state.get(sid)
        records = s.get("enriched_records", [])
        field_manifest = s.get("current_job", {}).get("field_manifest", {})

        if not records:
            raise ValueError("No records found in session to perform follow-up analysis.")

        await _push_event(sid, "status", {"message": "Analysing existing data for follow-up…"})

        # 1. Data Agent generates the Python script
        script = await asyncio.to_thread(data_agent.generate_script, question, field_manifest, records[:3])
        logger.info("[TIMING] Data Agent script generation: %.2fs", time.perf_counter() - t0)

        # 2. Sandbox executes the script
        t_exec = time.perf_counter()
        answer, charts = await asyncio.to_thread(sandbox.execute_data_script, script, records)
        logger.info("[TIMING] Sandbox execution: %.2fs", time.perf_counter() - t_exec)

        # Update state
        state.append_message(sid, "assistant", answer, msg_type="results")
        state.update(sid, last_charts=charts)

        # Complete event
        await _push_event(sid, "complete", {
            "summary": answer,
            "charts": charts,
        })

    except Exception as exc:
        logger.exception("Follow-up task failed")
        await _push_event(sid, "error", {"message": str(exc)})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=config.FLASK_PORT, reload=True)
