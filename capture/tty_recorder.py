import asyncio
import base64
import logging
from datetime import datetime, timezone

from storage.database import get_db, get_loop

log = logging.getLogger(__name__)


async def _record(session_id: str, data: bytes, direction: str) -> None:
    await get_db().keystrokes.insert_one({
        "session_id": session_id,
        "timestamp": datetime.now(timezone.utc),
        "data": base64.b64encode(data).decode(),
        "direction": direction,
    })


def log_keystroke(session_id: str, data: bytes, direction: str) -> None:
    asyncio.run_coroutine_threadsafe(_record(session_id, data, direction), get_loop())
