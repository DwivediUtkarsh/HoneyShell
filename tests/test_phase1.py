import asyncio
import os
import sys
import time

import paramiko
import motor.motor_asyncio

PROXY_HOST = os.getenv("PROXY_LISTEN_HOST", "127.0.0.1")
PROXY_PORT = int(os.getenv("PROXY_LISTEN_PORT", "2222"))
MONGO_URI = os.getenv("MONGO_URI", "mongodb://localhost:27017")
MONGO_DB = os.getenv("MONGO_DB", "honeyshell")

TEST_USER = "root"
TEST_PASS = "hunter2_this_is_not_the_real_password"
_DB_SETTLE_S = 1.5


def _ssh_connect_attempt() -> None:
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
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
    except Exception:
        pass
    finally:
        ssh.close()


async def _find_session(username: str, password: str) -> dict | None:
    client = motor.motor_asyncio.AsyncIOMotorClient(MONGO_URI)
    db = client[MONGO_DB]
    doc = await db.sessions.find_one(
        {"username": username, "password": password},
        sort=[("started_at", -1)],
    )
    client.close()
    return doc


def test_credential_logging() -> None:
    print(f"\n[*] Connecting to {PROXY_HOST}:{PROXY_PORT} as {TEST_USER!r}")
    _ssh_connect_attempt()

    time.sleep(_DB_SETTLE_S)
    doc = asyncio.run(_find_session(TEST_USER, TEST_PASS))

    assert doc is not None, f"Session not found in MongoDB — is the proxy running? (make run)"
    assert doc["username"] == TEST_USER
    assert doc["password"] == TEST_PASS
    assert doc["auth_method"] == "password"
    assert doc["source_ip"]
    assert doc["source_port"] > 0
    assert doc["session_id"]

    print(f"[+] PASS")
    print(f"    session_id  : {doc['session_id']}")
    print(f"    source      : {doc['source_ip']}:{doc['source_port']}")
    print(f"    credentials : {doc['username']!r} / {doc['password']!r}")
    print(f"    started_at  : {doc['started_at']}")
    print(f"    status      : {doc['status']}")


if __name__ == "__main__":
    try:
        test_credential_logging()
        print("\n[+] All Phase 1 tests passed.")
    except AssertionError as exc:
        print(f"\n[-] FAIL: {exc}", file=sys.stderr)
        sys.exit(1)
    except Exception as exc:
        print(f"\n[-] ERROR: {exc}", file=sys.stderr)
        sys.exit(2)
