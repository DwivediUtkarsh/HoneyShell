FROM ubuntu:22.04

# Pre-install tools attackers expect to find on a real server.
# Fake /etc/passwd, /etc/hosts, and hostname are configured at runtime.
RUN apt-get update && apt-get install -y \
    wget curl gcc python3 netcat-openbsd git openssh-server \
    && rm -rf /var/lib/apt/lists/*
