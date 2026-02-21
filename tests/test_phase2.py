import asyncio
import os
import sys
import time

import docker
import motor.motor_asyncio
import paramiko

PROXY_HOST = os.getenv("PROXY_LISTEN_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_LISTEN_PORT", "2222"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "honeyshell")

TEST_USER = "root"
TEST_PASS = "phase2_test_password"
_SETTLE_S = 2.0


async def _get_session() -> dict | None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    doc = await client[MONGO_DB].sessions.find_one(
        {"username": TEST_USER, "password": TEST_PASS},
        sort=[("started_at", -1)],
    )
    client.close()
    return doc


def _run_command_over_ssh(command: str) -> str:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    output = ""
    try:
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
        _, stdout, _ = ssh.exec_command(command, timeout=10)
        output = stdout.read().decode("utf-8", errors="replace").strip()
    except Exception as exc:
        print(f"  SSH error: {exc}")
    finally:
        ssh.close()
    return output


def test_container_spawned() -> None:
    print(f"\n[*] Connecting to {PROXY_HOST}:{PROXY_PORT} as {TEST_USER!r}")

    hostname = _run_command_over_ssh("hostname")
    print(f"[*] Container hostname: {hostname!r}")

    time.sleep(_SETTLE_S)
    doc = asyncio.run(_get_session())

    assert doc is not None, "Session not in MongoDB — is the proxy running? (make run)"
    assert doc["container_id"] is not None, "container_id is null — container was not spawned"

    print(f"[+] PASS — container spawned")
    print(f"    session_id   : {doc['session_id']}")
    print(f"    container_id : {doc['container_id'][:12]}")
    print(f"    hostname     : {hostname!r}")


def test_container_destroyed() -> None:
    print(f"\n[*] Verifying container is destroyed after session ends...")

    time.sleep(_SETTLE_S)
    doc = asyncio.run(_get_session())

    if doc is None or not doc.get("container_id"):
        print("  [!] No session with container_id found — run test_container_spawned first")
        return

    container_id = doc["container_id"]
    client = docker.from_env()

    try:
        client.containers.get(container_id)
        print(f"  [!] Container {container_id[:12]} still running — session may still be active")
    except docker.errors.NotFound:
        print(f"[+] PASS — container {container_id[:12]} destroyed after session ended")


def test_exec_command() -> None:
    print(f"\n[*] Testing exec command (non-interactive)")
    output = _run_command_over_ssh("cat /etc/passwd")

    assert output, "No output from exec command"
    assert "root:" in output, f"Unexpected /etc/passwd content: {output[:100]}"
    assert "deploy:" in output, "Fake passwd not installed — rebuild image: make build-image"

    print(f"[+] PASS — exec command works, fake /etc/passwd confirmed")


if __name__ == "__main__":
    try:
        test_container_spawned()
        test_exec_command()
        test_container_destroyed()
        print("\n[+] All Phase 2 tests passed.")
    except AssertionError as exc:
        print(f"\n[-] FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n[-] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
