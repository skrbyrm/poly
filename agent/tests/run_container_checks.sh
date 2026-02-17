#!/usr/bin/env bash
set -euo pipefail

# Run from repo root: ./agent/scripts/run_container_checks.sh

COMPOSE_FILE="compose.yaml"

printf "\n[1/5] Starting services...\n"
docker compose -f "$COMPOSE_FILE" up -d --build redis agent

printf "\n[2/5] Health check...\n"
curl -fsS http://localhost:8080/health | python -m json.tool

printf "\n[3/5] Running pytest inside agent container...\n"
docker compose -f "$COMPOSE_FILE" exec -T agent pytest -q tests

printf "\n[4/5] Triggering one tick...\n"
curl -fsS -X POST http://localhost:8080/agent/tick | python -m json.tool

printf "\n[5/5] Recent agent logs (last 120 lines)...\n"
docker compose -f "$COMPOSE_FILE" logs --tail=120 agent

printf "\nDone.\n"
