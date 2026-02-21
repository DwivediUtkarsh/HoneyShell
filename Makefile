.PHONY: setup key run test mongo-up mongo-down

setup:
	python3 -m venv .venv
	.venv/bin/pip install --upgrade pip
	.venv/bin/pip install -r requirements.txt

key:
	.venv/bin/python scripts/generate_host_key.py

mongo-up:
	docker compose up -d mongo

mongo-down:
	docker compose down

run:
	.venv/bin/python -m proxy.server

test:
	.venv/bin/python tests/test_phase1.py
