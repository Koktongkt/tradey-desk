#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${TRADEY_PYTHON-$HOME/.local/share/tradey/venv-linux/bin/python}"
cd "$ROOT"
exec "$PYTHON" "$ROOT/watchdog_cron.py" mechanical "$@"
