#!/usr/bin/env bash
set -euo pipefail
cd /opt/data/projects/tradey-desk
exec /opt/data/venvs/tradey-watchdog/bin/python watchdog_cron.py mechanical
