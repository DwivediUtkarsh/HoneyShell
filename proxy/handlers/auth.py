import asyncio
import logging
from typing import Callable

import paramiko

import storage.database as db
from storage.models import create_session

log = logging.getLogger(__name__)


class HoneypotServerInterface(paramiko.ServerInterface):
    def __init__(self, client_addr: tuple[str, int]) -> None:
        self.client_ip: str = client_addr[0]
        self.client_port: int = client_addr[1]
        self._session_future: asyncio.Future | None = None
        self.exec_command: bytes | None = None
        self._resize_callback: Callable[[int, int], None] | None = None

    def get_allowed_auths(self, username: str) -> str:
        return "password,publickey"

    def check_auth_none(self, username: str) -> int:
        return paramiko.AUTH_FAILED

    def check_auth_password(self, username: str, password: str) -> int:
        self._submit_session_log(username=username, password=password, auth_method="password")
        return paramiko.AUTH_SUCCESSFUL

    def check_auth_publickey(self, username: str, key: paramiko.PKey) -> int:
        fingerprint = key.get_fingerprint().hex(":")
        self._submit_session_log(username=username, password=fingerprint, auth_method="publickey")
        return paramiko.AUTH_SUCCESSFUL

    def _submit_session_log(self, username: str, password: str | None, auth_method: str) -> None:
        self._session_future = asyncio.run_coroutine_threadsafe(
            create_session(
                source_ip=self.client_ip,
                source_port=self.client_port,
                username=username,
                password=password,
                auth_method=auth_method,
            ),
            db.get_loop(),
        )

    def check_channel_request(self, kind: str, chanid: int) -> int:
        if kind == "session":
            return paramiko.OPEN_SUCCEEDED
        return paramiko.OPEN_FAILED_ADMINISTRATIVELY_PROHIBITED

    def check_channel_pty_request(
        self, channel: paramiko.Channel,
        term: str, width: int, height: int,
        pixelwidth: int, pixelheight: int, modes: bytes,
    ) -> bool:
        return True

    def check_channel_window_change_request(
        self, channel: paramiko.Channel,
        width: int, height: int,
        pixelwidth: int, pixelheight: int,
    ) -> bool:
        if self._resize_callback:
            self._resize_callback(width, height)
        return True

    def check_channel_shell_request(self, channel: paramiko.Channel) -> bool:
        return True

    def check_channel_exec_request(self, channel: paramiko.Channel, command: bytes) -> bool:
        self.exec_command = command
        return True

    def check_channel_subsystem_request(self, channel: paramiko.Channel, name: str) -> bool:
        return name == "sftp"
