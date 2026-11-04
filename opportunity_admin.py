"""Local-only administrative boundary: audited resolution, reviewed manifests,
explicit reopening grants and reviewed activation.

This module is the Task 3 administrative surface. It is never exposed to
discovery/reviewer subprocesses and performs no live/network/model work. Every
mutation is an append through the existing canonical ledger writer under the
existing entry-state lock order; audit and validation are strictly read-only.
Approval is never inferred from candidate/model text: the caller must supply
the exact reviewed canonical digest, and that digest binds integrity only —
it is not cryptographic proof of human consent.
"""
from __future__ import annotations

import argparse
import datetime as dt
from decimal import Decimal, InvalidOperation
import hashlib
import json
import os
from pathlib import Path
import re

import sys

import entry_state
from opportunity_identity import EventResolution, _load_binding
from opportunity_state import (
    INDEX_STREAMS,
    POLICY_STREAM,
    OpportunityIndex,
    OpportunityStateError,
    ConditionObservation,
    ReopeningClaim,
    allowance_identifier,
    claim_digest,
    claim_sealed,
    condition_consumed,
    _current_allowance,
    load_index,
    observation_digest,
    observation_sealed,
    seal_claim,
    seal_observation,
    _spends,
)
import sqlite_ledger as storage

CLAIMS_STREAM = 'private/opportunity_reopening_claims.jsonl'
MANIFEST_VERSION = 1
ACTIVATION_VERSION = 1
_IMPORTABLE_TYPES = ('identity_resolution', 'document_alias', 'condition_approval')
_FORBIDDEN_MANIFEST_TYPES = ('activation', 'reopen_grant')
_DIGEST = re.compile(r'[0-9a-f]{64}')
# Initial release: the approved structured-condition vocabulary only.
APPROVED_METRICS = frozenset({'completed_close_usd'})
APPROVED_SOURCES = frozenset({'massive_consolidated_completed_daily'})
APPROVED_UNITS = frozenset({'USD'})
APPROVED_OPERATORS = frozenset({'<=', '>='})
_CONDITION_KEYS = frozenset({
    'metric', 'operator', 'threshold', 'units', 'source_kind', 'expires_at',
    'observation_max_age_seconds', 'baseline_ref', 'allowance_id'})


class OpportunityAdminError(RuntimeError):
    """Administrative action refused, unavailable, or unsupported."""


def _canonical(value) -> bytes:
    """Manifest/approval canonical encoding: sorted keys, compact, finite, UTF-8."""
    try:
        return json.dumps(value, sort_keys=True, separators=(',', ':'),
                          allow_nan=False, ensure_ascii=False).encode('utf-8')
    except (ValueError, TypeError) as error:
        raise OpportunityAdminError('canonical_encoding_failed') from error


def canonical_manifest_digest(manifest) -> str:
    if not isinstance(manifest, dict):
        raise OpportunityAdminError('manifest_object_required')
    return hashlib.sha256(_canonical(manifest)).hexdigest()


def _utc_text(stamp: dt.datetime) -> str:
    if not isinstance(stamp, dt.datetime) or stamp.tzinfo is None \
            or stamp.utcoffset() != dt.timedelta(0):
        raise OpportunityAdminError('aware_utc_clock_required')
    return stamp.astimezone(dt.timezone.utc).isoformat()


def _valid_stamp(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return stamp.utcoffset() == dt.timedelta(0)


# ---------------------------------------------------------------------------
# Condition / observation / evaluation
# ---------------------------------------------------------------------------

class Condition:
    """A previously approved deterministic reopening condition.

    Constructed only from strictly validated canonical records; unsupported
    metrics, sources, units, operators or thresholds fail closed at creation.
    """

    __slots__ = ('condition_id', 'event_id', 'allowance_id', 'metric', 'operator',
                 'threshold', 'units', 'source_kind', 'expires_at',
                 'observation_max_age_seconds', 'baseline_ref')

    def __init__(self, condition_id: str, event_id: str, allowance_id: str,
                 metric: str, operator: str, threshold: str, units: str,
                 source_kind: str, expires_at: str,
                 observation_max_age_seconds: int, baseline_ref: str):
        values = (condition_id, event_id, allowance_id, metric, operator,
                  threshold, units, source_kind, expires_at, baseline_ref)
        if (not all(isinstance(v, str) and v for v in values)
                or type(observation_max_age_seconds) is not int
                or observation_max_age_seconds <= 0):
            raise ValueError('invalid_condition_parameters')
        if (metric not in APPROVED_METRICS or source_kind not in APPROVED_SOURCES
                or units not in APPROVED_UNITS or operator not in APPROVED_OPERATORS):
            raise ValueError('unsupported_condition_vocabulary')
        try:
            parsed = Decimal(threshold)
        except InvalidOperation as error:
            raise ValueError('invalid_condition_threshold') from error
        if not parsed.is_finite() or parsed <= 0:
            raise ValueError('invalid_condition_threshold')
        if not _valid_stamp(expires_at):
            raise ValueError('invalid_condition_expiry')
        object.__setattr__(self, 'threshold', parsed)
        for name, value in (('condition_id', condition_id), ('event_id', event_id),
                            ('allowance_id', allowance_id), ('metric', metric),
                            ('operator', operator), ('units', units),
                            ('source_kind', source_kind),
                            ('expires_at', expires_at),
                            ('observation_max_age_seconds', observation_max_age_seconds),
                            ('baseline_ref', baseline_ref)):
            object.__setattr__(self, name, value)

    def __setattr__(self, name, value):
        raise AttributeError('condition_is_immutable')

    def record(self) -> dict:
        return {'metric': self.metric, 'operator': self.operator,
                'threshold': str(self.threshold), 'units': self.units,
                'source_kind': self.source_kind, 'expires_at': self.expires_at,
                'observation_max_age_seconds': self.observation_max_age_seconds,
                'baseline_ref': self.baseline_ref, 'allowance_id': self.allowance_id}

    @classmethod
    def from_record(cls, condition_id: str, event_id: str, record) -> 'Condition':
        if not isinstance(record, dict) or set(record) != _CONDITION_KEYS:
            raise ValueError('invalid_condition_record')
        return cls(condition_id, event_id, record['allowance_id'],
                   record['metric'], record['operator'], record['threshold'],
                   record['units'], record['source_kind'], record['expires_at'],
                   record['observation_max_age_seconds'], record['baseline_ref'])


def _lineage(observation: ConditionObservation) -> dict:
    return {'event_id': observation.event_id, 'metric': observation.metric,
            'value': str(observation.value), 'units': observation.units,
            'source_kind': observation.source_kind,
            'observed_at': observation.observed_at.isoformat(),
            'evidence_ref': observation.evidence_ref}


def observe_completed_close(adapter_result: dict, *, event_id: str,
                            evidence_ref: str) -> ConditionObservation:
    """Trusted acquisition factory for the synchronized completed-close result.

    Called only on the existing synchronized-price adapter result; candidate
    or model price fields are never accepted. The observation timestamp is the
    adapter's original `market_prices_at` aggregate timestamp, not retrieval
    time or an invented close instant.
    """
    if not isinstance(adapter_result, dict):
        raise ValueError('adapter_result_required')
    if (adapter_result.get('metric') != 'completed_close_usd'
            or adapter_result.get('units') != 'USD'
            or adapter_result.get('source') != 'massive_consolidated_completed_daily'):
        raise ValueError('unsupported_observation_vocabulary')
    if not isinstance(event_id, str) or not event_id:
        raise ValueError('event_id_required')
    if not isinstance(evidence_ref, str) or not evidence_ref:
        raise ValueError('evidence_ref_required')
    raw = adapter_result.get('value')
    if not isinstance(raw, str):
        raise ValueError('invalid_observation_value')
    try:
        value = Decimal(raw)
    except InvalidOperation as error:
        raise ValueError('invalid_observation_value') from error
    if not value.is_finite() or value <= 0:
        raise ValueError('invalid_observation_value')
    stamp = adapter_result.get('market_prices_at')
    if not _valid_stamp(stamp):
        raise ValueError('invalid_market_prices_at_timestamp')
    observed_at = dt.datetime.fromisoformat(stamp.replace('Z', '+00:00'))
    return seal_observation(ConditionObservation(
        event_id=event_id, metric='completed_close_usd', value=value, units='USD',
        source_kind='massive_consolidated_completed_daily',
        observed_at=observed_at, evidence_ref=evidence_ref, seal=None))


def evaluate_condition(condition: Condition, observation, *,
                       now: dt.datetime) -> bool:
    """Deterministic fail-closed evaluation; raw dictionaries and unsealed
    observations never satisfy an approved condition."""
    try:
        if not isinstance(condition, Condition):
            return False
        if not observation_sealed(observation):
            return False
        if not isinstance(now, dt.datetime) or now.tzinfo is None \
                or now.utcoffset() != dt.timedelta(0):
            return False
        if (observation.event_id != condition.event_id
                or observation.metric != condition.metric
                or observation.units != condition.units
                or observation.source_kind != condition.source_kind):
            return False
        value = observation.value
        if not isinstance(value, Decimal) or not value.is_finite() or value <= 0:
            return False
        observed_at = observation.observed_at.astimezone(dt.timezone.utc)
        if observed_at > now:
            return False  # Future observations are never fresh evidence.
        if (now - observed_at).total_seconds() > condition.observation_max_age_seconds:
            return False
        expiry = dt.datetime.fromisoformat(
            condition.expires_at.replace('Z', '+00:00'))
        if now.astimezone(dt.timezone.utc) > expiry:
            return False  # Expiry equality is still within validity.
        if condition.operator == '<=':
            return value <= condition.threshold
        return value >= condition.threshold
    except (ValueError, TypeError, OverflowError):
        return False


# ---------------------------------------------------------------------------
# Read-only audit and manifest validation
# ---------------------------------------------------------------------------

def _index_or_fail(root: Path) -> OpportunityIndex:
    try:
        return load_index(Path(root))
    except OpportunityStateError as error:
        raise OpportunityAdminError('opportunity_policy_state_unavailable') from error


def audit_history(root: Path) -> dict:
    """Read-only audit: version, base watermarks, proposed bindings and
    unresolved cases, derived only from the coherent validated index."""
    index = _index_or_fail(root)
    bindings = {}
    for event_id, resolution in index.resolutions.items():
        bindings[event_id] = {
            'family': resolution.family, 'period': resolution.period,
            'symbol': resolution.issuer.symbol if resolution.issuer else None,
            'documents': len(resolution.documents)}
    return {
        'policy_version': index.activated_version,
        'base_watermark': list(index.snapshot.watermark),
        'proposed_bindings': bindings,
        'document_aliases': dict(sorted(index.document_aliases.items())),
        'unresolved_cases': sorted(index.unresolved_dossiers),
        'condition_approvals': sorted(index.conditions),
        'consumed_conditions': sorted(
            {grant.get('condition_id') for grant in index.grants.values()
             if isinstance(grant.get('condition_id'), str)}),
        'reopen_grants': sorted(index.grants),
        'dossier_allowance_count': len(index.dossier_allowances),
    }


def _manifest_records(manifest) -> list:
    if (not isinstance(manifest, dict)
            or manifest.get('manifest_version') != MANIFEST_VERSION):
        raise OpportunityAdminError('unsupported_manifest_version')
    records = manifest.get('records')
    if not isinstance(records, list):
        raise OpportunityAdminError('invalid_manifest_records')
    return records


def _validated_identity_record(record: dict, index: OpportunityIndex,
                               snapshot_rows: dict) -> dict:
    resolution_payload = record.get('resolution')
    try:
        resolution = _load_binding(resolution_payload)
    except (ValueError, TypeError, KeyError) as error:
        raise OpportunityAdminError('invalid_manifest_resolution') from error
    source = record.get('source')
    if not isinstance(source, dict):
        raise OpportunityAdminError('invalid_manifest_source_reference')
    stream, sequence = source.get('stream'), source.get('sequence')
    if stream not in INDEX_STREAMS or type(sequence) is not int or sequence < 1:
        raise OpportunityAdminError('invalid_manifest_source_reference')
    rows = snapshot_rows.get(stream)
    if not isinstance(rows, tuple) or sequence > len(rows):
        raise OpportunityAdminError('manifest_source_sequence_out_of_range')
    row = rows[sequence - 1]
    if hashlib.sha256(_canonical(row)).hexdigest() != source.get('row_sha256'):
        raise OpportunityAdminError('manifest_source_digest_mismatch')
    # No hidden resets: a dossier already bound to a different event stays bound.
    dossier = row.get('dossier_hash') if isinstance(row, dict) else None
    if isinstance(dossier, str) and dossier in index.dossier_allowances:
        bound_event = index.allowance_events.get(index.dossier_allowances[dossier])
        if bound_event is not None and bound_event != resolution.event_id:
            raise OpportunityAdminError('manifest_hidden_reset')
    return {'record_type': 'identity_resolution', 'schema_version': 1,
            'timestamp': record.get('timestamp'),
            'resolution': resolution_payload, 'source': dict(source)}


def _validated_alias_record(record: dict, index: OpportunityIndex) -> dict:
    alias, event_id = record.get('alias'), record.get('event_id')
    if (not isinstance(alias, str) or not alias or len(alias) > 256
            or not isinstance(event_id, str) or not event_id):
        raise OpportunityAdminError('invalid_manifest_alias')
    existing = index.document_aliases.get(alias)
    if existing is not None and existing != event_id:
        raise OpportunityAdminError('manifest_hidden_reset')
    if event_id not in index.resolutions:
        raise OpportunityAdminError('manifest_unknown_event')
    return {'record_type': 'document_alias', 'schema_version': 1,
            'timestamp': record.get('timestamp'), 'alias': alias,
            'event_id': event_id}


def _validated_condition_record(record: dict, index: OpportunityIndex) -> dict:
    condition_id, event_id = record.get('condition_id'), record.get('event_id')
    if not isinstance(condition_id, str) or not condition_id:
        raise OpportunityAdminError('invalid_manifest_condition')
    try:
        condition = Condition.from_record(condition_id, event_id,
                                          record.get('condition'))
    except (ValueError, TypeError) as error:
        raise OpportunityAdminError('invalid_manifest_condition') from error
    if event_id not in index.resolutions:
        raise OpportunityAdminError('manifest_unknown_event')
    existing = index.conditions.get(condition_id)
    if existing is not None and _canonical(existing.get('condition')) != _canonical(condition.record()):
        raise OpportunityAdminError('manifest_hidden_reset')
    return {'record_type': 'condition_approval', 'schema_version': 1,
            'timestamp': record.get('timestamp'), 'condition_id': condition_id,
            'event_id': event_id, 'condition': condition.record()}


def validate_manifest(root: Path, manifest: dict) -> dict:
    """Read-only manifest validation. Writes nothing; failure is a report."""
    errors: list[str] = []
    records: list[dict] = []
    try:
        index = _index_or_fail(root)
        raw = _manifest_records(manifest)
    except OpportunityAdminError as error:
        return {'valid': False, 'errors': [str(error)], 'records': 0}
    snapshot_rows = index.snapshot.rows
    for position, record in enumerate(raw):
        try:
            if not isinstance(record, dict):
                raise OpportunityAdminError('invalid_manifest_record')
            kind = record.get('record_type')
            if kind in _FORBIDDEN_MANIFEST_TYPES:
                raise OpportunityAdminError('manifest_hidden_reset')
            if kind not in _IMPORTABLE_TYPES:
                raise OpportunityAdminError('unsupported_manifest_record_type')
            if (record.get('schema_version') != 1
                    or not _valid_stamp(record.get('timestamp'))):
                raise OpportunityAdminError('invalid_manifest_record_envelope')
            if kind == 'identity_resolution':
                records.append(_validated_identity_record(record, index, snapshot_rows))
            elif kind == 'document_alias':
                records.append(_validated_alias_record(record, index))
            else:
                records.append(_validated_condition_record(record, index))
        except OpportunityAdminError as error:
            errors.append(f'record_{position}:{error}')
    seen = set()
    for record in records:
        key = _canonical(record)
        if key in seen:
            errors.append(f"duplicate_record:{record['record_type']}")
        seen.add(key)
    return {'valid': not errors, 'errors': errors,
            'records': records, 'record_count': len(records)}


# ---------------------------------------------------------------------------
# Locked mutation entry points (canonical append only, existing lock order)
# ---------------------------------------------------------------------------

def _policy_rows(root: Path) -> list[dict]:
    try:
        return storage.read_jsonl_stream_readonly(Path(root) / POLICY_STREAM)
    except (storage.LedgerError, OSError) as error:
        raise OpportunityAdminError('opportunity_policy_state_unavailable') from error


def _require_explicit_digest(value) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise OpportunityAdminError('explicit_approved_digest_required')


def import_manifest(root: Path, manifest: dict, *,
                    approved_manifest_sha256: str) -> dict:
    """Idempotent canonical append of reviewed manifest records.

    Requires the caller's explicit reviewed canonical digest; an inferred
    approval from source or model text is impossible by construction.
    """
    _require_explicit_digest(approved_manifest_sha256)
    if canonical_manifest_digest(manifest) != approved_manifest_sha256:
        raise OpportunityAdminError('approval_digest_mismatch')
    if not validate_manifest(root, manifest)['valid']:
        raise OpportunityAdminError('manifest_validation_failed')
    rows: list[dict] = []
    with entry_state.lock(Path(root)):
        # Revalidate under the lock so hidden-reset checks see concurrent appends.
        report = validate_manifest(root, manifest)
        if not report['valid']:
            raise OpportunityAdminError(
                'manifest_validation_failed:' + ';'.join(report['errors']))
        index = _index_or_fail(root)
        existing = {_canonical(row) for row in _policy_rows(root)}
        for record in report['records']:
            if _canonical(record) not in existing:
                rows.append(record)
        if rows:
            try:
                for record in rows:
                    storage.append_jsonl(Path(root) / POLICY_STREAM, record)
            except (storage.LedgerError, OSError) as error:
                raise OpportunityAdminError('policy_append_failed') from error
    return {'manifest_sha256': approved_manifest_sha256,
            'appended': len(rows),
            'already_present': len(report['records']) - len(rows)}


def activate(root: Path, manifest: dict, *,
             approved_manifest_sha256: str) -> dict:
    """Reviewed activation: import the manifest, then append one activation
    provenance record. Idempotent; never fabricates receipts."""
    _require_explicit_digest(approved_manifest_sha256)
    if canonical_manifest_digest(manifest) != approved_manifest_sha256:
        raise OpportunityAdminError('approval_digest_mismatch')
    activation = manifest.get('activation') if isinstance(manifest, dict) else None
    if (not isinstance(activation, dict)
            or type(activation.get('policy_version')) is not int
            or activation['policy_version'] <= 0):
        raise OpportunityAdminError('manifest_activation_version_required')
    imported = import_manifest(root, manifest,
                               approved_manifest_sha256=approved_manifest_sha256)
    appended = False
    with entry_state.lock(Path(root)):
        rows = _policy_rows(root)
        if not any(row.get('record_type') == 'activation'
                   and row.get('manifest_sha256') == approved_manifest_sha256
                   and row.get('policy_version') == activation['policy_version']
                   for row in rows):
            index = _index_or_fail(root)
            if index.activated_version > activation['policy_version']:
                raise OpportunityAdminError('activation_version_regression')
            try:
                storage.append_jsonl(Path(root) / POLICY_STREAM, dict(
                    record_type='activation', schema_version=ACTIVATION_VERSION,
                    policy_version=activation['policy_version'],
                    timestamp=_utc_text(dt.datetime.now(dt.timezone.utc)),
                    manifest_sha256=approved_manifest_sha256))
            except (storage.LedgerError, OSError) as error:
                raise OpportunityAdminError('activation_append_failed') from error
            appended = True
    return {**imported, 'appended_activation': appended,
            'policy_version': activation['policy_version']}


def _require_spent(index: OpportunityIndex, event_id: str) -> None:
    rows = [r for a, rs in index.allowance_reviews.items()
            for r in rs if index.allowance_events.get(a) == event_id]
    if not any(_spends(r) for r in rows):
        raise OpportunityAdminError('event_not_spent')


def _claim_store_rows(root: Path) -> list[dict]:
    try:
        return storage.read_jsonl_stream_readonly(Path(root) / CLAIMS_STREAM)
    except (storage.LedgerError, OSError) as error:
        raise OpportunityAdminError('claim_store_unavailable') from error


def record_reopening_claim(root: Path, claim: ReopeningClaim) -> dict:
    """Trusted persistence of one sealed claim; idempotent on replay."""
    if not claim_sealed(claim):
        raise OpportunityAdminError('claim_seal_invalid')
    row = {'record_type': 'reopening_claim', 'schema_version': 1,
           'timestamp': _utc_text(dt.datetime.now(dt.timezone.utc)),
           'claim': serialize_reopening_claim(claim),
           'claim_sha256': claim_digest(claim)}
    if any(r.get('claim_sha256') == row['claim_sha256']
           for r in _claim_store_rows(root)):
        return {'recorded': False, 'claim_sha256': row['claim_sha256']}
    try:
        storage.append_jsonl(Path(root) / CLAIMS_STREAM, row)
    except (storage.LedgerError, OSError) as error:
        raise OpportunityAdminError('claim_append_failed') from error
    return {'recorded': True, 'claim_sha256': row['claim_sha256']}


def record_observation_evidence(root: Path,
                                observation: ConditionObservation) -> dict:
    """Trusted persistence of one sealed observation for explicit approval."""
    if not observation_sealed(observation):
        raise OpportunityAdminError('observation_seal_invalid')
    row = {'record_type': 'observation_evidence', 'schema_version': 1,
           'timestamp': _utc_text(dt.datetime.now(dt.timezone.utc)),
           'observation': _lineage(observation),
           'observation_sha256': observation_digest(observation)}
    if any(r.get('observation_sha256') == row['observation_sha256']
           for r in _claim_store_rows(root)):
        return {'recorded': False, 'observation_sha256': row['observation_sha256']}
    try:
        storage.append_jsonl(Path(root) / CLAIMS_STREAM, row)
    except (storage.LedgerError, OSError) as error:
        raise OpportunityAdminError('evidence_append_failed') from error
    return {'recorded': True, 'observation_sha256': row['observation_sha256']}


def serialize_reopening_claim(claim: ReopeningClaim) -> dict:
    """Serialization from sealed server-created claims only. No serialization
    field itself grants authority; restoration revalidates everything."""
    if not claim_sealed(claim):
        raise OpportunityAdminError('claim_seal_invalid')
    return {'claim_version': 1, 'condition_id': claim.condition_id,
            'prior_allowance_id': claim.prior_allowance_id,
            'event_id': claim.observation.event_id,
            'observation': _lineage(claim.observation),
            'claim_sha256': claim_digest(claim)}


def make_reopening_claim(index: OpportunityIndex, resolution, observation, *,
                         now: dt.datetime) -> ReopeningClaim | None:
    """Build a sealed claim when a currently approved, unconsumed condition is
    satisfied by a sealed observation for a spent event; otherwise None."""
    try:
        if not observation_sealed(observation):
            return None
        if not isinstance(now, dt.datetime) or now.tzinfo is None:
            return None
        if (not isinstance(resolution, EventResolution)
                or resolution.status != 'verified' or resolution.event_id is None):
            return None
        event_id = resolution.event_id
        if event_id not in index.resolutions:
            return None
        for condition_id, row in sorted(index.conditions.items()):
            if row.get('event_id') != event_id:
                continue
            if condition_consumed(index, condition_id):
                continue
            try:
                approved = Condition.from_record(condition_id, event_id,
                                                 row.get('condition'))
            except (ValueError, TypeError):
                continue
            if not evaluate_condition(approved, observation, now=now):
                continue
            if approved.allowance_id != _current_allowance(index, event_id):
                continue
            prior = approved.allowance_id
            rows = [r for a, rs in index.allowance_reviews.items()
                    for r in rs if index.allowance_events.get(a) == event_id]
            if not any(_spends(r) for r in rows):
                return None
            return seal_claim(ReopeningClaim(
                condition_id=condition_id, prior_allowance_id=prior,
                observation=observation, seal=None))
        return None
    except (OpportunityStateError, ValueError, TypeError):
        return None


def _restore_observation(lineage: dict) -> ConditionObservation:
    try:
        value = Decimal(lineage['value'])
        observed_at = dt.datetime.fromisoformat(
            lineage['observed_at'].replace('Z', '+00:00'))
        if not isinstance(lineage.get('evidence_ref'), str) or not lineage['evidence_ref']:
            raise ValueError('evidence_ref_required')
        return seal_observation(ConditionObservation(
            event_id=lineage['event_id'], metric=lineage['metric'], value=value,
            units=lineage['units'], source_kind=lineage['source_kind'],
            observed_at=observed_at, evidence_ref=lineage['evidence_ref'],
            seal=None))
    except (KeyError, ValueError, TypeError, InvalidOperation) as error:
        raise OpportunityAdminError('claim_lineage_mismatch') from error


def _verify_claim_against_index(index: OpportunityIndex, claim: ReopeningClaim, *,
                                now: dt.datetime) -> Condition:
    """Full canonical lineage verification; forged, expired, consumed or
    altered claims fail closed."""
    if not claim_sealed(claim):
        raise OpportunityAdminError('claim_seal_invalid')
    condition = index.conditions.get(claim.condition_id)
    if condition is None:
        raise OpportunityAdminError('condition_not_approved')
    if condition.get('event_id') != claim.observation.event_id:
        raise OpportunityAdminError('condition_event_mismatch')
    try:
        approved = Condition.from_record(claim.condition_id,
                                         condition.get('event_id'),
                                         condition.get('condition'))
    except (ValueError, TypeError) as error:
        raise OpportunityAdminError('condition_unsupported') from error
    observation = claim.observation
    if (observation.metric != approved.metric or observation.units != approved.units
            or observation.source_kind != approved.source_kind):
        raise OpportunityAdminError('observation_lineage_mismatch')
    if (claim.prior_allowance_id != approved.allowance_id
            or claim.prior_allowance_id != _current_allowance(
                index, claim.observation.event_id)):
        raise OpportunityAdminError('claim_prior_allowance_mismatch')
    if condition_consumed(index, claim.condition_id):
        raise OpportunityAdminError('condition_already_consumed')
    if not evaluate_condition(approved, observation, now=now):
        raise OpportunityAdminError('condition_not_satisfied')
    return approved


def restore_reopening_claim(index: OpportunityIndex, dossier_hash: str, *,
                            now: dt.datetime) -> ReopeningClaim:
    """Durable reconstruction from server-created claim rows.

    Requires the exact canonical candidate/observation lineage through the
    index and a currently approved, fresh, unconsumed condition; model-authored
    observation fields are never accepted.
    """
    import re as _re
    from opportunity_state import _DOSSIER_HASH
    if (not isinstance(dossier_hash, str)
            or _DOSSIER_HASH.fullmatch(dossier_hash) is None):
        raise OpportunityAdminError('dossier_hash_required')
    allowance = index.dossier_allowances.get(dossier_hash)
    event_id = index.allowance_events.get(allowance) if allowance else None
    if event_id is None:
        raise OpportunityAdminError('dossier_binding_missing')
    rows = [r for r in _claim_store_rows(index.snapshot.root)
            if r.get('record_type') == 'reopening_claim'
            and isinstance(r.get('claim'), dict)
            and r['claim'].get('event_id') == event_id]
    if not rows:
        raise OpportunityAdminError('no_durable_claim')
    row = rows[-1]
    payload = row['claim']
    if (row.get('claim_sha256') != payload.get('claim_sha256')
            or not isinstance(payload.get('observation'), dict)):
        raise OpportunityAdminError('claim_lineage_mismatch')
    observation = _restore_observation(payload['observation'])
    try:
        claim = seal_claim(ReopeningClaim(
            condition_id=payload['condition_id'],
            prior_allowance_id=payload['prior_allowance_id'],
            observation=observation, seal=None))
    except (KeyError, TypeError) as error:
        raise OpportunityAdminError('claim_lineage_mismatch') from error
    if claim_digest(claim) != payload.get('claim_sha256'):
        raise OpportunityAdminError('claim_lineage_mismatch')
    _verify_claim_against_index(index, claim, now=now)
    return claim


def _grant_record(index: OpportunityIndex, *, event_id: str, condition_id,
                  approval_digest: str, lineage: dict, lineage_sha: str) -> dict:
    generation = 0
    for grant in index.grants.values():
        if grant.get('event_id') == event_id:
            generation = max(generation, grant['generation'])
    prior = allowance_identifier(event_id, generation)
    return {
        'record_type': 'reopen_grant', 'schema_version': 1,
        'timestamp': _utc_text(dt.datetime.now(dt.timezone.utc)),
        'event_id': event_id, 'generation': generation + 1,
        'prior_allowance_id': prior,
        'allowance_id': allowance_identifier(event_id, generation + 1),
        'condition_id': condition_id,
        'approval_digest': approval_digest,
        'observation': lineage,
        'lineage_sha256': lineage_sha,
    }


def _append_grant(root: Path, record: dict) -> str:
    try:
        storage.append_jsonl(Path(root) / POLICY_STREAM, record)
    except (storage.LedgerError, OSError) as error:
        raise OpportunityAdminError('grant_append_failed') from error
    return record['allowance_id']


def commit_reopening_claim(root: Path, claim: ReopeningClaim, *,
                           dossier_hash: str, now: dt.datetime) -> str:
    """One durable one-shot reopen grant derived under the entry lock.

    Revalidates the full claim lineage against a fresh index under the lock;
    a lost acknowledgement is recoverable by replay, which returns the same
    one-shot durable allowance ID without a second grant record.
    """
    if not isinstance(dossier_hash, str) or not dossier_hash:
        raise OpportunityAdminError('dossier_hash_required')
    with entry_state.lock(Path(root)):
        index = _index_or_fail(root)
        lineage = claim_digest(claim) if claim_sealed(claim) else None
        if lineage is not None:
            for grant in index.grants.values():
                if grant.get('lineage_sha256') == lineage:
                    return grant['allowance_id']  # Lost-ack replay.
        _verify_claim_against_index(index, claim, now=now)
        if index.dossier_allowances.get(dossier_hash) != claim.prior_allowance_id:
            raise OpportunityAdminError('claim_dossier_mismatch')
        _require_spent(index, claim.observation.event_id)
        # The claim must be durably recorded server-side; an unbacked
        # in-memory claim can never commit.
        if not any(r.get('claim_sha256') == lineage
                   for r in _claim_store_rows(root)):
            raise OpportunityAdminError('claim_not_durable')
        approval_digest = hashlib.sha256(_canonical(
            index.conditions[claim.condition_id])).hexdigest()
        record = _grant_record(
            index, event_id=claim.observation.event_id,
            condition_id=claim.condition_id, approval_digest=approval_digest,
            lineage=_lineage(claim.observation), lineage_sha=lineage)
        return _append_grant(root, record)


def grant_reopening(root: Path, approval: dict, *,
                    approved_manifest_sha256: str) -> str:
    """Explicit evidence-backed reopening authorization.

    The approval must reference a durably recorded sealed observation; the
    explicit reviewed canonical digest is required and never inferred. The
    durable grant holds the authorization in one record, derived idempotently.
    """
    _require_explicit_digest(approved_manifest_sha256)
    if canonical_manifest_digest(approval) != approved_manifest_sha256:
        raise OpportunityAdminError('approval_digest_mismatch')
    if (not isinstance(approval, dict) or approval.get('approval_version') != 1
            or approval.get('kind') != 'explicit_reopening'
            or not isinstance(approval.get('reason'), str) or not approval['reason']
            or not isinstance(approval.get('changed_fact'), str)
            or not approval['changed_fact']):
        raise OpportunityAdminError('invalid_reopening_approval')
    observation_sha = approval.get('observation_sha256')
    if not isinstance(observation_sha, str) or _DIGEST.fullmatch(observation_sha) is None:
        raise OpportunityAdminError('invalid_reopening_approval')
    with entry_state.lock(Path(root)):
        index = _index_or_fail(root)
        # Idempotent derivation: the same approval returns the same allowance.
        for grant in index.grants.values():
            if grant.get('approval_digest') == approved_manifest_sha256:
                return grant['allowance_id']
        event_id = approval.get('event_id')
        if not isinstance(event_id, str) or event_id not in index.resolutions:
            raise OpportunityAdminError('unknown_event')
        lineage = None
        for row in _claim_store_rows(index.snapshot.root):
            if (row.get('record_type') == 'observation_evidence'
                    and row.get('observation_sha256') == observation_sha):
                lineage = row.get('observation')
        if not isinstance(lineage, dict) or lineage.get('event_id') != event_id:
            raise OpportunityAdminError('observation_evidence_missing')
        if approval.get('prior_allowance_id') != _current_allowance(index, event_id):
            raise OpportunityAdminError('prior_allowance_mismatch')
        _require_spent(index, event_id)
        record = _grant_record(index, event_id=event_id, condition_id=None,
                               approval_digest=approved_manifest_sha256,
                               lineage=lineage, lineage_sha=observation_sha)
        return _append_grant(root, record)


# ---------------------------------------------------------------------------
# Read-only default CLI (local administrative use only)
# ---------------------------------------------------------------------------

def _read_artifact(path: Path) -> bytes:
    try:
        return Path(path).read_bytes()
    except OSError as error:
        raise OpportunityAdminError('artifact_unreadable') from error


def _parse_artifact(raw: bytes):
    try:
        return json.loads(raw.decode('utf-8'))
    except (UnicodeDecodeError, ValueError) as error:
        raise OpportunityAdminError('artifact_not_valid_json') from error


def _mutation_payload(args) -> tuple[dict, str]:
    """Verify BOTH the raw artifact digest and the parsed canonical digest
    against the explicit approval before any mutation."""
    if not args.apply:
        raise OpportunityAdminError('explicit_apply_flag_required')
    digest = args.approved_sha256
    _require_explicit_digest(digest)
    raw = _read_artifact(args.manifest)
    if hashlib.sha256(raw).hexdigest() != digest:
        raise OpportunityAdminError('raw_artifact_digest_mismatch')
    payload = _parse_artifact(raw)
    if canonical_manifest_digest(payload) != digest:
        raise OpportunityAdminError('canonical_artifact_digest_mismatch')
    return payload, digest


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog='opportunity_admin',
        description='Read-only default administrative boundary for opportunity policy.')
    parser.add_argument('command', choices=('audit', 'validate', 'import',
                                            'reopen', 'activate'))
    parser.add_argument('root')
    parser.add_argument('--manifest')
    parser.add_argument('--approved-sha256')
    parser.add_argument('--out')
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args(argv)
    root = Path(args.root)
    try:
        if args.command == 'audit':
            report = audit_history(root)
            payload = _canonical(report)
            if args.out:
                descriptor = os.open(args.out, os.O_WRONLY | os.O_CREAT | os.O_TRUNC,
                                     0o600)
                try:
                    os.write(descriptor, payload)
                    os.fsync(descriptor)
                finally:
                    os.close(descriptor)
                os.chmod(args.out, 0o600)
            else:
                sys.stdout.buffer.write(payload + b'\n')
            return 0
        if args.command == 'validate':
            raw = _read_artifact(args.manifest)
            report = validate_manifest(root, _parse_artifact(raw))
            sys.stdout.buffer.write(_canonical(report) + b'\n')
            return 0 if report['valid'] else 1
        payload, digest = _mutation_payload(args)
        if args.command == 'import':
            result = import_manifest(root, payload, approved_manifest_sha256=digest)
        elif args.command == 'reopen':
            result = {'allowance_id': grant_reopening(
                root, payload, approved_manifest_sha256=digest)}
        else:
            result = activate(root, payload, approved_manifest_sha256=digest)
        sys.stdout.buffer.write(_canonical(result) + b'\n')
        return 0
    except OpportunityAdminError as error:
        sys.stderr.write(f'opportunity_admin: {error}\n')
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
