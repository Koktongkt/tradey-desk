"""One bounded private failure projection; no operational ledger or raw errors.

Best effort, atomic replacement, no locks/fsync/network. The latest failure is
retained (not an append stream); hard interruption or storage failure can lose it.
"""
from datetime import datetime, timezone
import json
import math
import os
import secrets

REASONS = frozenset(('broker_adapter_failed', 'broker_operational_snapshot_incomplete',
    'broker_references_invalid', 'broker_runtime_failed', 'broker_runtime_timeout',
    'broker_deadline_exceeded', 'operational_lock_busy', 'operational_lock_unavailable',
    'operational_history_incomplete', 'operational_snapshot_changed'))
STAGES = frozenset(('broker_adapter', 'operational', 'references', 'worker_spawn',
    'worker_exit', 'worker_decode', 'worker_schema', 'worker_timeout', 'worker_deadline'))


def write_failure(output_root, mode, slot, started_at, details):
    """Strict allowlist; never serialize exception text, class names or payloads."""
    directory = temporary = None
    try:
        row = dict(mode=mode if mode in ('mechanical', 'daily') else 'unknown',
                   slot_at=slot.isoformat(), started_at=started_at,
                   finished_at=datetime.now(timezone.utc).isoformat(),
                   reason=details.get('reason') if details.get('reason') in REASONS else 'broker_adapter_failed',
                   stage=details.get('stage') if details.get('stage') in STAGES else 'broker_adapter',
                   reasons=[r for r in sorted(REASONS) if r in details.get('reasons', [])])
        for key in ('attempts', 'wait_seconds', 'elapsed_seconds', 'worker_exit', 'worker_elapsed_seconds'):
            value = details.get(key)
            row[key] = value if type(value) in (int, float) and math.isfinite(value) and abs(value) <= 1_000_000 else None
        data = (json.dumps(row, sort_keys=True, allow_nan=False) + '\n').encode()
        if len(data) > 4096:
            return
        flags = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW | os.O_NONBLOCK
        # Open every directory component beneath the validated output root
        # without following symlinks. All diagnostic writes remain output-only.
        directory = os.open(output_root, flags)
        for component in ('private', 'watchdog'):
            try:
                os.mkdir(component, mode=0o700, dir_fd=directory)
            except FileExistsError:
                pass
            child = os.open(component, flags, dir_fd=directory)
            os.close(directory)
            directory = child
        os.fchmod(directory, 0o700)
        temporary = '.failure-' + secrets.token_hex(8)
        fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW | os.O_NONBLOCK,
                     0o600, dir_fd=directory)
        try:
            os.fchmod(fd, 0o600)
            if os.write(fd, data) != len(data):
                return
        finally:
            os.close(fd)
        os.replace(temporary, 'failure.json', src_dir_fd=directory, dst_dir_fd=directory)
    except Exception:
        # Diagnostics must never change a monitoring result or emit raw errors.
        pass
    finally:
        if directory is not None:
            if temporary is not None:
                try:
                    os.unlink(temporary, dir_fd=directory)
                except OSError:
                    pass
            os.close(directory)
