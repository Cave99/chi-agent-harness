"""
session/state.py — In-memory session state manager.

Stores per-session state keyed by Flask session ID.
No disk persistence for the home build.
"""
from __future__ import annotations

import threading
import uuid
from typing import Optional

_store: dict = {}
_lock = threading.Lock()


def get(session_id: str) -> dict:
    """Return the state dict for a session, creating it if needed."""
    with _lock:
        if session_id not in _store:
            _store[session_id] = _empty_state()
        return _store[session_id]


def update(session_id: str, **kwargs) -> None:
    """Merge kwargs into the top-level state for a session."""
    with _lock:
        state = _store.setdefault(session_id, _empty_state())
        state.update(kwargs)


def update_job(session_id: str, **kwargs) -> None:
    """Merge kwargs into the current_job sub-dict."""
    with _lock:
        state = _store.setdefault(session_id, _empty_state())
        state["current_job"].update(kwargs)


def append_message(session_id: str, role: str, content: str, msg_type: str = "text") -> None:
    """Append a message to the conversation history."""
    with _lock:
        state = _store.setdefault(session_id, _empty_state())
        state["messages"].append({
            "role": role,
            "content": content,
            "type": msg_type,  # "text" | "approval_gate" | "results"
        })


def clear_job(session_id: str) -> None:
    """Reset the current job to a clean state."""
    with _lock:
        state = _store.setdefault(session_id, _empty_state())
        state["current_job"] = _empty_job()


def new_session_id() -> str:
    return str(uuid.uuid4())


def _empty_state() -> dict:
    return {
        "messages":          [],
        "current_job":       _empty_job(),
        "last_summary_dict": {},
        "enriched_records":  [],
        "last_charts":       [],
    }


def _empty_job() -> dict:
    return {
        "question":      "",
        "where_clause":  "",
        "system_prompt": "",
        "field_manifest": {},
        "job_id":        "",
        "status":        "idle",   # idle | pending | complete | failed
        "metadata":      [],
    }
