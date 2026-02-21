import logging
import uuid
from datetime import datetime, timezone

from storage.database import get_db

log = logging.getLogger(__name__)


async def create_session(
    source_ip: str,
    source_port: int,
    username: str,
    password: str | None,
    auth_method: str,
) -> str:
    session_id = str(uuid.uuid4())
    doc = {
        "session_id": session_id,
        "source_ip": source_ip,
        "source_port": source_port,
        "username": username,
        "password": password,
        "auth_method": auth_method,
        "container_id": None,
        "started_at": datetime.now(timezone.utc),
        "ended_at": None,
        "duration_seconds": None,
        "status": "active",
    }

    await get_db().sessions.insert_one(doc)
    log.info(f"[session:{session_id[:8]}] {source_ip}:{source_port} auth={auth_method} user={username!r}")
    return session_id


async def update_session_container(session_id: str, container_id: str) -> None:
    await get_db().sessions.update_one(
        {"session_id": session_id},
        {"$set": {"container_id": container_id}},
    )


async def end_session(session_id: str) -> None:
    now = datetime.now(timezone.utc)

    session = await get_db().sessions.find_one({"session_id": session_id})
    if session is None:
        log.warning(f"end_session called for unknown session_id={session_id!r}")
        return

    started_at = session["started_at"]
    if started_at.tzinfo is None:
        started_at = started_at.replace(tzinfo=timezone.utc)

    duration = int((now - started_at).total_seconds())

    await get_db().sessions.update_one(
        {"session_id": session_id},
        {"$set": {
            "ended_at": now,
            "duration_seconds": duration,
            "status": "completed",
        }},
    )
    log.info(f"[session:{session_id[:8]}] ended — {duration}s")
