import logging
import os
import socket
import threading

import paramiko
from dotenv import load_dotenv

import storage.database as db
import orchestrator.manager as manager
from proxy.handlers.auth import HoneypotServerInterface
from proxy.handlers.sftp import HoneypotSFTPServerInterface
from proxy.handlers.shell import handle_channel

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)
log = logging.getLogger(__name__)

_HOST_KEY_PATH = os.getenv("HOST_KEY_PATH", "proxy/keys/host_rsa")
_LISTEN_HOST = os.getenv("PROXY_LISTEN_HOST", "0.0.0.0")
_LISTEN_PORT = int(os.getenv("PROXY_LISTEN_PORT", "2222"))
_CHANNEL_ACCEPT_TIMEOUT_S = 20


def _load_host_key() -> paramiko.RSAKey:
    if not os.path.exists(_HOST_KEY_PATH):
        raise FileNotFoundError(
            f"Host key not found at {_HOST_KEY_PATH!r}. Run: make key"
        )
    return paramiko.RSAKey(filename=_HOST_KEY_PATH)


def _handle_connection(
    client_sock: socket.socket,
    client_addr: tuple[str, int],
    host_key: paramiko.RSAKey,
) -> None:
    ip, port = client_addr
    log.info(f"Connection from {ip}:{port}")

    transport = paramiko.Transport(client_sock)
    transport.add_server_key(host_key)
    transport.local_version = os.getenv("SSH_BANNER", "SSH-2.0-OpenSSH_8.9p1 Ubuntu-3ubuntu0.6")

    server_iface = HoneypotServerInterface(client_addr)
    transport.set_subsystem_handler("sftp", paramiko.SFTPServer, HoneypotSFTPServerInterface)

    try:
        transport.start_server(server=server_iface)
    except paramiko.SSHException as exc:
        log.warning(f"SSH handshake failed from {ip}:{port} — {exc}")
        client_sock.close()
        return

    chan = transport.accept(timeout=_CHANNEL_ACCEPT_TIMEOUT_S)
    if chan is None:
        log.debug(f"No channel opened by {ip}:{port}")
        transport.close()
        return

    handle_channel(chan, server_iface)
    transport.close()


def main() -> None:
    db.init()
    manager.init()
    host_key = _load_host_key()

    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    sock.bind((_LISTEN_HOST, _LISTEN_PORT))
    sock.listen(100)

    log.info(f"HoneyShell listening on {_LISTEN_HOST}:{_LISTEN_PORT}")

    try:
        while True:
            client, addr = sock.accept()
            t = threading.Thread(
                target=_handle_connection,
                args=(client, addr, host_key),
                daemon=True,
            )
            t.start()
    except KeyboardInterrupt:
        log.info("Shutting down.")
    finally:
        sock.close()


if __name__ == "__main__":
    main()
