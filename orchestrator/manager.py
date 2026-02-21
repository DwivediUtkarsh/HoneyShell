import logging
import os
import threading

import docker
import docker.errors

log = logging.getLogger(__name__)

_HONEYPOT_IMAGE = os.getenv("HONEYPOT_IMAGE", "honeyshell-ubuntu")
_HONEYPOT_NETWORK = os.getenv("HONEYPOT_NETWORK", "honeypot-net")
_CPU_LIMIT = float(os.getenv("CONTAINER_CPU_LIMIT", "0.5"))
_MEMORY_LIMIT = os.getenv("CONTAINER_MEMORY_LIMIT", "256m")
_TTL_MINUTES = int(os.getenv("CONTAINER_TTL_MINUTES", "30"))
_FAKE_HOSTNAME = os.getenv("HONEYPOT_HOSTNAME", "web-prod-01")
_FAKE_HOSTS = {
    "db-internal": "10.0.1.10",
    "redis-internal": "10.0.1.11",
    "api-internal": "10.0.1.12",
}

_client: docker.DockerClient | None = None


def init() -> None:
    global _client
    _client = docker.from_env()
    _ensure_network()
    log.info("Docker client initialised")


def _ensure_network() -> None:
    try:
        _client.networks.get(_HONEYPOT_NETWORK)
    except docker.errors.NotFound:
        _client.networks.create(
            _HONEYPOT_NETWORK,
            driver="bridge",
            internal=True,
        )
        log.info(f"Created isolated network {_HONEYPOT_NETWORK!r}")


def create_session_container(session_id: str) -> str:
    container = _client.containers.run(
        _HONEYPOT_IMAGE,
        command="sleep infinity",
        detach=True,
        stdin_open=True,
        name=f"honeyshell-{session_id[:8]}",
        hostname=_FAKE_HOSTNAME,
        extra_hosts=_FAKE_HOSTS,
        network=_HONEYPOT_NETWORK,
        cpu_period=100000,
        cpu_quota=int(_CPU_LIMIT * 100000),
        mem_limit=_MEMORY_LIMIT,
        memswap_limit=_MEMORY_LIMIT,
        privileged=False,
        labels={"honeyshell.session_id": session_id},
    )
    log.info(f"[session:{session_id[:8]}] container {container.short_id} started")
    _schedule_auto_destruct(container.id, session_id)
    return container.id


def open_exec(
    container_id: str,
    command: list[str],
    tty: bool = True,
    width: int = 80,
    height: int = 24,
) -> tuple[str, object]:
    exec_id = _client.api.exec_create(
        container_id,
        command,
        stdin=True,
        tty=tty,
        environment={"TERM": "xterm-256color", "LANG": "en_US.UTF-8", "HOME": "/root"},
    )["Id"]

    sock = _client.api.exec_start(exec_id, socket=True, tty=tty)

    if tty:
        _client.api.exec_resize(exec_id, height=height, width=width)

    return exec_id, sock


def resize_exec(exec_id: str, width: int, height: int) -> None:
    try:
        _client.api.exec_resize(exec_id, height=height, width=width)
    except Exception:
        pass


def destroy_container(container_id: str) -> None:
    try:
        c = _client.containers.get(container_id)
        c.stop(timeout=5)
        c.remove(force=True)
        log.info(f"Container {container_id[:12]} destroyed")
    except docker.errors.NotFound:
        pass
    except Exception:
        log.exception(f"Failed to destroy container {container_id[:12]}")


def _schedule_auto_destruct(container_id: str, session_id: str) -> None:
    def _run() -> None:
        import time
        time.sleep(_TTL_MINUTES * 60)
        log.warning(f"[session:{session_id[:8]}] TTL expired — destroying container")
        destroy_container(container_id)

    threading.Thread(target=_run, daemon=True, name=f"ttl-{session_id[:8]}").start()
