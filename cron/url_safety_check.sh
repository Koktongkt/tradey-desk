#!/usr/bin/env bash
# Pre-open URL-admission compatibility check (validation only: no fetches, models, broker or ledger writes).
# Silent on pass; one SYSTEM_FAILURE line and exit 3 if a Hermes update broke the extraction boundary.
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${TRADEY_PYTHON-$HOME/.local/share/tradey/venv-linux/bin/python}"
cd "$ROOT"
exec "$PYTHON" "$ROOT/scripts/check_url_safety_compatibility.py" --scheduled "$@"
