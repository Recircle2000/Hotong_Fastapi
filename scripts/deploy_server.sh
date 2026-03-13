#!/usr/bin/env bash

set -Eeuo pipefail

PROJECT_ROOT="${PROJECT_ROOT:-$(pwd)}"
FRONTEND_ROOT="${PROJECT_ROOT}/frontend-admin"
STATIC_ROOT="${PROJECT_ROOT}/nginx/static/admin-v2"
COMPOSE_FILE="${PROJECT_ROOT}/docker-compose.server.yml"

if ! command -v docker >/dev/null 2>&1; then
  echo "docker is required on the server." >&2
  exit 1
fi

if docker compose version >/dev/null 2>&1; then
  COMPOSE_CMD=(docker compose)
elif command -v docker-compose >/dev/null 2>&1; then
  COMPOSE_CMD=(docker-compose)
else
  echo "docker compose or docker-compose is required on the server." >&2
  exit 1
fi

cd "${PROJECT_ROOT}"

mkdir -p "${STATIC_ROOT}"

docker run --rm \
  -v "${PROJECT_ROOT}:/workspace" \
  -w /workspace/frontend-admin \
  node:22-alpine \
  sh -lc "npm ci && npm run build"

find "${STATIC_ROOT}" -mindepth 1 -maxdepth 1 ! -name '.gitkeep' -exec rm -rf {} +
cp -R "${FRONTEND_ROOT}/dist/." "${STATIC_ROOT}/"

"${COMPOSE_CMD[@]}" -f "${COMPOSE_FILE}" up -d --build
