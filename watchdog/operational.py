"""Read SQLite authority and compatibility projections without sync/repair."""
from contextlib import closing
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import struct

from sqlite_ledger import DEFAULT_STREAMS, SCHEMA_VERSION
from .types import OperationalSnapshot


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('duplicate JSON key')
        result[key] = value
    return result


def _loads(raw):
    return json.loads(raw, object_pairs_hook=_unique_object)


def _canonical(row):
    if not isinstance(row, dict):
        raise ValueError('record is not an object')
    return json.dumps(row, sort_keys=True, separators=(',', ':'), allow_nan=False)


def _metadata(paths):
    result = {}
    for path in paths:
        try:
            stat = path.stat()
            result[path] = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        except FileNotFoundError:
            result[path] = None
    return result


def _wal_ready(db):
    # SQLite may CREATE sidecars even with mode=ro. Refuse before opening it.
    with db.open('rb') as handle:
        header = handle.read(100)
    if header[18:20] == b'\x02\x02':
        for suffix in ('-wal', '-shm'):
            sidecar = Path(str(db) + suffix)
            with sidecar.open('rb') as handle:
                if suffix == '-shm':
                    index = handle.read(136)
                    if len(index) < 136 or index[:48] != index[48:96]:
                        return False
                    # mode=ro can still WRITE a new WAL read mark. Only use an
                    # existing mark; otherwise declare coverage unavailable.
                    frame = struct.unpack_from('=I', index, 16)[0]
                    marks = struct.unpack_from('=5I', index, 100)
                    if frame and frame not in marks[1:]:
                        return False
        return True
    return True


def read_operational(root: Path) -> OperationalSnapshot:
    """Root is the storage root, never a ledger file or inferred live checkout.

    Use only the existing writer lock, opened rb: no lock creation or repair.
    Cooperating durable-ledger writers cannot remove WAL prerequisites between
    validation and the read transaction. Contention is a retryable observation.
    """
    root = Path(root).resolve()
    try:
        with (root / 'private/trading_journal.sqlite3.lock').open('rb') as lock:
            fcntl.flock(lock, fcntl.LOCK_SH | fcntl.LOCK_NB)
            return _read_operational(root)
    except BlockingIOError:
        reason = 'operational_snapshot_changed'
    except OSError:
        reason = 'operational_lock_unavailable'
    return OperationalSnapshot({name: [] for name in DEFAULT_STREAMS}, frozenset(), datetime.now(timezone.utc).isoformat(), False, [reason])


def _read_operational(root: Path) -> OperationalSnapshot:
    root = Path(root).resolve()
    db = root / 'private/trading_journal.sqlite3'
    streams = {name: [] for name in DEFAULT_STREAMS}
    reasons = []
    symbols = frozenset()
    paths = [root / name for name in DEFAULT_STREAMS] + [db, Path(str(db) + '-wal'), Path(str(db) + '-shm'), Path(str(db) + '-journal'), root / 'private/broker_baseline.json']
    before = None
    try:
        before = _metadata(paths)
        try:
            if not _wal_ready(db):
                raise OSError('unusable shm')
        except OSError:
            if db.is_file():
                reasons.append('operational_wal_unavailable')
            raise
        baseline = _loads((root / 'private/broker_baseline.json').read_text())
        values = baseline['preexisting_symbols']
        if not isinstance(values, list) or not all(isinstance(symbol, str) and symbol and symbol.isascii() and symbol.isalpha() and symbol == symbol.upper() for symbol in values):
            raise ValueError('invalid baseline symbols')
        symbols = frozenset(values)
        with closing(sqlite3.connect(db.as_uri() + '?mode=ro', uri=True, timeout=1)) as connection:
            connection.execute('PRAGMA query_only=ON')
            connection.execute('BEGIN')
            if connection.execute('PRAGMA user_version').fetchone()[0] != SCHEMA_VERSION:
                raise ValueError('unsupported ledger schema')
            for stream, sequence, payload, digest in connection.execute(
                'SELECT stream, sequence, record_json, record_sha256 FROM ledger_entries ORDER BY stream, sequence'
            ):
                if stream not in streams or sequence != len(streams[stream]) + 1:
                    raise ValueError('invalid stream or sequence')
                if not isinstance(payload, str) or not isinstance(digest, str):
                    raise ValueError('invalid stored record type')
                if hashlib.sha256(payload.encode()).hexdigest() != digest:
                    raise ValueError('invalid digest')
                row = _loads(payload)
                if _canonical(row) != payload:
                    raise ValueError('noncanonical row')
                streams[stream].append(row)
            for stream, rows in streams.items():
                raw = (root / stream).read_bytes()
                if raw and not raw.endswith(b'\n'):
                    raise ValueError('partial projection')
                projected = [_loads(line) for line in raw.decode().splitlines() if line.strip()]
                if [_canonical(row) for row in projected] != [_canonical(row) for row in rows]:
                    raise ValueError('projection mismatch')
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error):
        reasons.append('operational_history_incomplete')
    if before is not None:
        try:
            if before != _metadata(paths):
                reasons.append('operational_snapshot_changed')
        except OSError:
            reasons.append('operational_snapshot_changed')
    return OperationalSnapshot(streams, symbols, datetime.now(timezone.utc).isoformat(), not reasons, reasons)
