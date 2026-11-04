"""Read-only compatibility floor for explicitly activated opportunity policies."""
from __future__ import annotations

import datetime as dt
import re
from pathlib import Path

from sqlite_ledger import LedgerError, read_jsonl_stream_readonly

POLICY_STREAM = 'private/opportunity_policy.jsonl'
SUPPORTED_POLICY_VERSION = 1
_KNOWN_RECORD_TYPES = frozenset({
    'activation', 'identity_resolution', 'document_alias', 'reopen_grant', 'condition_approval',
})


class ActivationStateError(RuntimeError):
    """Policy state is unavailable, malformed, or newer than this runtime."""


def activation_version(root: Path) -> int:
    """Select activation versions only; this is not economic payload validation."""
    try:
        rows = read_jsonl_stream_readonly(root / POLICY_STREAM)
        version = 0
        for row in rows:
            if (row.get('record_type') not in _KNOWN_RECORD_TYPES
                    or type(row.get('schema_version')) is not int
                    or row['schema_version'] != 1
                    or not isinstance(row.get('timestamp'), str)):
                raise ValueError('invalid policy envelope')
            timestamp = dt.datetime.fromisoformat(row['timestamp'].replace('Z', '+00:00'))
            if timestamp.utcoffset() != dt.timedelta(0):
                raise ValueError('policy timestamp must be aware UTC')
            if row['record_type'] != 'activation':
                # Later feature readers must validate the complete economic schema.
                continue
            if (type(row.get('policy_version')) is not int
                    or row['policy_version'] <= 0
                    or not isinstance(row.get('manifest_sha256'), str)
                    or re.fullmatch(r'[0-9a-f]{64}', row['manifest_sha256']) is None):
                raise ValueError('invalid activation record')
            version = max(version, row['policy_version'])
        return version
    except (OSError, LedgerError, ValueError, TypeError) as error:
        raise ActivationStateError('opportunity_policy_state_unavailable') from error


def require_supported_activation(root: Path, *, supported: int) -> None:
    """Deny new entry when the active policy exceeds this runtime's support."""
    if activation_version(root) > supported:
        raise ActivationStateError('opportunity_policy_version_unsupported')
