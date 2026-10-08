#!/usr/bin/env python3
"""Monitoring-only watchdog CLI entry point.

Thin wrapper around watchdog.cli.main so operators can run:

    python3 watchdog_cli.py mechanical [--root R] [--output-root O] \
        [--fixture] [--smoke] [--now ISO]

No trading authorization, no schedule registration, no live defaults.
"""
import sys

from watchdog.cli import main

if __name__ == '__main__':
    sys.exit(main())
