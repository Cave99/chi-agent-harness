import asyncio
import logging
from typing import Dict, Optional

logger = logging.getLogger(__name__)

class SSEManager:
    def __init__(self):
        self._queues: Dict[str, asyncio.Queue] = {}

    def ensure_queue(self, session_id: str) -> asyncio.Queue:
        if session_id not in self._queues:
            logger.info(f"Creating SSE queue for session {session_id}")
            self._queues[session_id] = asyncio.Queue()
        return self._queues[session_id]

    async def push_event(self, session_id: str, event: str, data: dict) -> None:
        q = self._queues.get(session_id)
        if q:
            await q.put({"event": event, "data": data})
        else:
            logger.debug(f"Attempted to push event to missing queue: {session_id}")

    def remove_session(self, session_id: str) -> None:
        if session_id in self._queues:
            logger.info(f"Removing SSE queue for session {session_id}")
            del self._queues[session_id]

    def get_queue(self, session_id: str) -> Optional[asyncio.Queue]:
        return self._queues.get(session_id)

sse_manager = SSEManager()
