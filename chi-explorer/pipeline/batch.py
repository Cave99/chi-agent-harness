"""
pipeline/batch.py — Batch dispatch stub.

When BATCH_ENABLED = False (home build), generates synthetic JSONL directly
and returns immediately (no polling loop needed).
When BATCH_ENABLED = True, swap in real Bedrock batch dispatch here.
"""
from __future__ import annotations

import logging
import uuid

import config
from pipeline.synthetic import generate_jsonl

logger = logging.getLogger(__name__)


def dispatch(call_ids: list, system_prompt: str, field_manifest: dict) -> dict:
    """
    Dispatch a batch job (or stub equivalent) for the given call IDs.

    Returns:
        {"job_id": str, "status": "complete", "jsonl": str, "stubbed": bool}
    """
    if not config.BATCH_ENABLED:
        logger.warning(
            "[STUB] batch.dispatch called for %d calls — generating synthetic JSONL directly",
            len(call_ids),
        )
        job_id   = f"stub-job-{uuid.uuid4().hex[:8]}"
        jsonl    = generate_jsonl(field_manifest, count=len(call_ids), call_ids=call_ids)
        logger.warning("[STUB] Synthetic batch complete: job_id=%s, records=%d", job_id, len(call_ids))
        return {
            "job_id":  job_id,
            "status":  "complete",
            "jsonl":   jsonl,
            "stubbed": True,
        }

    # ── Real implementation (swap in when BATCH_ENABLED = True) ───────────────
    raise NotImplementedError("Real Bedrock batch not yet connected. Set BATCH_ENABLED=false in .env.")


def poll(job_id: str) -> dict:
    """
    Check the status of a batch job.

    Returns:
        {"job_id": str, "status": "complete"|"pending"|"failed"}
    """
    if not config.BATCH_ENABLED:
        logger.warning("[STUB] batch.poll called for job_id=%r — returning complete immediately", job_id)
        return {"job_id": job_id, "status": "complete"}

    raise NotImplementedError("Real Bedrock batch not yet connected. Set BATCH_ENABLED=false in .env.")
