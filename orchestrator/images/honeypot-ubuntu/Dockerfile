FROM ubuntu:22.04

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
    wget curl gcc python3 python3-pip netcat-openbsd git \
    vim nano net-tools procps htop sudo less file \
    && rm -rf /var/lib/apt/lists/*

# Fake system identity
RUN echo "web-prod-01" > /etc/hostname
COPY fake_passwd /etc/passwd
COPY fake_hosts /etc/hosts

# Decoy web app
RUN mkdir -p /var/www/html /var/www/app
RUN echo '<?php\ndefine("DB_HOST", "db-internal");\ndefine("DB_USER", "webapp");\ndefine("DB_PASS", "Wf9#mP2$xLq");\n' \
    > /var/www/app/config.php
RUN echo 'upstream backend { server api-internal:8000; }\nserver { listen 80; root /var/www/html; }' \
    > /etc/nginx.conf.bak

# Decoy root home directory
RUN mkdir -p /root/.ssh /home/deploy
RUN echo "# prod env\nDB_URL=postgresql://webapp:Wf9#mP2\$xLq@db-internal/proddb\nREDIS_URL=redis://redis-internal:6379/0\nSECRET_KEY=django-insecure-f4k3k3y-d0-n0t-us3" \
    > /root/.env
RUN echo "Host db-internal\n  User deploy\n  IdentityFile ~/.ssh/id_rsa" \
    > /root/.ssh/config
RUN chmod 700 /root/.ssh

WORKDIR /root
