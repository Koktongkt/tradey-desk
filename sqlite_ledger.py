#!/usr/bin/env python3
"""Transactional SQLite ledger with JSONL compatibility projections.

SQLite becomes the authoritative reader after an explicit migration. Every new
append is serialized, validated in SQLite, durably appended to the legacy JSONL
projection, and committed to SQLite in one critical section. Existing scripts
and forensic tools can therefore keep consuming JSONL during the migration.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import tempfile
from typing import Iterable


SCHEMA_VERSION = 1
DEFAULT_STREAMS = (
    "candidates.jsonl",
    "candidate_outcomes.jsonl",
    "decision_audit.jsonl",
    "order_ledger.jsonl",
    "trade_journal.jsonl",
    "private/blocker_diagnostics.jsonl",
    "private/bridge_diagnostics.jsonl",
    "private/order_intents.jsonl",
    "private/order_notifications.jsonl",
    "private/protection_orders.jsonl",
    "private/research_diagnostics.jsonl",
    "private/reviews.jsonl",
    "public/disagreements.jsonl",
)


class LedgerError(RuntimeError):
    """Base class for local ledger failures."""


class LedgerIntegrityError(LedgerError):
    """The SQLite history and compatibility projection do not agree."""


class LedgerConstraintError(LedgerError):
    """A record violates an append-only ledger invariant."""


class LedgerDurabilityError(OSError):
    """A durable append could not be acknowledged safely."""


def _canonical(row: dict) -> str:
    if not isinstance(row, dict):
        raise ValueError("ledger record must be an object")
    return json.dumps(row, sort_keys=True, separators=(",", ":"), allow_nan=False)


def _storage_root(path: Path) -> Path:
    path = Path(path).resolve()
    ancestors = list(path.parents)
    for ancestor in ancestors:
        if ancestor.name == "test_artifacts":
            return ancestor
    for ancestor in ancestors:
        if ancestor.name in {"private", "public"}:
            return ancestor.parent
    return path.parent


def database_path(path: Path | str) -> Path:
    root = _storage_root(Path(path))
    return root / "private" / "trading_journal.sqlite3"


def _stream_name(path: Path, root: Path) -> str:
    try:
        return path.resolve().relative_to(root.resolve()).as_posix()
    except ValueError as error:
        raise LedgerIntegrityError("ledger path is outside its storage root") from error


def _sync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _ensure_parent(path: Path) -> None:
    missing = []
    parent = path.parent
    while not parent.exists():
        missing.append(parent)
        parent = parent.parent
    for directory in reversed(missing):
        directory.mkdir(exist_ok=True)
        _sync_directory(directory.parent)


def _connect(db: Path) -> sqlite3.Connection:
    _ensure_parent(db)
    connection = sqlite3.connect(db, timeout=30, isolation_level=None)
    try:
        connection.execute("PRAGMA busy_timeout=30000")
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA synchronous=FULL")
        connection.execute("PRAGMA journal_mode=WAL")
        connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS ledger_entries (
                id INTEGER PRIMARY KEY,
                stream TEXT NOT NULL CHECK(length(stream) > 0),
                sequence INTEGER NOT NULL CHECK(sequence > 0),
                record_json TEXT NOT NULL
                    CHECK(json_valid(record_json))
                    CHECK(json_type(record_json) = 'object'),
                record_sha256 TEXT NOT NULL CHECK(length(record_sha256) = 64),
                appended_at TEXT NOT NULL,
                UNIQUE(stream, sequence)
            );
            CREATE INDEX IF NOT EXISTS ledger_entries_stream_time
                ON ledger_entries(stream, json_extract(record_json, '$.timestamp'));
            CREATE INDEX IF NOT EXISTS ledger_entries_client_order
                ON ledger_entries(stream, json_extract(record_json, '$.client_order_id'));
            CREATE UNIQUE INDEX IF NOT EXISTS unique_order_intent
                ON ledger_entries(json_extract(record_json, '$.client_order_id'))
                WHERE stream = 'private/order_intents.jsonl'
                  AND json_extract(record_json, '$.client_order_id') IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS unique_trade_closure
                ON ledger_entries(json_extract(record_json, '$.closure_key'))
                WHERE stream = 'trade_journal.jsonl'
                  AND json_extract(record_json, '$.closure_key') IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS unique_protection_order
                ON ledger_entries(json_extract(record_json, '$.protection_client_order_id'))
                WHERE stream = 'private/protection_orders.jsonl'
                  AND json_extract(record_json, '$.protection_client_order_id') IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS unique_protection_parent
                ON ledger_entries(json_extract(record_json, '$.parent_client_order_id'))
                WHERE stream = 'private/protection_orders.jsonl'
                  AND json_extract(record_json, '$.parent_client_order_id') IS NOT NULL;
            CREATE UNIQUE INDEX IF NOT EXISTS unique_notification_transition
                ON ledger_entries(
                    json_extract(record_json, '$.notification_key'),
                    json_extract(record_json, '$.state')
                )
                WHERE stream = 'private/order_notifications.jsonl'
                  AND json_extract(record_json, '$.notification_key') IS NOT NULL;
            CREATE TRIGGER IF NOT EXISTS trade_journal_fills_only
            BEFORE INSERT ON ledger_entries
            WHEN NEW.stream = 'trade_journal.jsonl'
             AND COALESCE(json_extract(NEW.record_json, '$.status'), '') <> 'filled'
            BEGIN
                SELECT RAISE(ABORT, 'trade journal accepts confirmed fills only');
            END;
            """
        )
        connection.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        return connection
    except Exception:
        connection.close()
        raise


def _parse_projection(path: Path, strict: bool = True) -> list[dict]:
    if not path.exists():
        return []
    try:
        raw_bytes = path.read_bytes()
        if raw_bytes and not raw_bytes.endswith(b"\n"):
            raise LedgerIntegrityError("ledger projection has an unterminated final record")
        lines = raw_bytes.decode("utf-8").splitlines()
    except LedgerIntegrityError:
        raise
    except (OSError, UnicodeError) as error:
        raise LedgerIntegrityError("ledger projection is unreadable") from error
    rows = []
    for number, raw in enumerate(lines, 1):
        if not raw.strip():
            continue
        try:
            row = json.loads(raw)
            if not isinstance(row, dict):
                raise ValueError("not an object")
            _canonical(row)
            rows.append(row)
        except (ValueError, TypeError, json.JSONDecodeError) as error:
            if strict:
                raise LedgerIntegrityError(f"invalid ledger record at line {number}") from error
    return rows


def _insert(connection: sqlite3.Connection, stream: str, sequence: int, payload: str) -> None:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    timestamp = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    try:
        connection.execute(
            "INSERT INTO ledger_entries(stream, sequence, record_json, record_sha256, appended_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (stream, sequence, payload, digest, timestamp),
        )
    except sqlite3.IntegrityError as error:
        raise LedgerConstraintError(str(error)) from error


def _database_rows(connection: sqlite3.Connection, stream: str) -> list[str]:
    rows = connection.execute(
        "SELECT record_json, record_sha256 FROM ledger_entries WHERE stream=? ORDER BY sequence",
        (stream,),
    ).fetchall()
    payloads = []
    for payload, expected_digest in rows:
        actual_digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
        if actual_digest != expected_digest:
            raise LedgerIntegrityError(f"stored ledger digest mismatch for {stream}")
        payloads.append(payload)
    return payloads


def _sync_stream(connection: sqlite3.Connection, root: Path, path: Path) -> tuple[int, int]:
    stream = _stream_name(path, root)
    projected = [_canonical(row) for row in _parse_projection(path, strict=True)]
    stored = _database_rows(connection, stream)
    if len(projected) < len(stored) or projected[: len(stored)] != stored:
        raise LedgerIntegrityError(f"compatibility projection diverged for {stream}")
    imported = 0
    for offset, payload in enumerate(projected[len(stored) :], len(stored) + 1):
        _insert(connection, stream, offset, payload)
        imported += 1
    return len(projected), imported


def _lock_path(db: Path) -> Path:
    return db.with_suffix(db.suffix + ".lock")


def migrate_jsonl(root: Path | str, paths: Iterable[Path] | None = None) -> dict:
    root = Path(root).resolve()
    selected = [Path(path).resolve() for path in paths] if paths is not None else [root / name for name in DEFAULT_STREAMS]
    selected = [path for path in selected if path.exists()]
    db = database_path(root / "order_ledger.jsonl")
    _ensure_parent(_lock_path(db))
    rows = 0
    imported = 0
    with _lock_path(db).open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        connection = _connect(db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            for path in selected:
                count, added = _sync_stream(connection, root, path)
                rows += count
                imported += added
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
    _sync_directory(db.parent)
    return {
        "database": str(db),
        "streams_migrated": len(selected),
        "rows_migrated": rows,
        "rows_imported": imported,
    }


def append_jsonl(path: Path | str, row: dict) -> None:
    path = Path(path).resolve()
    payload = _canonical(row)
    if path.name == "trade_journal.jsonl" and row.get("status") != "filled":
        raise LedgerConstraintError("trade journal accepts confirmed fills only")
    root = _storage_root(path)
    db = database_path(path)
    lock_path = _lock_path(db)
    try:
        _ensure_parent(lock_path)
        with lock_path.open("a+", encoding="utf-8") as global_lock:
            fcntl.flock(global_lock.fileno(), fcntl.LOCK_EX)
            _ensure_parent(path)
            with path.open("a+", encoding="utf-8") as projection:
                fcntl.flock(projection.fileno(), fcntl.LOCK_EX)
                connection = _connect(db)
                try:
                    connection.execute("BEGIN IMMEDIATE")
                    _, _ = _sync_stream(connection, root, path)
                    sequence = connection.execute(
                        "SELECT COUNT(*) FROM ledger_entries WHERE stream=?",
                        (_stream_name(path, root),),
                    ).fetchone()[0] + 1
                    _insert(connection, _stream_name(path, root), sequence, payload)
                    projection.write(payload + "\n")
                    projection.flush()
                    os.fsync(projection.fileno())
                    _sync_directory(path.parent)
                    connection.commit()
                    _sync_directory(db.parent)
                except Exception:
                    connection.rollback()
                    raise
                finally:
                    connection.close()
    except LedgerError:
        raise
    except (OSError, sqlite3.Error) as error:
        raise LedgerDurabilityError("ledger durability unconfirmed") from error


def read_jsonl(path: Path | str, strict: bool = False) -> list[dict]:
    path = Path(path).resolve()
    db = database_path(path)
    if not db.exists():
        return _parse_projection(path, strict=strict)
    root = _storage_root(path)
    lock_path = _lock_path(db)
    _ensure_parent(lock_path)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        connection = _connect(db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            _sync_stream(connection, root, path)
            rows = [json.loads(payload) for payload in _database_rows(connection, _stream_name(path, root))]
            connection.commit()
            return rows
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def verify_database(root: Path | str) -> dict:
    root = Path(root).resolve()
    db = database_path(root / "order_ledger.jsonl")
    if not db.exists():
        return {"ok": False, "database": str(db), "streams": 0, "rows": 0, "error": "database_missing"}
    lock_path = _lock_path(db)
    _ensure_parent(lock_path)
    with lock_path.open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        connection = _connect(db)
        try:
            connection.execute("BEGIN IMMEDIATE")
            streams = [row[0] for row in connection.execute("SELECT DISTINCT stream FROM ledger_entries ORDER BY stream")]
            for stream in streams:
                _sync_stream(connection, root, root / stream)
            integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            rows = connection.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
            connection.commit()
            return {
                "ok": integrity == "ok" and not foreign_keys,
                "database": str(db),
                "streams": len(streams),
                "rows": rows,
                "integrity_check": integrity,
                "foreign_key_violations": len(foreign_keys),
            }
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()


def backup_database(root: Path | str, destination: Path | str) -> dict:
    """Create and validate a consistent SQLite snapshot under the writer lock."""
    root = Path(root).resolve()
    db = database_path(root / "order_ledger.jsonl")
    if not db.exists():
        raise LedgerIntegrityError("database missing")
    destination = Path(destination).resolve()
    if destination == db.resolve() or destination.suffix.lower() == ".jsonl":
        raise LedgerConstraintError("backup destination conflicts with live ledger storage")
    _ensure_parent(destination)
    lock_path = _lock_path(db)
    _ensure_parent(lock_path)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(descriptor)
    temporary = Path(temporary_name)
    try:
        with lock_path.open("a+", encoding="utf-8") as lock:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
            source = _connect(db)
            target = sqlite3.connect(temporary)
            try:
                streams = [row[0] for row in source.execute(
                    "SELECT DISTINCT stream FROM ledger_entries ORDER BY stream"
                )]
                for stream in streams:
                    _sync_stream(source, root, root / stream)
                source.backup(target)
                target.commit()
                integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
                rows = target.execute("SELECT COUNT(*) FROM ledger_entries").fetchone()[0]
                if integrity != "ok":
                    raise LedgerIntegrityError("backup integrity check failed")
            finally:
                target.close()
                source.close()
        with temporary.open("rb") as snapshot:
            os.fsync(snapshot.fileno())
        os.replace(temporary, destination)
        _sync_directory(destination.parent)
        return {
            "ok": True,
            "database": str(db),
            "backup": str(destination),
            "streams": len(streams),
            "rows": rows,
            "integrity_check": integrity,
        }
    finally:
        if temporary.exists():
            temporary.unlink()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Migrate and verify Tradey append-only ledgers")
    parser.add_argument("action", choices=("migrate", "verify", "backup"))
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parent)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    if args.action == "migrate":
        report = migrate_jsonl(args.root)
    elif args.action == "verify":
        report = verify_database(args.root)
    else:
        if args.output is None:
            parser.error("backup requires --output")
        report = backup_database(args.root, args.output)
    print(json.dumps(report, sort_keys=True))
    return 0 if report.get("ok", True) else 2


if __name__ == "__main__":
    raise SystemExit(main())
