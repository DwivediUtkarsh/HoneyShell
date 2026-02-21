import asyncio
import logging
import time

import paramiko

import storage.database as db
from storage.models import end_session
from proxy.handlers.auth import HoneypotServerInterface

log = logging.getLogger(__name__)

_DB_WRITE_TIMEOUT_S = 5
_DRAIN_POLL_S = 0.1


def handle_channel(channel: paramiko.Channel, server_iface: HoneypotServerInterface) -> None:
    session_id: str | None = None

    try:
        session_id = _resolve_session_id(server_iface)
        _drain_channel(channel)
    except Exception:
        log.exception(f"Unexpected error in channel handler (session={session_id!r})")
    finally:
        channel.close()
        if session_id:
            asyncio.run_coroutine_threadsafe(
                end_session(session_id), db.get_loop()
            ).result(timeout=_DB_WRITE_TIMEOUT_S)


def _resolve_session_id(server_iface: HoneypotServerInterface) -> str | None:
    if server_iface._session_future is None:
        log.warning("No session future — auth may not have fired.")
        return None

    try:
        return server_iface._session_future.result(timeout=_DB_WRITE_TIMEOUT_S)
    except Exception:
        log.exception("Failed to retrieve session_id from DB future")
        return None


def _drain_channel(channel: paramiko.Channel) -> None:
    transport = channel.get_transport()

    while True:
        if channel.recv_ready():
            data = channel.recv(4096)
            if not data:
                break

        if channel.closed:
            break

        if transport is None or not transport.is_active():
            break

        time.sleep(_DRAIN_POLL_S)
