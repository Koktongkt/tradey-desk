"""Explicit, atomic prospective opportunity-policy baseline (paper testing).

Administrative apply is local-only and requires an exact approved manifest.
This module never calls a model, broker, reconciliation or repair routine.
"""
from __future__ import annotations

import argparse
import datetime as dt
from hashlib import sha256
import json
from pathlib import Path
import re

import entry_state
import sqlite_ledger as storage

POLICY_STREAM = 'private/opportunity_policy.jsonl'
# Historical v2 descriptors are immutable and predate research memory.
BASELINE_STREAMS = tuple(name for name in storage.DEFAULT_STREAMS
                         if name != 'private/research_memory.jsonl')
POLICY_VERSION = 2
_DIGEST = re.compile(r'[0-9a-f]{64}')


class CutoverError(RuntimeError):
    """An explicit prospective baseline is invalid or unavailable."""


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, ensure_ascii=True).encode('utf-8')


def manifest_digest(manifest: dict) -> str:
    return sha256(_canonical(manifest)).hexdigest()


def _prefix_digest(rows) -> str:
    return sha256(''.join(storage._canonical(row) for row in rows).encode('utf-8')).hexdigest()


def baseline_for_snapshot(snapshot: storage.LedgerSnapshot) -> dict:
    if set(snapshot.rows) != set(BASELINE_STREAMS):
        raise CutoverError('prospective_snapshot_incomplete')
    descriptor = {'version': 1, 'root': str(snapshot.root.resolve()),
                  'reopening_mode': 'manual_only',
                  'streams': {name: {'sequence': len(snapshot.rows[name]),
                                    'prefix_sha256': _prefix_digest(snapshot.rows[name])}
                              for name in sorted(BASELINE_STREAMS)}}
    return {**descriptor, 'baseline_id': manifest_digest(descriptor)}


def validate_baseline(snapshot: storage.LedgerSnapshot, descriptor: dict) -> dict:
    if (not isinstance(descriptor, dict)
            or set(descriptor) != {'version', 'root', 'reopening_mode', 'streams', 'baseline_id'}
            or type(descriptor['version']) is not int or descriptor['version'] != 1
            or descriptor['root'] != str(snapshot.root.resolve())
            or descriptor['reopening_mode'] != 'manual_only'
            or not isinstance(descriptor['streams'], dict)
            or set(descriptor['streams']) != set(BASELINE_STREAMS)
            or set(snapshot.rows) != set(BASELINE_STREAMS)):
        raise CutoverError('prospective_baseline_invalid')
    expected = manifest_digest({k: v for k, v in descriptor.items() if k != 'baseline_id'})
    if descriptor['baseline_id'] != expected:
        raise CutoverError('prospective_baseline_digest_mismatch')
    for name, boundary in descriptor['streams'].items():
        if (not isinstance(boundary, dict) or set(boundary) != {'sequence', 'prefix_sha256'}
                or type(boundary['sequence']) is not int or boundary['sequence'] < 0
                or not isinstance(boundary['prefix_sha256'], str)
                or _DIGEST.fullmatch(boundary['prefix_sha256']) is None
                or boundary['sequence'] > len(snapshot.rows[name])
                or _prefix_digest(snapshot.rows[name][:boundary['sequence']]) != boundary['prefix_sha256']):
            raise CutoverError('prospective_baseline_prefix_mismatch')
    return descriptor


def active_baseline(snapshot: storage.LedgerSnapshot) -> dict | None:
    activations = [(i, row) for i, row in enumerate(snapshot.rows.get(POLICY_STREAM, ()), 1)
                   if row.get('record_type') == 'activation']
    prospective = [(i, row) for i, row in activations
                   if row.get('policy_version') == POLICY_VERSION or 'prospective_baseline' in row]
    if not prospective:
        return None
    if len(activations) != 1 or len(prospective) != 1:
        raise CutoverError('prospective_reset_forbidden')
    sequence, row = prospective[0]
    if (set(row) != {'record_type', 'schema_version', 'policy_version', 'timestamp',
                     'manifest_sha256', 'prospective_baseline'}
            or type(row['policy_version']) is not int or row['policy_version'] != POLICY_VERSION):
        raise CutoverError('prospective_activation_invalid')
    baseline = validate_baseline(snapshot, row['prospective_baseline'])
    if sequence != baseline['streams'][POLICY_STREAM]['sequence'] + 1:
        raise CutoverError('prospective_activation_boundary_mismatch')
    if row['manifest_sha256'] != manifest_digest(_manifest(baseline)):
        raise CutoverError('prospective_activation_digest_mismatch')
    return baseline


def _manifest(baseline: dict) -> dict:
    return {'manifest_version': 2, 'policy_version': POLICY_VERSION, 'baseline': baseline}


def _snapshot(root: Path) -> storage.LedgerSnapshot:
    return storage.read_stream_snapshot_readonly(Path(root), BASELINE_STREAMS)


def prepare_manifest(root: Path) -> dict:
    snapshot = _snapshot(root)
    if (not storage.database_path(snapshot.root/'order_ledger.jsonl').exists()
            and any(snapshot.rows.values())):
        # Creating the first DB by appending only activation would leave other
        # existing projections unimported. Require the explicit migration first.
        raise CutoverError('prospective_storage_migration_required')
    if any(r.get('record_type') == 'activation' for r in snapshot.rows[POLICY_STREAM]):
        raise CutoverError('prospective_reset_forbidden')
    # Fully validate retained business history without demanding recovered links.
    from opportunity_state import _state_parts, _baseline_exclusions
    _state_parts(snapshot)
    _baseline_exclusions(snapshot.root)
    config = json.loads((snapshot.root/'autonomy_config.json').read_text())
    if config.get('broker_mode') != 'paper':
        raise CutoverError('paper_mode_required')
    return _manifest(baseline_for_snapshot(snapshot))


def activate_prospective(root: Path, manifest: dict, *, approved_manifest_sha256: str) -> dict:
    if (not isinstance(approved_manifest_sha256, str)
            or _DIGEST.fullmatch(approved_manifest_sha256) is None
            or manifest_digest(manifest) != approved_manifest_sha256):
        raise CutoverError('approval_digest_mismatch')
    if (not isinstance(manifest, dict) or set(manifest) != {'manifest_version', 'policy_version', 'baseline'}
            or type(manifest['manifest_version']) is not int or manifest['manifest_version'] != 2
            or type(manifest['policy_version']) is not int or manifest['policy_version'] != POLICY_VERSION):
        raise CutoverError('prospective_manifest_invalid')
    with entry_state.lock(Path(root)):
        snapshot = _snapshot(root)
        existing = active_baseline(snapshot)
        if existing is not None:
            if existing != manifest['baseline']:
                raise CutoverError('prospective_reset_forbidden')
            return {'policy_version': POLICY_VERSION, 'baseline_id': existing['baseline_id'],
                    'appended_activation': False, 'manifest_sha256': approved_manifest_sha256}
        expected = prepare_manifest(root)
        if expected != manifest:
            raise CutoverError('prospective_manifest_stale')
        record = {'record_type': 'activation', 'schema_version': 1,
                  'policy_version': POLICY_VERSION,
                  'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'manifest_sha256': approved_manifest_sha256,
                  'prospective_baseline': manifest['baseline']}
        # One canonical append: descriptor and activation never exist separately.
        storage.append_jsonl(Path(root)/POLICY_STREAM, record,
                             expected_watermark=snapshot.watermark)
    verified = active_baseline(_snapshot(root))
    if verified != manifest['baseline']:
        raise CutoverError('prospective_readback_failed')
    return {'policy_version': POLICY_VERSION, 'baseline_id': verified['baseline_id'],
            'appended_activation': True, 'manifest_sha256': approved_manifest_sha256}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=('prepare', 'validate', 'activate', 'status'))
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--manifest', type=Path)
    parser.add_argument('--approved-manifest-sha256')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    try:
        if args.command == 'prepare':
            result = prepare_manifest(args.root)
        elif args.command == 'status':
            result = {'baseline': active_baseline(_snapshot(args.root))}
        else:
            if args.manifest is None:
                raise CutoverError('manifest_required')
            manifest = json.loads(args.manifest.read_text())
            if args.command == 'validate':
                result = {'valid': prepare_manifest(args.root) == manifest,
                          'manifest_sha256': manifest_digest(manifest)}
            else:
                if not args.apply:
                    raise CutoverError('explicit_apply_flag_required')
                result = activate_prospective(args.root, manifest,
                    approved_manifest_sha256=args.approved_manifest_sha256)
        print(json.dumps(result, sort_keys=True))
        return 0
    except (CutoverError, storage.LedgerError, OSError, ValueError, RuntimeError) as error:
        print(json.dumps({'error': str(error)}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
