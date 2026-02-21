.PHONY: setup key build-image mongo-up mongo-down run test

setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

key:
	.venv/bin/python scripts/generate_host_key.py

build-image:
	docker build -t honeyshell-ubuntu orchestrator/images/honeypot-ubuntu/

mongo-up:
	docker compose up -d mongo

mongo-down:
	docker compose down

run:
	.venv/bin/python -m proxy.server

test:
	.venv/bin/python tests/test_phase1.py

test-phase2:
	.venv/bin/python tests/test_phase2.py

test-phase3:
	.venv/bin/python tests/test_phase3.py
