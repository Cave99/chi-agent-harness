import asyncio
import logging
import time
import json
import threading
from typing import Optional

from agents import business_agent, vision_agent, data_agent
from pipeline import batch, db, parser, provider, sandbox
import session.state as state
import config
from services.sse_manager import sse_manager

logger = logging.getLogger(__name__)

def estimate_cost(call_count: int, field_count: int) -> float:
    """Rough input token cost estimate at ~$3 per million tokens."""
    tokens_per_call = 800 + field_count * 50
    total_tokens = call_count * tokens_per_call
    return round(total_tokens / 1_000_000 * 3.0, 2)

async def stream_business_agent(sid: str, question: str) -> dict:
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

    char_count = 0
    last_status_at = 0
    STATUS_INTERVAL = 100  # push a status update every N chars

    while True:
        kind, value = await async_q.get()
        if kind == "token":
            await sse_manager.push_event(sid, "background_token", {"text": value})
            char_count += len(value)
            if char_count - last_status_at >= STATUS_INTERVAL:
                last_status_at = char_count
                await sse_manager.push_event(
                    sid, "status",
                    {"message": f"Building analysis plan… ({char_count} chars)"}
                )
        elif kind == "done":
            await sse_manager.push_event(sid, "status", {"message": "Validating and parsing plan…"})
            return value  # type: ignore[return-value]
        elif kind == "error":
            raise value

async def stream_via_thread(sid: str, messages: list, system: str, model: str) -> str:
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
        await sse_manager.push_event(sid, "token", {"text": item})

    return full_text

async def run_business_agent_task(sid: str, question: str, refinement: str | None = None, current_plan: dict | None = None) -> None:
    try:
        t0 = time.perf_counter()
        if refinement:
            await sse_manager.push_event(sid, "status", {"message": f"Refining your plan: {refinement[:60]}…"})
            plan = await asyncio.to_thread(
                business_agent.analyse_with_refinement, question, refinement, current_plan
            )
        else:
            await sse_manager.push_event(sid, "status", {"message": "Reading your question and building an analysis plan…"})
            # Stream the first attempt — background_token events feed the UI indicator
            plan = await stream_business_agent(sid, question)

        logger.info("[TIMING] Business Agent LLM: %.2fs", time.perf_counter() - t0)
        
        where_clause   = plan["where_clause"]
        system_prompt  = plan["system_prompt"]
        field_manifest = plan["field_manifest"]

        state.update_job(sid, where_clause=where_clause, system_prompt=system_prompt, field_manifest=field_manifest)

        await sse_manager.push_event(sid, "status", {"message": "Fetching metadata and counting matched calls…"})
        count_result  = await asyncio.to_thread(db.count_calls, where_clause)
        call_count    = count_result["count"]
        field_count   = len(field_manifest.get("fields", []))
        cost_estimate = estimate_cost(call_count, field_count)

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
        await sse_manager.push_event(sid, "gate", gate_data)

    except Exception as exc:
        logger.exception("Business Agent task failed")
        state.update_job(sid, status="failed")
        await sse_manager.push_event(sid, "error", {"message": f"The analysis planner ran into an issue: {exc}"})


async def run_pipeline_task(sid: str, question: str, where_clause: str, system_prompt: str, field_manifest: dict) -> None:
    try:
        t_pipeline = time.perf_counter()

        # ── 1. Count + fetch call IDs ──────────────────────────────────────────
        await sse_manager.push_event(sid, "status", {"message": "Dispatching batch job…"})
        t = time.perf_counter()
        count_result = await asyncio.to_thread(db.count_calls, where_clause)
        call_count   = min(count_result["count"], 200)
        logger.info("[TIMING] DB count: %.2fs  (%d calls matched)", time.perf_counter() - t, call_count)

        call_ids = await asyncio.to_thread(db.fetch_call_ids, where_clause, call_count)

        # ── 2. Fetch metadata ──────────────────────────────────────────────────
        await sse_manager.push_event(sid, "status", {"message": f"Fetching metadata for {call_count} calls…"})
        t = time.perf_counter()
        metadata = await asyncio.to_thread(db.fetch_call_metadata, call_ids)
        metadata_by_id = {m["call_id"]: m for m in metadata}
        state.update_job(sid, metadata=metadata)
        logger.info("[TIMING] Metadata fetch: %.2fs", time.perf_counter() - t)

        # ── 3. Batch LLM analysis ──────────────────────────────────────────────
        await sse_manager.push_event(sid, "status", {"message": f"Analysing {call_count} call transcripts…"})
        t = time.perf_counter()
        batch_result = await asyncio.to_thread(batch.dispatch, call_ids, system_prompt, field_manifest)
        state.update_job(sid, job_id=batch_result["job_id"])
        logger.info("[TIMING] Batch dispatch: %.2fs", time.perf_counter() - t)

        # ── 4. Parse results ───────────────────────────────────────────────────
        await sse_manager.push_event(sid, "status", {"message": "Parsing and structuring AI responses…"})
        t = time.perf_counter()
        summary, records = await asyncio.to_thread(parser.parse, batch_result["jsonl"], field_manifest, metadata_by_id)
        state.update(sid, last_summary_dict=summary, enriched_records=records)
        logger.info("[TIMING] Parser: %.2fs", time.perf_counter() - t)

        # ── 5. Data Agent → chart specs ────────────────────────────────────────
        await sse_manager.push_event(sid, "status", {"message": "Generating visualizations via Data Agent…"})
        t = time.perf_counter()
        script = await asyncio.to_thread(data_agent.generate_script, question, field_manifest, records[:3])
        _, charts = await asyncio.to_thread(sandbox.execute_data_script, script, records)
        state.update(sid, last_charts=charts)
        logger.info("[TIMING] Data Agent + Sandbox: %.2fs", time.perf_counter() - t)

        # ── 7. Vision agent → executive summary (streamed) ────────────────────
        await sse_manager.push_event(sid, "status", {"message": "Writing executive summary…"})
        t = time.perf_counter()

        field_names = [f["name"] for f in field_manifest.get("fields", [])]
        chart_descriptions = [
            f"Chart {i+1}: visualization of call analysis data ({', '.join(field_names[:3])})"
            for i in range(len(charts))
        ]
        chart_json_str = [json.dumps(c) for c in charts]
        va_messages = vision_agent.build_messages(question, chart_json_str, chart_descriptions)

        summary_text = await stream_via_thread(
            sid, va_messages, vision_agent.SYSTEM_PROMPT, config.VISION_AGENT_MODEL
        )
        logger.info("[TIMING] Vision Agent LLM (streamed): %.2fs", time.perf_counter() - t)
        logger.info("[TIMING] Total pipeline: %.2fs", time.perf_counter() - t_pipeline)

        state.append_message(sid, "assistant", summary_text, msg_type="results")
        state.update_job(sid, status="complete")

        await sse_manager.push_event(sid, "complete", {
            "html": None,
            "summary": summary_text,
            "charts": charts,
        })

    except Exception as exc:
        logger.exception("Pipeline task failed")
        state.update_job(sid, status="failed")
        await sse_manager.push_event(sid, "error", {"message": str(exc)})

async def run_followup_task(sid: str, question: str) -> None:
    try:
        t0 = time.perf_counter()
        s = state.get(sid)
        records = s.get("enriched_records", [])
        field_manifest = s.get("current_job", {}).get("field_manifest", {})

        if not records:
            raise ValueError("No records found in session to perform follow-up analysis.")

        await sse_manager.push_event(sid, "status", {"message": "Analysing existing data for follow-up…"})

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
        await sse_manager.push_event(sid, "complete", {
            "summary": answer,
            "charts": charts,
        })

    except Exception as exc:
        logger.exception("Follow-up task failed")
        await sse_manager.push_event(sid, "error", {"message": str(exc)})
