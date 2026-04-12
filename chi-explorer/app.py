"""
app.py — Flask entry point for Chi Explorer.

Routes:
  GET  /                  → chat UI
  POST /chat              → submit a question (triggers Business Agent + approval gate)
  POST /refine            → refine the current plan with an instruction
  POST /run               → approve and run the full pipeline
  GET  /stream/<sid>      → SSE stream for real-time status updates
  POST /reset             → clear session and start fresh
"""
from __future__ import annotations

import json
import logging
import queue
import threading
import time
import uuid

from flask import (
    Flask, Response, jsonify, render_template,
    request, session,
)

import config
from agents import business_agent, briefing_agent, code_agent, vision_agent
from pipeline import batch, db, executor, parser
from pipeline.executor import LintError, ExecutionError
import session.state as state

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.secret_key = config.FLASK_SECRET_KEY

# Per-session SSE queues: {session_id: queue.Queue}
_sse_queues: dict = {}
_sse_lock = threading.Lock()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _get_or_create_session_id() -> str:
    if "id" not in session:
        session["id"] = str(uuid.uuid4())
    return session["id"]


def _push_event(session_id: str, event: str, data: dict) -> None:
    """Push a server-sent event to the session's queue."""
    with _sse_lock:
        q = _sse_queues.get(session_id)
    if q:
        q.put({"event": event, "data": data})


def _estimate_cost(call_count: int, field_count: int) -> float:
    """Rough input token cost estimate at ~$3 per million tokens."""
    tokens_per_call = 800 + field_count * 50   # system prompt + transcript
    total_tokens = call_count * tokens_per_call
    return round(total_tokens / 1_000_000 * 3.0, 2)


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    sid = _get_or_create_session_id()
    s = state.get(sid)
    return render_template("chat.html", messages=s["messages"], session_id=sid)


@app.route("/chat", methods=["POST"])
def chat():
    """
    User submitted a question.
    Immediately returns {ok, session_id} and kicks off the Business Agent
    in a background thread. Progress is streamed via SSE:
      - 'status' events for progress messages
      - 'gate'   event with the rendered approval_gate HTML
      - 'error'  event on failure
    """
    sid = _get_or_create_session_id()
    question = request.form.get("question", "").strip()

    if not question:
        return jsonify({"error": "Question cannot be empty."}), 400

    state.append_message(sid, "user", question)
    state.clear_job(sid)
    state.update_job(sid, question=question, status="pending")

    # Create SSE queue for this session (shared with /run pipeline)
    with _sse_lock:
        _sse_queues[sid] = queue.Queue()

    thread = threading.Thread(
        target=_run_business_agent_thread,
        args=(sid, question),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "session_id": sid})


@app.route("/run", methods=["POST"])
def run_pipeline():
    """
    User approved the batch. Kick off the full pipeline in a background thread
    and return immediately so the SSE stream can report progress.
    """
    sid = _get_or_create_session_id()
    s   = state.get(sid)
    job = s["current_job"]

    if job["status"] not in ("pending", "failed"):
        return jsonify({"error": "No pending job."}), 400

    # Create SSE queue for this session
    with _sse_lock:
        _sse_queues[sid] = queue.Queue()

    state.update_job(sid, status="running")

    thread = threading.Thread(
        target=_run_pipeline_thread,
        args=(sid, job["question"], job["where_clause"],
              job["system_prompt"], job["field_manifest"]),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "session_id": sid})


@app.route("/refine", methods=["POST"])
def refine_plan():
    """
    User wants to refine the current analysis plan via AI.
    Takes 'instruction' from the form and re-runs the Business Agent
    with the original question + current plan + refinement as context.
    Streams a new 'gate' event via SSE to replace the current approval gate.
    """
    sid = _get_or_create_session_id()
    instruction = request.form.get("instruction", "").strip()

    if not instruction:
        return jsonify({"error": "Instruction cannot be empty."}), 400

    s = state.get(sid)
    job = s.get("current_job", {})
    original_question = job.get("question", "")

    if not original_question:
        return jsonify({"error": "No active analysis plan to refine."}), 400

    # Pass the current plan as context so the agent makes targeted changes
    current_plan = {
        "where_clause": job.get("where_clause", ""),
        "system_prompt": job.get("system_prompt", ""),
        "field_manifest": job.get("field_manifest", {}),
    } if job.get("where_clause") is not None else None

    # Re-create SSE queue
    with _sse_lock:
        _sse_queues[sid] = queue.Queue()

    thread = threading.Thread(
        target=_run_business_agent_thread,
        args=(sid, original_question, instruction, current_plan),
        daemon=True,
    )
    thread.start()

    return jsonify({"ok": True, "session_id": sid})


@app.route("/patch", methods=["POST"])
def patch_plan():
    """
    Apply manual edits to the current plan without re-running the Business Agent.
    Accepts JSON body with any subset of: where_clause, system_prompt, field_manifest.
    Regenerates the approval gate HTML and streams it via a one-shot SSE queue.
    """
    sid = _get_or_create_session_id()
    data = request.get_json(force=True, silent=True) or {}

    s = state.get(sid)
    job = s.get("current_job", {})
    if not job.get("question"):
        return jsonify({"error": "No active job to patch."}), 400

    # Merge incoming changes over the current job
    updates = {}
    if "where_clause" in data:
        updates["where_clause"] = data["where_clause"]
    if "system_prompt" in data:
        updates["system_prompt"] = data["system_prompt"]
    if "field_manifest" in data:
        fm = data["field_manifest"]
        if not isinstance(fm, dict) or "fields" not in fm:
            return jsonify({"error": "field_manifest must be a dict with a 'fields' key."}), 400
        updates["field_manifest"] = fm

    if not updates:
        return jsonify({"error": "No changes provided."}), 400

    state.update_job(sid, **updates)
    s = state.get(sid)
    job = s["current_job"]

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

    gate_html = render_template(
        "approval_gate.html",
        question=question,
        where_clause=where_clause,
        system_prompt=system_prompt,
        field_manifest=field_manifest,
        call_count=call_count,
        cost_estimate=cost_estimate,
        warn_count=warn_count,
        warn_cost=warn_cost,
        session_id=sid,
        sample_transcripts=sample_transcripts,
    )
    return jsonify({"ok": True, "html": gate_html})


# Known columns for SQL linting
_KNOWN_COLUMNS = {
    "call_id", "agent_name", "team_name", "call_datetime",
    "call_duration", "call_queue", "agent_leader_name", "agent_team_id",
}

@app.route("/validate-sql", methods=["POST"])
def validate_sql():
    """
    Lightweight server-side SQL WHERE-clause linter.
    Returns {ok: bool, errors: [str]}.
    """
    data = request.get_json(force=True, silent=True) or {}
    clause = (data.get("where_clause") or "").strip()

    errors = []
    if clause:
        import re
        # Find all word tokens that look like column references (lowercase_word not in SQL keywords)
        SQL_KEYWORDS = {
            "and", "or", "not", "in", "is", "null", "like", "between", "true", "false",
            "current_date", "current_timestamp", "interval", "date", "where", "select",
            "from", "having", "group", "by", "order", "limit", "offset", "cast", "as",
        }
        # Extract bare identifiers (no quotes, no digits-only)
        tokens = re.findall(r"\b([a-zA-Z_][a-zA-Z0-9_]*)\b", clause)
        for tok in tokens:
            lower = tok.lower()
            if lower in SQL_KEYWORDS:
                continue
            # If it looks like a column name (contains underscore or all alpha) and
            # is not a known column, flag it
            if lower not in _KNOWN_COLUMNS and ("_" in lower or lower.isalpha()):
                errors.append(f"Unknown column or keyword: '{tok}'")

        if "select" in clause.lower():
            errors.append("WHERE clause must not contain SELECT")
        if "from " in clause.lower():
            errors.append("WHERE clause must not contain FROM")

    return jsonify({"ok": len(errors) == 0, "errors": errors})



@app.route("/stream/<session_id>")
def stream(session_id: str):
    """SSE endpoint — streams pipeline progress events to the client."""
    def generate():
        with _sse_lock:
            q = _sse_queues.get(session_id, queue.Queue())

        while True:
            try:
                item = q.get(timeout=30)
                event = item["event"]
                data  = json.dumps(item["data"])
                yield f"event: {event}\ndata: {data}\n\n"
                if event in ("complete", "gate", "error"):
                    break
            except queue.Empty:
                yield "event: ping\ndata: {}\n\n"

    return Response(generate(), mimetype="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no",
                             "Connection": "keep-alive"})


@app.route("/reset", methods=["POST"])
def reset():
    sid = _get_or_create_session_id()
    state.update(sid, messages=[], current_job={}, last_summary_dict={}, last_charts=[])
    return ("", 204)


# ── Business Agent thread ────────────────────────────────────────────────────

def _run_business_agent_thread(
    sid: str,
    question: str,
    refinement: str | None = None,
    current_plan: dict | None = None,
) -> None:
    """
    Runs the Business Agent in a background thread and pushes SSE events:
      status → progress
      gate   → rendered approval_gate.html fragment
      error  → failure message
    """
    def push(event, **data):
        _push_event(sid, event, data)

    try:
        if refinement:
            push("status", message=f"Refining your plan: {refinement[:60]}…")
            plan = business_agent.analyse_with_refinement(question, refinement, current_plan)
        else:
            push("status", message="Reading your question and building an analysis plan…")
            plan = business_agent.analyse(question)

        where_clause   = plan["where_clause"]
        system_prompt  = plan["system_prompt"]
        field_manifest = plan["field_manifest"]

        state.update_job(
            sid,
            where_clause=where_clause,
            system_prompt=system_prompt,
            field_manifest=field_manifest,
        )

        # DB stub count
        push("status", message="Fetching metadata and counting matched calls…")
        count_result  = db.count_calls(where_clause)
        call_count    = count_result["count"]
        field_count   = len(field_manifest.get("fields", []))
        cost_estimate = _estimate_cost(call_count, field_count)

        warn_count = call_count > config.CALL_COUNT_WARN_THRESHOLD
        warn_cost  = cost_estimate > config.COST_WARN_THRESHOLD_USD

        sample_call_ids = db.fetch_sample_call_ids(where_clause, limit=3)
        sample_transcripts = db.fetch_sample_transcripts(sample_call_ids)

        state.append_message(sid, "assistant", "", msg_type="approval_gate")

        with app.app_context():
            gate_html = render_template(
                "approval_gate.html",
                question=question,
                where_clause=where_clause,
                system_prompt=system_prompt,
                field_manifest=field_manifest,
                call_count=call_count,
                cost_estimate=cost_estimate,
                warn_count=warn_count,
                warn_cost=warn_cost,
                session_id=sid,
                sample_transcripts=sample_transcripts,
            )

        push("gate", html=gate_html)

    except Exception as exc:
        logger.exception("Business Agent thread failed for session %s", sid)
        state.update_job(sid, status="failed")
        push("error", message=f"The analysis planner ran into an issue: {exc}")


# ── Pipeline thread ───────────────────────────────────────────────────────────

def _run_pipeline_thread(
    sid: str,
    question: str,
    where_clause: str,
    system_prompt: str,
    field_manifest: dict,
) -> None:
    """
    Full pipeline:
    synthetic batch → parser → briefing agent → code agent → lint/execute → vision
    """
    def push(event, **data):
        _push_event(sid, event, data)

    try:
        # Step 1: Generate call IDs (stub uses sequential IDs)
        push("status", message="Dispatching batch job…")
        count_result = db.count_calls(where_clause)
        call_count   = min(count_result["count"], 200)  # cap for synthetic perf

        # Stub IDs — in real build these come from the DB query
        import uuid as _uuid
        call_ids = [_uuid.uuid4().hex[:10].upper() for _ in range(call_count)]

        # Step 2: Fetch metadata
        push("status", message=f"Fetching metadata for {call_count} calls…")
        metadata = db.fetch_call_metadata(call_ids)
        metadata_by_id = {m["call_id"]: m for m in metadata}
        state.update_job(sid, metadata=metadata)

        # Step 3: Batch dispatch (stub generates synthetic JSONL)
        push("status", message=f"Analysing {call_count} call transcripts with AI (synthetic data)…")
        batch_result = batch.dispatch(call_ids, system_prompt, field_manifest)
        state.update_job(sid, job_id=batch_result["job_id"])

        # Step 4: Parse JSONL
        push("status", message="Parsing and structuring AI responses…")
        summary = parser.parse(batch_result["jsonl"], field_manifest, metadata_by_id)
        state.update(sid, last_summary_dict=summary)

        # Step 5: Briefing Agent
        push("status", message="Briefing chart generation agent…")
        brief_text = briefing_agent.brief(question, summary)

        # Step 6: Code Agent → lint → execute (up to 3 retries)
        push("status", message="Generating visualisations…")
        script = code_agent.generate_script(brief_text, summary)
        charts = _run_with_lint_retry(script, summary, sid, brief_text, push)

        state.update(sid, last_charts=charts)

        # Step 7: Vision Agent
        push("status", message="Writing executive summary…")
        # Build chart descriptions from field manifest for the vision agent
        field_names = [f["name"] for f in field_manifest.get("fields", [])]
        chart_descriptions = [
            f"Chart {i+1}: visualisation of call analysis data ({', '.join(field_names[:3])})"
            for i in range(len(charts))
        ]
        summary_text = vision_agent.analyse(question, charts, chart_descriptions)

        # Append final results message
        state.append_message(sid, "assistant", summary_text, msg_type="results")
        state.update_job(sid, status="complete")

        # Render the results fragment
        results_html = render_template(
            "results.html",
            summary_text=summary_text,
            charts=charts,
            session_id=sid,
        )
        push("complete", html=results_html, summary=summary_text)

    except Exception as exc:
        logger.exception("Pipeline failed for session %s", sid)
        state.update_job(sid, status="failed")
        push("error", message=str(exc))


def _run_with_lint_retry(
    script: str,
    summary: dict,
    sid: str,
    brief_text: str,
    push,
    max_retries: int = 3,
) -> list:
    """Attempt to lint and execute the script, asking the Code Agent to fix on failure."""
    last_error = None
    current_script = script

    for attempt in range(max_retries):
        try:
            executor.lint(current_script)
            charts = executor.execute(current_script, summary)
            if not charts:
                raise ExecutionError("Script executed but produced no charts.")
            return charts
        except (LintError, ExecutionError, executor.TimeoutError) as exc:
            last_error = exc
            logger.warning("Script attempt %d failed: %s", attempt + 1, exc)
            push("status", message=f"Fixing chart script (attempt {attempt + 1}/{max_retries})…")

            if attempt < max_retries - 1:
                # Ask Code Agent to fix the script
                fix_message = (
                    f"Your previous script had an error:\n{exc}\n\n"
                    f"Here is the script that failed:\n```python\n{current_script}\n```\n\n"
                    f"Fix ONLY the error above. Output ONLY the corrected raw Python code."
                )
                try:
                    current_script = code_agent.generate_script(
                        brief_text + "\n\n" + fix_message,
                        summary,
                    )
                except Exception as gen_exc:
                    logger.warning("Code Agent fix attempt failed: %s", gen_exc)

    raise ExecutionError(
        f"Chart generation failed after {max_retries} attempts. Last error: {last_error}"
    )


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=config.FLASK_PORT, debug=config.FLASK_DEBUG, use_reloader=False)
