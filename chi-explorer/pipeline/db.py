"""
pipeline/db.py — Database stub.

When DB_ENABLED = False (home build), returns synthetic data and logs a warning.
When DB_ENABLED = True, swap in real DB queries here.
"""
from __future__ import annotations

import logging
import random

import config
from pipeline.synthetic import generate_call_metadata

logger = logging.getLogger(__name__)


def count_calls(where_clause: str) -> dict:
    """
    Return the number of calls matching the WHERE clause.

    Returns:
        {"count": int, "stubbed": bool}
    """
    if not config.DB_ENABLED:
        logger.warning(
            "[STUB] db.count_calls called with where_clause=%r — returning synthetic count",
            where_clause,
        )
        count = random.randint(80, 600)
        return {"count": count, "stubbed": True}

    # ── Real implementation (swap in when DB_ENABLED = True) ──────────────────
    import sqlite3
    try:
        conn = sqlite3.connect(config.SQLITE_DB_PATH)
        cursor = conn.cursor()
        query = f"SELECT count(*) FROM calls WHERE {where_clause}" if where_clause else "SELECT count(*) FROM calls"
        cursor.execute(query)
        count = cursor.fetchone()[0]
        return {"count": count, "stubbed": False}
    except Exception as e:
        logger.error("DB query failed: %s", e)
        return {"count": 0, "stubbed": False}
    finally:
        if 'conn' in locals():
            conn.close()


def fetch_call_metadata(call_ids: list) -> list:
    """
    Fetch call metadata records for the given call IDs.

    Returns:
        List of dicts with keys: call_id, agent_name, team_name, call_datetime,
        call_duration, call_queue, agent_leader_name, agent_team_id, region.
    """
    if not config.DB_ENABLED:
        logger.warning(
            "[STUB] db.fetch_call_metadata called for %d call IDs — returning synthetic metadata",
            len(call_ids),
        )
        return generate_call_metadata(call_ids)

    # ── Real implementation (swap in when DB_ENABLED = True) ──────────────────
    import sqlite3
    try:
        conn = sqlite3.connect(config.SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        placeholders = ",".join("?" * len(call_ids))
        query = f"SELECT * FROM calls WHERE call_id IN ({placeholders})"
        cursor.execute(query, call_ids)
        rows = cursor.fetchall()
        return [dict(row) for row in rows]
    except Exception as e:
        logger.error("DB metadata fetch failed: %s", e)
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def fetch_sample_transcripts(call_ids: list, limit: int = 3) -> list:
    """Fetch sample transcripts texts for the given call IDs."""
    if not config.DB_ENABLED:
        return [
            {"call_id": c, "text": "Synthetic mock transcript for call " + c} 
            for c in call_ids[:limit]
        ]
    
    import sqlite3
    try:
        conn = sqlite3.connect(config.SQLITE_DB_PATH)
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        ids = call_ids[:limit]
        placeholders = ",".join("?" * len(ids))
        query = f"SELECT call_id, transcript_text FROM transcripts WHERE call_id IN ({placeholders})"
        cursor.execute(query, ids)
        rows = cursor.fetchall()
        return [{"call_id": row["call_id"], "text": row["transcript_text"]} for row in rows]
    except Exception as e:
        logger.error("DB sample transcripts fetch failed: %s", e)
        return []
    finally:
        if 'conn' in locals():
            conn.close()

def fetch_sample_call_ids(where_clause: str, limit: int = 3) -> list:
    """Fetch sample call records for gate."""
    if not config.DB_ENABLED:
        import uuid
        return [uuid.uuid4().hex[:10].upper() for _ in range(limit)]
        
    import sqlite3
    try:
        conn = sqlite3.connect(config.SQLITE_DB_PATH)
        cursor = conn.cursor()
        query = f"SELECT call_id FROM calls WHERE {where_clause} LIMIT {limit}" if where_clause else f"SELECT call_id FROM calls LIMIT {limit}"
        cursor.execute(query)
        rows = cursor.fetchall()
        return [row[0] for row in rows]
    except Exception as e:
        logger.error("DB sample call ids fetch failed: %s", e)
        return []
    finally:
        if 'conn' in locals():
            conn.close()
