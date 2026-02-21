# HoneyShell — Project Roadmap

> This is a living document. Priorities may shift as the project evolves, but the goal stays the same: build something that actually works, is secure enough to run on the open internet, and produces useful threat intelligence.

---

## The Big Picture

Think of this project in four stages, each one independently useful:

```
Phase 1 → You have a working SSH trap that logs credentials
Phase 2 → Attackers land inside real containers they can actually use
Phase 3 → You can watch what they're doing in real time
Phase 4 → You have a polished, deployable system with a dashboard
```

You could ship after any phase. Each one adds real value.

---

## Phase 1 — The Trap (SSH Proxy + Credential Logging)

**Goal:** An SSH server that accepts everything and records who tried to get in.

This is the foundation. Without this nothing else works.

### Tasks

- [ ] Set up the Python project skeleton (`proxy/`, virtual environment, dependencies)
- [ ] Generate a persistent RSA host key (and make sure it's gitignored)
- [ ] Implement the Paramiko `ServerInterface` subclass
  - Accept all `auth_password` attempts (always return `AUTH_SUCCESSFUL`)
  - Accept all `auth_publickey` attempts
  - Log source IP, port, username, and password before accepting
- [ ] Stand up MongoDB (Docker Compose service) and write the `sessions` collection model
- [ ] Wire credential logging to MongoDB using Motor (async)
- [ ] Write a basic test harness — connect with `ssh wrong_password@localhost` and verify the record appears in the DB
- [ ] Document the host SSH port migration (move real sshd to port 2222 before binding port 22)

**Done when:** Every SSH connection attempt to port 22 is logged to MongoDB, and you can query it.

**Estimated effort:** 1–2 weeks

---

## Phase 2 — The Container (Isolated Backend Environments)

**Goal:** Each authenticated session drops the attacker into their own throwaway Ubuntu container.

This is where it gets interesting. The attacker thinks they're on a real server.

### Tasks

- [ ] Write the Container Orchestrator (`orchestrator/manager.py`)
  - `create_session_container(session_id)` → starts a container, returns ID + SSH-exec target
  - `destroy_container(container_id)` → stops and removes
- [ ] Build the honeypot base image (`orchestrator/images/honeypot-ubuntu/Dockerfile`)
  - Start from `ubuntu:22.04`
  - Pre-install common tools attackers expect: `wget`, `curl`, `gcc`, `python3`, `netcat`, `git`
  - Add fake but convincing `/etc/passwd`, `/etc/hosts`, hostname
  - Set up an internal SSH daemon or direct exec access point
- [ ] Enforce resource limits on container creation:
  - `--cpus=0.5`, `--memory=256m`, `--memory-swap=256m`
  - No privileged mode, no host network
- [ ] Create the `honeypot-net` Docker bridge network with egress blocked via iptables
- [ ] Implement the auto-destruct timer (asyncio task that calls `destroy_container` after N minutes)
- [ ] Bridge the Paramiko channel to the container's shell (the MITM tunnel)
  - Forward PTY resize events
  - Handle both `shell` and `exec` request types
- [ ] Test: SSH in, verify container exists, run commands, verify container is destroyed after session ends

**Done when:** An attacker can SSH in, poke around a real Ubuntu environment, and the container disappears when they leave.

**Estimated effort:** 2–3 weeks

---

## Phase 3 — The Recorder (Keystroke + File Capture)

**Goal:** Everything the attacker does is captured and stored.

### Tasks

**TTY Recording**
- [ ] Implement `capture/tty_recorder.py` — a transparent byte interceptor sitting between the Paramiko channel and the container PTY
- [ ] Write every chunk to the `keystrokes` collection with direction (`input`/`output`) and timestamp
- [ ] Make sure timing is precise enough for session replay

**SFTP Capture**
- [ ] Implement the `SFTPServerInterface` subclass (`proxy/handlers/sftp.py`)
- [ ] Intercept file uploads: capture file content before forwarding to container
- [ ] Store files in MongoDB GridFS via `capture/sftp_recorder.py`
- [ ] Add SHA-256 hashing of each captured file
- [ ] Log upload metadata to the `uploads` collection

**Validation**
- [ ] Manually test: SFTP upload a script, verify it appears in MongoDB with correct content
- [ ] Manually test: Run a multi-command session, verify keystroke log can be used to reconstruct the session

**Done when:** You can fully reconstruct what an attacker did from the database alone.

**Estimated effort:** 1–2 weeks

---

## Phase 4 — The Dashboard (Real-time Monitoring + UI)

**Goal:** A live window into what's happening, accessible from a browser.

This is the payoff phase — where all the raw data becomes something you can actually look at.

### Backend API & Events

- [ ] Set up FastAPI application (`api/main.py`)
- [ ] Add `python-socketio` with ASGI middleware
- [ ] Implement Socket.io event emitters — hook them into the capture layer so events fire on:
  - New session
  - Each keystroke chunk
  - File upload
  - Session end
- [ ] Build REST endpoints for the dashboard:
  - `GET /sessions` — paginated session list
  - `GET /sessions/:id` — full session detail
  - `GET /sessions/:id/keystrokes` — full keystroke log
  - `GET /uploads/:id` — file download
  - `GET /stats` — aggregate stats (counts, top IPs, top credentials)

### React Dashboard

- [ ] Bootstrap with Vite + React + TypeScript
- [ ] Set up Socket.io client, connect to backend
- [ ] **Live Sessions Panel** — table of active sessions, updates in real time
- [ ] **Credential Feed** — live list of login attempts (username + password + IP + timestamp)
- [ ] **Session Detail View** — xterm.js terminal that replays the keystroke log
- [ ] **Upload Viewer** — list captured files, show hex dump or raw content
- [ ] **Stats Page** — bar charts (top countries, top usernames, top passwords) using Recharts
- [ ] Basic auth on the dashboard (you don't want anyone to see your honeypot data)

**Done when:** You can open a browser, watch attackers connect in real time, and click into any session to see exactly what they did.

**Estimated effort:** 2–3 weeks

---

## Phase 5 — Hardening & Deployment (Production Readiness)

This phase is about making it safe and stable enough to run continuously on a real VPS.

- [ ] Full `docker-compose.yml` with all services (proxy, MongoDB, API, dashboard, nginx reverse proxy)
- [ ] Nginx with TLS for the dashboard (Let's Encrypt via Certbot)
- [ ] Rate limiting at the TCP level (iptables rules to prevent container exhaustion)
- [ ] Alerting — email/Slack notification when a new session starts or a file is uploaded
- [ ] Disk space monitoring — alert when MongoDB volume exceeds threshold
- [ ] Log rotation for raw logs
- [ ] GitHub Actions CI — lint, type-check, run unit tests on every push
- [ ] A proper `README.md` with deployment instructions (the kind someone could actually follow)

**Estimated effort:** 1–2 weeks

---

## Rough Timeline

This is aspirational — adjust based on how many hours a week you can put in.

```
Week 1–2    Phase 1 (SSH Proxy + Credential Logging)
Week 3–5    Phase 2 (Container Orchestration)
Week 6–7    Phase 3 (Data Capture)
Week 8–10   Phase 4 (Dashboard)
Week 11–12  Phase 5 (Hardening)
```

Total: ~10–12 weeks of focused work, or longer if this is a side project.

---

## Future Ideas (Post-MVP)

These aren't in scope right now, but worth keeping in mind:

- **Malware analysis pipeline** — auto-submit SFTP uploads to VirusTotal or a local sandbox (Cuckoo)
- **Decoy file system** — pre-populate containers with fake credentials, SSH keys, and config files to see if attackers exfiltrate them (canary tokens)
- **Threat intelligence export** — export captured IPs and credentials in STIX/TAXII format
- **Multi-node deployment** — run honeypots in multiple cloud regions and aggregate data centrally
- **Command classification** — use an LLM to auto-tag sessions by attacker behavior (recon, persistence, lateral movement, etc.)
- **Mimicry profiles** — make the honeypot impersonate specific server types (AWS EC2, cPanel host, Jenkins server) to attract targeted attackers

---

## Decisions Still Open

A few things worth thinking through before building:

| Question | Options | Notes |
|----------|---------|-------|
| How does the proxy talk to the container? | Direct Docker exec vs. in-container sshd | `docker exec` is simpler; sshd inside the container is more realistic |
| Where does Socket.io live? | Python backend (python-socketio) vs. separate Node.js bridge | Keep it in Python to avoid running two servers |
| How are containers network-isolated? | Custom Docker bridge + iptables vs. Docker's `--network none` | Bridge lets you control egress granularly; `--network none` is simpler but blocks all traffic |
| Dashboard auth | Simple HTTP Basic Auth vs. JWT | Basic auth is fine for a personal tool |
| MongoDB hosting | Same host vs. remote | Remote is safer — logs survive host compromise |
