"""Read SQLite authority and compatibility projections without sync/repair."""
from contextlib import closing, contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
import json
from pathlib import Path
import sqlite3
import shutil
import tempfile

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


@contextmanager
def _copied_database(db):
    """Only byte reads touch the source; SQLite VFS sees disposable copies.

    Caller holds the existing shared ledger lock throughout copy and validation.
    WAL is authority; SHM is a rebuildable index, never trusted or copied. A
    closed/checkpointed WAL database needs no source sidecars. Journal recovery,
    if required, fails closed with the readonly local connection.
    """
    with tempfile.TemporaryDirectory(prefix='watchdog-', dir='/opt/data/cache/scratch') as scratch:
        local = Path(scratch) / db.name
        shutil.copyfile(db, local)
        for suffix in ('-wal', '-journal'):
            source = Path(str(db) + suffix)
            try:
                with source.open('rb') as incoming, Path(str(local) + suffix).open('wb') as outgoing:
                    shutil.copyfileobj(incoming, outgoing)
            except FileNotFoundError:
                pass
        yield local



def read_operational(root: Path) -> OperationalSnapshot:
    """Root is the storage root, never a ledger file or inferred live checkout.

    Use only the existing writer lock, opened rb: no lock creation or repair.
    Cooperating durable-ledger writers cannot change authoritative bytes while
    they are copied and checked. SQLite opens only the disposable local copy;
    it never attaches to source DB/WAL/SHM. Contention is retryable.
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
        baseline = _loads((root / 'private/broker_baseline.json').read_text())
        values = baseline['preexisting_symbols']
        if not isinstance(values, list) or not all(isinstance(symbol, str) and symbol and symbol.isalpha() for symbol in values):
            raise ValueError('invalid baseline symbols')
        symbols = frozenset(symbol.upper() for symbol in values)
        with _copied_database(db) as local, closing(sqlite3.connect(local.as_uri() + '?mode=ro', uri=True, timeout=1)) as connection:
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
