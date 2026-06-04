#!/usr/bin/env bash
set -euo pipefail

SERVER="${DAZI_DEPLOY_SERVER:-root@47.103.127.95}"
REMOTE_DIR="${DAZI_DEPLOY_DIR:-/opt/dazi-server}"
TEST_PHONE="${DAZI_TEST_PHONE:-}"
TEST_CODE="${DAZI_TEST_CODE:-}"

require() {
  local name="$1"
  local value="$2"
  if [[ -z "$value" ]]; then
    echo "[fail] $name is required" >&2
    exit 1
  fi
}

require_safe() {
  local name="$1"
  local value="$2"
  local pattern="$3"
  if [[ ! "$value" =~ $pattern ]]; then
    echo "[fail] $name contains unsupported characters" >&2
    exit 1
  fi
}

require "DAZI_TEST_PHONE" "$TEST_PHONE"
require "DAZI_TEST_CODE" "$TEST_CODE"
require_safe "DAZI_DEPLOY_DIR" "$REMOTE_DIR" '^[A-Za-z0-9_./-]+$'
require_safe "DAZI_TEST_PHONE" "$TEST_PHONE" '^[0-9+ -]+$'
require_safe "DAZI_TEST_CODE" "$TEST_CODE" '^[0-9]+$'

echo "[step] ensure remote directory: $SERVER:$REMOTE_DIR"
ssh "$SERVER" "mkdir -p $REMOTE_DIR"

echo "[step] upload backend files"
rsync -avz --progress \
  --exclude '__pycache__' \
  --exclude '.git' \
  --exclude '*.pyc' \
  --exclude '.env' \
  ./ "$SERVER:$REMOTE_DIR/"

echo "[step] rebuild api"
ssh "$SERVER" "cd $REMOTE_DIR && docker compose -f docker-compose.prod.yml up -d --build"

echo "[step] smoke test"
ssh "$SERVER" "cd $REMOTE_DIR && DAZI_API_BASE_URL=http://localhost:8000 DAZI_TEST_PHONE='$TEST_PHONE' DAZI_TEST_CODE='$TEST_CODE' python3 scripts/smoke_internal_test.py"

echo "[ok] internal test deployment finished"
