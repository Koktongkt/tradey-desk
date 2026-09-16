"""Cooperating-writer JSONL append with an explicit durability boundary.

No automatic retries: a failed sync may have left a complete but unacknowledged
record. Readers do not participate in the advisory lock. This is not a guarantee
against every host/storage failure, nor permission to truncate/replace live files.
"""
import fcntl
import json
import os
from pathlib import Path


class DurableAppendError(OSError):
    """Append durability is unconfirmed; do not acknowledge or blindly retry."""


def _sync_directory(path):
    fd = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def append_jsonl(path, row):
    """Append one compact object, lock through flush and fsync, then acknowledge."""
    if not isinstance(row, dict):
        raise ValueError('JSONL record must be an object')
    payload = json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False) + '\n'
    path = Path(path)
    try:
        missing = []
        parent = path.parent
        while not parent.exists():
            missing.append(parent)
            parent = parent.parent
        for directory in reversed(missing):
            directory.mkdir(exist_ok=True)
            _sync_directory(directory.parent)
        with path.open('a', encoding='utf-8') as stream:
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            # Closing the descriptor releases the lock, including on errors.
            # Keep it held through close so a buffered close cannot flush after
            # another cooperating writer has acquired the lock.
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
            # Always sync the parent: covers new files and previous failed
            # creation acknowledgments without a racy exists() test.
            _sync_directory(path.parent)
    except OSError as error:
        raise DurableAppendError('ledger durability unconfirmed') from error
