import asyncio
import logging
import os
from threading import Thread

import motor.motor_asyncio

log = logging.getLogger(__name__)

_loop: asyncio.AbstractEventLoop | None = None
_db: motor.motor_asyncio.AsyncIOMotorDatabase | None = None


def _run_loop(loop: asyncio.AbstractEventLoop) -> None:
    asyncio.set_event_loop(loop)
    loop.run_forever()


def init(mongo_uri: str | None = None, db_name: str | None = None) -> None:
    global _loop, _db

    mongo_uri = mongo_uri or os.getenv("MONGO_URI", "mongodb://localhost:27017")
    db_name = db_name or os.getenv("MONGO_DB", "honeyshell")

    _loop = asyncio.new_event_loop()
    Thread(target=_run_loop, args=(_loop,), daemon=True, name="db-event-loop").start()

    client = motor.motor_asyncio.AsyncIOMotorClient(mongo_uri)
    _db = client[db_name]

    log.info(f"MongoDB connected — {mongo_uri}/{db_name}")


def get_db() -> motor.motor_asyncio.AsyncIOMotorDatabase:
    if _db is None:
        raise RuntimeError("Database not initialised. Call storage.database.init() first.")
    return _db


def get_loop() -> asyncio.AbstractEventLoop:
    if _loop is None:
        raise RuntimeError("Event loop not initialised. Call storage.database.init() first.")
    return _loop
