import asyncio
import logging
import threading
import time

import paramiko

import orchestrator.manager as manager
import storage.database as db
from storage.models import end_session, update_session_container
from proxy.handlers.auth import HoneypotServerInterface

log = logging.getLogger(__name__)

_DB_WRITE_TIMEOUT_S = 5
_CHUNK_SIZE = 4096
_POLL_S = 0.01


def handle_channel(channel: paramiko.Channel, server_iface: HoneypotServerInterface) -> None:
    session_id: str | None = None
    container_id: str | None = None

    try:
        session_id = _resolve_session_id(server_iface)
        if session_id is None:
            return

        container_id = manager.create_session_container(session_id)

        asyncio.run_coroutine_threadsafe(
            update_session_container(session_id, container_id),
            db.get_loop(),
        ).result(timeout=_DB_WRITE_TIMEOUT_S)

        _bridge(channel, server_iface, container_id)

    except Exception:
        log.exception(f"Error in channel handler (session={session_id!r})")
    finally:
        channel.close()
        if container_id:
            manager.destroy_container(container_id)
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
        log.exception("Failed to retrieve session_id")
        return None


def _bridge(
    channel: paramiko.Channel,
    server_iface: HoneypotServerInterface,
    container_id: str,
) -> None:
    if server_iface.exec_command:
        command = ["sh", "-c", server_iface.exec_command.decode("utf-8", errors="replace")]
        tty = False
    else:
        command = ["/bin/bash"]
        tty = True

    exec_id, sock = manager.open_exec(container_id, command, tty=tty)

    # sock is socket.SocketIO; ._sock is the underlying bidirectional socket
    raw = sock._sock
    raw.setblocking(True)

    server_iface._resize_callback = lambda w, h: manager.resize_exec(exec_id, w, h)

    stop = threading.Event()

    def attacker_to_container() -> None:
        try:
            while not stop.is_set():
                if channel.recv_ready():
                    data = channel.recv(_CHUNK_SIZE)
                    if not data:
                        break
                    raw.sendall(data)
                elif channel.closed:
                    break
                else:
                    time.sleep(_POLL_S)
        except Exception:
            pass
        finally:
            stop.set()

    def container_to_attacker() -> None:
        try:
            while not stop.is_set():
                data = raw.recv(_CHUNK_SIZE)
                if not data:
                    break
                channel.send(data)
        except Exception:
            pass
        finally:
            stop.set()

    t1 = threading.Thread(target=attacker_to_container, daemon=True)
    t2 = threading.Thread(target=container_to_attacker, daemon=True)
    t1.start()
    t2.start()
    stop.wait()

    try:
        sock.close()
    except Exception:
        pass
