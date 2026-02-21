import asyncio
import logging
import os

import paramiko

import storage.database as db
from capture import sftp_recorder

log = logging.getLogger(__name__)

_SFTP_ROOT = "/tmp/honeyshell-sftp"


class HoneypotSFTPServerInterface(paramiko.SFTPServerInterface):
    def __init__(self, server) -> None:
        super().__init__(server)
        try:
            honeypot_iface = server.get_server()
            future = getattr(honeypot_iface, "_session_future", None)
            self._session_id = future.result(timeout=5) if future else "unknown"
        except Exception:
            self._session_id = "unknown"

        self._root = os.path.join(_SFTP_ROOT, self._session_id[:8])
        os.makedirs(self._root, exist_ok=True)
        log.info(f"[session:{self._session_id[:8]}] SFTP session started")

    def _realpath(self, path: str) -> str:
        path = os.path.normpath(path)
        return os.path.join(self._root, path.lstrip("/"))

    def list_folder(self, path: str):
        try:
            out = []
            for fname in os.listdir(self._realpath(path)):
                full = os.path.join(self._realpath(path), fname)
                attr = paramiko.SFTPAttributes.from_stat(os.stat(full))
                attr.filename = fname
                out.append(attr)
            return out
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def stat(self, path: str):
        try:
            return paramiko.SFTPAttributes.from_stat(os.stat(self._realpath(path)))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def lstat(self, path: str):
        try:
            return paramiko.SFTPAttributes.from_stat(os.lstat(self._realpath(path)))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def open(self, path: str, flags: int, attr):
        try:
            binary_flag = getattr(os, "O_BINARY", 0)
            mode = getattr(attr, "st_mode", None) or 0o666
            fd = os.open(self._realpath(path), flags | binary_flag, mode)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

        is_write = bool(flags & (os.O_WRONLY | os.O_RDWR | os.O_APPEND | os.O_CREAT))
        return HoneypotSFTPHandle(fd, path, self._session_id, capture=is_write)

    def remove(self, path: str) -> int:
        try:
            os.remove(self._realpath(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def rename(self, oldpath: str, newpath: str) -> int:
        try:
            os.rename(self._realpath(oldpath), self._realpath(newpath))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def mkdir(self, path: str, attr) -> int:
        try:
            os.mkdir(self._realpath(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def rmdir(self, path: str) -> int:
        try:
            os.rmdir(self._realpath(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def chattr(self, path: str, attr) -> int:
        try:
            if getattr(attr, "st_mode", None) is not None:
                os.chmod(self._realpath(path), attr.st_mode)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def symlink(self, target_path: str, path: str) -> int:
        try:
            os.symlink(target_path, self._realpath(path))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def readlink(self, path: str):
        try:
            target = os.readlink(self._realpath(path))
            if target.startswith(self._root):
                target = target[len(self._root):]
            return target
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)


class HoneypotSFTPHandle(paramiko.SFTPHandle):
    def __init__(self, fd: int, path: str, session_id: str, capture: bool = False) -> None:
        super().__init__()
        self._fd = fd
        self._path = path
        self._session_id = session_id
        self._capture = capture
        self._buf: bytearray | None = bytearray() if capture else None

    def read(self, offset: int, length: int):
        try:
            os.lseek(self._fd, offset, os.SEEK_SET)
            return os.read(self._fd, length)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def write(self, offset: int, data: bytes) -> int:
        try:
            os.lseek(self._fd, offset, os.SEEK_SET)
            os.write(self._fd, data)
            if self._capture and self._buf is not None:
                self._buf.extend(data)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK

    def close(self) -> int:
        if self._capture and self._buf:
            asyncio.run_coroutine_threadsafe(
                sftp_recorder.record_upload(
                    self._session_id,
                    os.path.basename(self._path),
                    bytes(self._buf),
                ),
                db.get_loop(),
            )
        os.close(self._fd)
        return paramiko.SFTP_OK

    def stat(self):
        try:
            return paramiko.SFTPAttributes.from_stat(os.fstat(self._fd))
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)

    def chattr(self, attr) -> int:
        try:
            if getattr(attr, "st_mode", None) is not None:
                os.fchmod(self._fd, attr.st_mode)
        except OSError as e:
            return paramiko.SFTPServer.convert_errno(e.errno)
        return paramiko.SFTP_OK
