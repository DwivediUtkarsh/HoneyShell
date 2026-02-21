import hashlib
import logging
from datetime import datetime, timezone

import motor.motor_asyncio

from storage.database import get_db

log = logging.getLogger(__name__)


async def record_upload(session_id: str, filename: str, content: bytes) -> None:
    db = get_db()

    bucket = motor.motor_asyncio.AsyncIOMotorGridFSBucket(db)
    file_id = await bucket.upload_from_stream(filename, content)

    await db.uploads.insert_one({
        "session_id": session_id,
        "filename": filename,
        "size_bytes": len(content),
        "content_hash": hashlib.sha256(content).hexdigest(),
        "uploaded_at": datetime.now(timezone.utc),
        "file_ref": file_id,
    })

    log.info(
        f"[session:{session_id[:8]}] upload captured: "
        f"{filename!r} {len(content)}B sha256={hashlib.sha256(content).hexdigest()[:16]}…"
    )
