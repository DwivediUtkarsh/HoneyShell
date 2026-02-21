import os
import sys
import paramiko

KEY_PATH = os.getenv("HOST_KEY_PATH", "proxy/keys/host_rsa")
KEY_BITS = 2048


def main() -> None:
    os.makedirs(os.path.dirname(KEY_PATH), exist_ok=True)

    if os.path.exists(KEY_PATH):
        print(f"[!] Host key already exists at {KEY_PATH}. Delete it first to regenerate.")
        sys.exit(0)

    key = paramiko.RSAKey.generate(KEY_BITS)
    key.write_private_key_file(KEY_PATH)
    os.chmod(KEY_PATH, 0o600)

    print(f"[+] Key written to {KEY_PATH}")
    print(f"[+] Fingerprint: {key.get_fingerprint().hex(':')}")


if __name__ == "__main__":
    main()
