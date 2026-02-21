# HoneyShell — Technical Documentation

> A high-interaction SSH honeypot that lures attackers into fully functional, containerized environments — capturing everything they do, in real time.

---

## What is HoneyShell?

HoneyShell is a deception system designed to look and behave exactly like a real SSH server. When an attacker connects, they get what appears to be a legitimate Linux shell. Behind the scenes, they're actually inside a disposable Docker container with a full TTY, a real filesystem, and running processes — but one that's completely isolated from your infrastructure, recording every keystroke they make.

The system is built on three pillars:

1. **Intercept** — A Python proxy (powered by Paramiko) sits on port 22 and accepts every single connection, logging credentials on the way in.
2. **Contain** — Each attacker session gets its own fresh Ubuntu container, spun up on demand and destroyed when the session ends (or when a safety timer fires).
3. **Observe** — A React dashboard fed by Socket.io lets you watch sessions live, replay activity, and query the full historical dataset.

---

## System Architecture

```
Internet
    │
    ▼
┌─────────────────────────────────┐
│         SSH Proxy (Port 22)     │  ← Python / Paramiko
│  - Accepts all auth attempts    │
│  - Logs credentials to MongoDB  │
│  - Tunnels shell/SFTP traffic   │
└────────────────┬────────────────┘
                 │  docker-py API
                 ▼
┌─────────────────────────────────┐
│      Container Orchestrator     │
│  - Spawns Ubuntu container/     │
│    session                      │
│  - Enforces CPU / RAM caps      │
│  - Sets network isolation rules │
│  - Runs auto-destruct timer     │
└────────────────┬────────────────┘
                 │
        ┌────────┴────────┐
        ▼                 ▼
┌──────────────┐  ┌──────────────────┐
│  MongoDB     │  │  Socket.io Server │
│  Persistence │  │  (Event Emitter)  │
└──────────────┘  └────────┬─────────┘
                           │
                           ▼
                  ┌─────────────────┐
                  │  React Dashboard │
                  │  (Live Monitor)  │
                  └─────────────────┘
```

---

## Core Components

### 1. SSH Proxy (`proxy/`)

This is the front door. It's a Paramiko-based server that listens on port 22 and acts as a man-in-the-middle between the attacker and the backend container.

**What it does:**

- Presents a believable SSH banner (configurable — can mimic OpenSSH, Dropbear, etc.)
- Accepts every login attempt (`auth_password` and `auth_publickey`) — nobody gets rejected
- Before proxying the session, it records the source IP, username, and password to MongoDB
- Once authenticated, it asks the Container Orchestrator for a fresh container and bridges the attacker's channel to it
- For interactive shells, it wraps the PTY in a keystroke interceptor
- For SFTP subsystems, it hooks into the file transfer layer to capture uploaded files

**Key Paramiko interfaces used:**

| Interface | Purpose |
|-----------|---------|
| `ServerInterface` | Custom auth handler — always returns `AUTH_SUCCESSFUL` |
| `Transport` | Low-level SSH transport management |
| `Channel` | PTY/shell channel piping |
| `SFTPServerInterface` | SFTP upload capture |

---

### 2. Container Orchestrator (`orchestrator/`)

Every attacker gets their own disposable environment. This component talks to the Docker daemon through docker-py and manages the full lifecycle of each container.

**Container Spec per Session:**

| Parameter | Value |
|-----------|-------|
| Base image | `ubuntu:22.04` (pre-pulled, hardened) |
| CPU limit | 0.5 cores (configurable) |
| RAM limit | 256 MB (configurable) |
| Network mode | Isolated bridge (no outbound internet by default) |
| Auto-destruct | 30 minutes from session start (configurable) |
| Storage | Ephemeral (tmpfs or throwaway volume) |

**Lifecycle:**

```
Session starts
    │
    ▼
Pull/verify base image
    │
    ▼
docker run --cpus=0.5 --memory=256m --network=honeypot-net
    │
    ▼
Inject SSH daemon or exec shell directly
    │
    ▼
Proxy bridges attacker ↔ container
    │
    ▼
Session ends OR timer fires
    │
    ▼
docker stop + docker rm (container destroyed, logs retained)
```

**Safety notes:**

- Outbound internet access from containers is blocked by default via iptables rules on the `honeypot-net` bridge
- Containers run as an unprivileged user with no `--privileged` flag
- `--pid` namespacing prevents host process visibility

---

### 3. Data Capture Layer

Everything an attacker does is recorded. There are two capture points:

**TTY Keystroke Logging**

The proxy sits between the attacker's terminal and the container's PTY. Every byte that flows through is timestamped and written to MongoDB. This gives you:

- A character-by-character replay of the session
- The ability to reconstruct exactly what commands were run
- Timing data (how long they paused, what they hesitated on)

**SFTP File Capture**

When the attacker uploads a file via SFTP, the proxy intercepts the file content before forwarding it. Files are:

- Stored as binary blobs in MongoDB (GridFS for larger files)
- Tagged with session ID, original filename, and upload timestamp
- Optionally submitted to a malware analysis pipeline (future)

---

### 4. MongoDB Schema

Collections:

**`sessions`**
```json
{
  "_id": "ObjectId",
  "session_id": "uuid4",
  "source_ip": "1.2.3.4",
  "source_port": 54321,
  "username": "root",
  "password": "toor123",
  "auth_method": "password",
  "container_id": "abc123def456",
  "started_at": "ISODate",
  "ended_at": "ISODate",
  "duration_seconds": 142,
  "status": "completed | active | terminated"
}
```

**`keystrokes`**
```json
{
  "_id": "ObjectId",
  "session_id": "uuid4",
  "timestamp": "ISODate",
  "data": "base64-encoded bytes",
  "direction": "input | output"
}
```

**`uploads`**
```json
{
  "_id": "ObjectId",
  "session_id": "uuid4",
  "filename": "backdoor.sh",
  "size_bytes": 2048,
  "content_hash": "sha256",
  "uploaded_at": "ISODate",
  "file_ref": "GridFS ObjectId"
}
```

---

### 5. Real-time Streaming (Socket.io)

The backend emits events to a Socket.io namespace that the React dashboard subscribes to.

**Events:**

| Event | Payload | When |
|-------|---------|------|
| `session:new` | session metadata | New attacker connects |
| `session:keystroke` | `{session_id, data, ts}` | Every TTY byte |
| `session:upload` | upload metadata | File uploaded |
| `session:end` | `{session_id, duration}` | Session terminates |
| `session:alert` | `{session_id, reason}` | Suspicious activity flag |

The Socket.io server lives inside the same Python backend (using `python-socketio` with an ASGI adapter) or as a thin Node.js bridge — your call.

---

### 6. React Dashboard (`dashboard/`)

A real-time monitoring interface with:

- **Live Sessions Panel** — Active connections with source IP, username, geolocation flag, and duration
- **Session Replay** — Terminal emulator (xterm.js) that plays back keystroke logs with original timing
- **Credential Feed** — Running log of attempted username/password combos
- **Upload Viewer** — List of captured files with download/hex-view options
- **Stats Overview** — Attack frequency, top source countries, most-tried credentials (charts via Recharts)

---

## Tech Stack Summary

| Layer | Technology |
|-------|-----------|
| SSH Proxy | Python 3.11+, Paramiko |
| Container Management | docker-py (Docker SDK for Python) |
| Backend API / Events | FastAPI + python-socketio |
| Database | MongoDB + Motor (async driver) |
| Frontend | React 18, xterm.js, Recharts, Socket.io client |
| Infrastructure | Docker Compose (dev), optional Kubernetes (prod) |

---

## Security Considerations for the Host

Running a honeypot means deliberately inviting attackers in — so host integrity is everything.

- **Never run the proxy as root.** Use `CAP_NET_BIND_SERVICE` to bind port 22 without root privileges.
- **The Docker socket** (`/var/run/docker.sock`) is the most sensitive surface — the proxy process should have a minimal wrapper instead of direct socket access if possible.
- **Network isolation** is critical — the `honeypot-net` Docker network must have egress blocked via iptables before the honeypot goes live.
- **The host SSH daemon** should be moved to a non-standard port (e.g. 2222) before the honeypot takes over port 22.
- **Log shipping** — MongoDB should be on a separate host or at minimum a separate volume so logs survive even if the honeypot host is compromised.
- **Rate limiting** at the TCP level (via iptables or nftables) prevents a single source from exhausting container resources.

---

## Directory Layout (Planned)

```
cybersec/
├── proxy/                  # Paramiko SSH server & MITM logic
│   ├── server.py
│   ├── handlers/
│   │   ├── auth.py
│   │   ├── shell.py
│   │   └── sftp.py
│   └── keys/               # Host key (gitignored)
├── orchestrator/           # Docker container lifecycle
│   ├── manager.py
│   └── images/
│       └── honeypot-ubuntu/
│           └── Dockerfile
├── capture/                # Keystroke + file capture logic
│   ├── tty_recorder.py
│   └── sftp_recorder.py
├── storage/                # MongoDB models + GridFS helpers
│   └── models.py
├── api/                    # FastAPI + Socket.io backend
│   ├── main.py
│   └── events.py
├── dashboard/              # React frontend
│   ├── src/
│   └── package.json
├── docker-compose.yml
└── .env.example
```
