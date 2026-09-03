#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
fail(){ printf 'SYSTEM_FAILURE dashboard_deploy %s\n' "$1" >&2; exit 1; }
python3 "$ROOT/public_dashboard.py" >/dev/null 2>&1 || fail build
command -v npx >/dev/null 2>&1 || fail npx_missing
AUTH_ARGS=()
if [ -n "${VERCEL_TOKEN:-}" ]; then
  AUTH_ARGS=(--token "$VERCEL_TOKEN")
fi
npx --yes vercel deploy "$ROOT/public" --prod --yes "${AUTH_ARGS[@]}" >/dev/null 2>&1 || fail vercel_deploy_failed
