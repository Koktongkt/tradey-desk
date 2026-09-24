"""Compatibility exports for the transactional SQLite ledger.

Callers retain the historical durable_jsonl API while SQLite supplies the
transactional store and JSONL remains a byte-readable compatibility projection.
"""
import os  # Re-exported for existing durability fault-injection tests.

from sqlite_ledger import (
    LedgerConstraintError,
    LedgerDurabilityError,
    LedgerError,
    LedgerIntegrityError,
    append_jsonl,
    read_jsonl,
)


DurableAppendError = LedgerDurabilityError

__all__ = [
    "DurableAppendError",
    "LedgerConstraintError",
    "LedgerError",
    "LedgerIntegrityError",
    "append_jsonl",
    "read_jsonl",
]
