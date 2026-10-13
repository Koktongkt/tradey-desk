#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
if ! command -v python3 >/dev/null 2>&1; then
  printf 'SYSTEM_FAILURE dashboard_cli_missing\n'
  exit 1
fi
# Python owns deadlines, safe diagnostics and all classified retries.
exec python3 "$ROOT/dashboard_deployment.py" 2>/dev/null
