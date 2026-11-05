"""Coherent read-only history/allowance index and event entry policy decisions.

This module owns validated opportunity state: it builds typed dictionaries
once from a canonical read-only ledger snapshot and derives fail-closed
policy decisions. It never writes, imports, repairs, or schema-initializes
storage, and it creates no private locks — the existing canonical writer
lock is the only serialization point. Untrusted candidate/model dictionaries
never become trusted state merely by matching JSON shape; policy records are
validated against the same strict envelopes as Task 0/1.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import datetime as dt
from decimal import Decimal
from hashlib import sha256
import json
import re
from pathlib import Path
from types import MappingProxyType

from opportunity_activation import _KNOWN_RECORD_TYPES
from opportunity_identity import EventResolution, _load_binding, candidate_identity
from opportunity_activation import activation_version, ActivationStateError
from sqlite_ledger import (
    LedgerError,
    LedgerSnapshot,
    read_stream_snapshot_readonly,
)

POLICY_STREAM = 'private/opportunity_policy.jsonl'
REVIEWS_STREAM = 'private/reviews.jsonl'
CANDIDATES_STREAM = 'candidates.jsonl'
INDEX_STREAMS = (POLICY_STREAM, REVIEWS_STREAM, CANDIDATES_STREAM)

# Fixed fail-closed vocabulary for proven-unrecoverable canonical history.
MISSING_HISTORY_KINDS = ('legacy_review_unlinked', 'filled_buy_unlinked')
MISSING_HISTORY_REASONS = ('recovery_exhausted_exact_link_unavailable',)
CLEARANCE_REASONS = ('permanently_unattributable_user_acknowledged',)
CLEARANCE_KEYS = {'record_type', 'schema_version', 'timestamp', 'gap_source',
                  'clearance_reason'}
TRADE_JOURNAL_STREAM = 'trade_journal.jsonl'
# Dedicated gap-source allowlist: separate from INDEX_STREAMS so binding
# sources can never name trade_journal.jsonl (DESIGN-REVIEW I-3).
MIGRATION_SOURCE_STREAMS = (REVIEWS_STREAM, TRADE_JOURNAL_STREAM)
# Single coherent read for the migration-validation path: widening the
# requested-stream caller argument, never a second separate read (F-1).
MIGRATION_SNAPSHOT_STREAMS = INDEX_STREAMS + (TRADE_JOURNAL_STREAM,)
_HINT_KEY = re.compile(r'[0-9a-f]{64}')

# Exact reuse of the candidate_retry completed-review vocabulary. A decision
# outside this set (or fatal flags) is a completed dissent; reconciliation
# markers and empty review output never spend an untouched allowance.
_EXEMPT_DECISIONS = frozenset(
    {None, 'APPROVE', 'reconciliation_blocked', 'execution_retryable'})
_DOSSIER_HASH = re.compile(r'[0-9a-f]{64}')


class OpportunityStateError(RuntimeError):
    """Opportunity state is unavailable, incoherent, or unsupported."""


class HistoricalDossierHashMissing(OpportunityStateError):
    """Read-only diagnostics only; never a usable/permission-bearing index."""

    def __init__(self, snapshot: LedgerSnapshot, sequences: tuple[int, ...],
                 *, gaps: tuple[dict, ...] = (),
                 sources: tuple[dict, ...] = (), state: dict | None = None):
        super().__init__('opportunity_policy_state_unavailable')
        self.snapshot = snapshot
        self.sequences = sequences
        self.gaps = gaps
        self.sources = sources
        self.state = state


def _canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      ensure_ascii=True, allow_nan=False).encode('ascii')


def allowance_identifier(event_id: str, generation: int) -> str:
    """Canonical allowance ID: resolver version, event ID and generation."""
    if not isinstance(event_id, str) or not event_id or type(generation) is not int or generation < 0:
        raise ValueError('invalid_allowance_identifier_input')
    return 'oa1:' + sha256(
        _canonical({'version': 1, 'event_id': event_id, 'generation': generation})).hexdigest()


@dataclass(frozen=True)
class PolicyDecision:
    outcome: str
    reason: str
    event_id: str | None
    allowance_id: str | None

    _OUTCOMES = frozenset({'eligible', 'skip', 'unknown', 'reopening_pending'})

    def __post_init__(self):
        if self.outcome not in self._OUTCOMES:
            raise ValueError('invalid_policy_outcome')


@dataclass(frozen=True)
class ConditionObservation:
    event_id: str
    metric: str
    value: Decimal
    units: str
    source_kind: str
    observed_at: dt.datetime
    evidence_ref: str
    seal: object

    def __post_init__(self):
        # The brief's shared state contract types `value: Decimal`; persisted
        # rows carrying non-numeric values fail closed here, at validation.
        if not isinstance(self.value, Decimal):
            raise ValueError('condition_observation_value_not_decimal')


@dataclass(frozen=True)
class ReopeningClaim:
    condition_id: str
    prior_allowance_id: str
    observation: ConditionObservation
    seal: object


@dataclass(frozen=True)
class _ObservationSeal:
    """Module-private seal binding an observation to its exact field lineage."""
    digest: str


@dataclass(frozen=True)
class _ClaimSeal:
    """Module-private seal binding a reopening claim to sealed observation lineage."""
    digest: str


def observation_digest(observation) -> str:
    if not isinstance(observation, ConditionObservation):
        raise ValueError('condition_observation_required')
    return sha256(_canonical({
        'version': 1, 'kind': 'condition_observation',
        'event_id': observation.event_id, 'metric': observation.metric,
        'value': str(observation.value), 'units': observation.units,
        'source_kind': observation.source_kind,
        'observed_at': observation.observed_at.isoformat(),
        'evidence_ref': observation.evidence_ref})).hexdigest()


def seal_observation(observation) -> ConditionObservation:
    """Trusted server-side sealing; the unsealed input keeps its exact fields."""
    if not isinstance(observation, ConditionObservation) or observation.seal is not None:
        raise ValueError('unsealed_observation_input_required')
    return ConditionObservation(
        observation.event_id, observation.metric, observation.value,
        observation.units, observation.source_kind, observation.observed_at,
        observation.evidence_ref, _ObservationSeal(observation_digest(observation)))


def observation_sealed(observation) -> bool:
    return (isinstance(observation, ConditionObservation)
            and isinstance(observation.seal, _ObservationSeal)
            and observation.seal.digest == observation_digest(observation))


def claim_digest(claim) -> str:
    if not isinstance(claim, ReopeningClaim) or not observation_sealed(claim.observation):
        raise ValueError('sealed_observation_required')
    return sha256(_canonical({
        'version': 1, 'kind': 'reopening_claim',
        'condition_id': claim.condition_id,
        'prior_allowance_id': claim.prior_allowance_id,
        'observation': observation_digest(claim.observation)})).hexdigest()


def seal_claim(claim) -> ReopeningClaim:
    if not isinstance(claim, ReopeningClaim) or claim.seal is not None:
        raise ValueError('unsealed_claim_input_required')
    return ReopeningClaim(claim.condition_id, claim.prior_allowance_id,
                          claim.observation, _ClaimSeal(claim_digest(claim)))


def claim_sealed(claim) -> bool:
    return (isinstance(claim, ReopeningClaim)
            and isinstance(claim.seal, _ClaimSeal)
            and claim.seal.digest == claim_digest(claim)
            and observation_sealed(claim.observation))


def condition_consumed(index: OpportunityIndex, condition_id: str) -> bool:
    """A condition is consumed once any durable grant record references it."""
    if not isinstance(condition_id, str):
        raise ValueError('condition_id_required')
    return any(grant.get('condition_id') == condition_id
               for grant in index.grants.values())


@dataclass(frozen=True)
class _AttemptSeal:
    """Module-private seal binding an authorization to exact index state."""
    digest: str


@dataclass(frozen=True)
class AttemptAuthorization:
    dossier_hash: str
    proposal_hash: str
    evidence_id: str
    allowance_id: str
    seal: object


def _completed_decisions(row: dict) -> list[dict]:
    reviews = row.get('reviews')
    if not isinstance(reviews, list):
        return []
    return [r for r in reviews if isinstance(r, dict) and r.get('decision') is not None]


def _legacy_completed_outputs(row: dict) -> list[dict]:
    """Retained pre-decision reviewer outputs; never approval authority.

    Legacy BUY/HOLD proposals are completed paid reviews, not empty output.
    Explicit marker decisions always win over the legacy action vocabulary.
    """
    reviews = row.get('reviews')
    if not isinstance(reviews, list):
        return []
    return [r for r in reviews if isinstance(r, dict) and 'decision' not in r
            and r.get('action') in ('BUY', 'HOLD')]


def _completed_dissent(row: dict) -> bool:
    # Unnormalized legacy completion never proves consensus approval/retry.
    return bool(_legacy_completed_outputs(row)) or any(
        r.get('decision') not in _EXEMPT_DECISIONS or bool(r.get('fatal_flags'))
        for r in _completed_decisions(row))


def _spends(row: dict) -> bool:
    """Completed modern/legacy review; empty/marker output never spends."""
    return bool(_legacy_completed_outputs(row)) or any(
        r.get('decision') not in ('reconciliation_blocked', 'execution_retryable')
        for r in _completed_decisions(row))


def _dual_approval_row(row: dict) -> bool:
    decisions = row.get('reviews')
    return (isinstance(decisions, list) and len(decisions) == 2
            and all(isinstance(r, dict) and r.get('decision') == 'APPROVE'
                    and not bool(r.get('fatal_flags')) for r in decisions))


def _valid_timestamp(value) -> bool:
    if not isinstance(value, str):
        return False
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except ValueError:
        return False
    return stamp.utcoffset() == dt.timedelta(0)


@dataclass(frozen=True)
class OpportunityIndex:
    """Validated opportunity state built once from one coherent snapshot.

    Internal maps are derived state, never caller input; the snapshot root,
    watermarks and record validation bind the whole index to one coherent
    read-only view of canonical history.
    """
    snapshot: LedgerSnapshot
    activated_version: int
    resolutions: dict[str, EventResolution]
    document_aliases: dict[str, str]
    dossier_allowances: dict[str, str]
    allowance_reviews: dict[str, tuple[dict, ...]]
    grants: dict[str, dict]
    conditions: dict[str, dict]
    unresolved_dossiers: frozenset[str]
    allowance_events: dict[str, str] = field(default_factory=dict, repr=False)
    state_digest: str = ''
    unresolved_issuer_scopes: dict[str, dict[str, str]] = field(default_factory=dict)
    missing_history_gaps: tuple[dict, ...] = ()
    unknown_history_blocks: dict[str, tuple[dict, ...]] = field(default_factory=dict)

    def __post_init__(self):
        object.__setattr__(self, 'unresolved_issuer_scopes', MappingProxyType({
            key: MappingProxyType(dict(scope))
            for key, scope in self.unresolved_issuer_scopes.items()}))


def _source_row(source, snapshot_rows: dict) -> dict:
    """Exact existing manifest source boundary (UTF-8 canonical row digest)."""
    if (not isinstance(source, dict)
            or set(source) != {'stream', 'sequence', 'row_sha256'}
            or not isinstance(source['stream'], str)
            or source['stream'] not in INDEX_STREAMS
            or type(source['sequence']) is not int or source['sequence'] < 1
            or not isinstance(source['row_sha256'], str)
            or _DOSSIER_HASH.fullmatch(source['row_sha256']) is None):
        raise OpportunityStateError('invalid_manifest_source_reference')
    rows = snapshot_rows.get(source['stream'], ())
    if source['sequence'] > len(rows):
        raise OpportunityStateError('manifest_source_sequence_out_of_range')
    row = rows[source['sequence'] - 1]
    digest = sha256(json.dumps(row, sort_keys=True, separators=(',', ':'),
                              ensure_ascii=False, allow_nan=False).encode('utf-8')).hexdigest()
    if digest != source['row_sha256']:
        raise OpportunityStateError('manifest_source_digest_mismatch')
    return row


def _row_digest(row) -> str:
    """Canonical UTF-8 row digest recomputed on every call (never cached)."""
    return sha256(json.dumps(row, sort_keys=True, separators=(',', ':'),
                             ensure_ascii=False, allow_nan=False)
                  .encode('utf-8')).hexdigest()


def _gap_source_row(source, snapshot_rows: dict) -> dict:
    """Exact migration gap-source boundary (dedicated allowlist, not _source_row).

    Same digest/sequence discipline as _source_row, but only the
    MIGRATION_SOURCE_STREAMS are accepted; binding sources stay unchanged.
    """
    if (not isinstance(source, dict)
            or set(source) != {'stream', 'sequence', 'row_sha256'}
            or not isinstance(source['stream'], str)
            or source['stream'] not in MIGRATION_SOURCE_STREAMS
            or type(source['sequence']) is not int or source['sequence'] < 1
            or not isinstance(source['row_sha256'], str)
            or _DOSSIER_HASH.fullmatch(source['row_sha256']) is None):
        raise OpportunityStateError('invalid_manifest_source_reference')
    rows = snapshot_rows.get(source['stream'], ())
    if source['sequence'] > len(rows):
        raise OpportunityStateError('manifest_source_sequence_out_of_range')
    row = rows[source['sequence'] - 1]
    if _row_digest(row) != source['row_sha256']:
        raise OpportunityStateError('manifest_source_digest_mismatch')
    return row


def extract_row_symbol(row) -> str | None:
    """First `symbol`-keyed value at any depth of the row's own JSON bytes."""
    if not isinstance(row, dict):
        return None
    stack = [row]
    while stack:
        current = stack.pop(0)
        if isinstance(current, dict):
            for key, value in current.items():
                if key == 'symbol' and isinstance(value, str):
                    return value
                stack.append(value)
        elif isinstance(current, list):
            stack.extend(current)
    return None


_GAP_KEYS = {'record_type', 'schema_version', 'timestamp', 'kind', 'reason',
             'source', 'observed_fields', 'issuer_evidence', 'hint'}


def _validate_gap_record(row: dict, snapshot_rows: dict) -> dict:
    """Full §3.1 gap validation against the referenced row's own canonical bytes."""
    if (not isinstance(row, dict) or set(row) != _GAP_KEYS
            or row.get('kind') not in MISSING_HISTORY_KINDS
            or row.get('reason') not in MISSING_HISTORY_REASONS
            or not isinstance(row.get('observed_fields'), list)
            or not all(isinstance(name, str) for name in row['observed_fields'])):
        raise OpportunityStateError('invalid_missing_history_record')
    referenced = _gap_source_row(row['source'], snapshot_rows)
    if sorted(row['observed_fields']) != sorted(referenced):
        raise OpportunityStateError('missing_history_observed_fields_mismatch')
    evidence = row.get('issuer_evidence')
    symbol = extract_row_symbol(referenced)
    if evidence is not None:
        if (not isinstance(evidence, dict) or set(evidence) != {'symbol'}
                or not isinstance(evidence['symbol'], str)
                or evidence['symbol'] != symbol):
            raise OpportunityStateError(
                'missing_history_symbol_evidence_unsubstantiated')
    hint = row.get('hint')
    if hint is not None and (not isinstance(hint, dict)
                             or set(hint) != {'legacy_proposal_hash'}
                             or not isinstance(hint['legacy_proposal_hash'], str)
                             or _DOSSIER_HASH.fullmatch(
                                 hint['legacy_proposal_hash']) is None):
        raise OpportunityStateError('invalid_missing_history_record')
    return {'source': dict(row['source']), 'kind': row['kind'],
            'symbol_evidence': evidence['symbol'] if evidence is not None else None,
            'hint': None if hint is None else dict(hint)}


def _unresolved_record(row: dict, resolutions: dict, unresolved: set,
                       scopes: dict, snapshot_rows: dict) -> None:
    """Validate explicit reviewed scope; never infer an issuer from a source."""
    record = row.get('unresolved')
    keys = {'dossier_hash', 'status', 'reason'}
    if (not isinstance(record, dict) or set(record) not in (keys, keys | {'issuer_scope'})
            or not isinstance(record.get('dossier_hash'), str)
            or _DOSSIER_HASH.fullmatch(record['dossier_hash']) is None
            or record.get('status') not in ('unknown', 'conflict')
            or not isinstance(record.get('reason'), str)):
        raise OpportunityStateError('invalid_unresolved_record')
    dossier = record['dossier_hash']
    if 'issuer_scope' in record:
        scope = record['issuer_scope']
        if (set(row) != {'record_type', 'schema_version', 'timestamp', 'unresolved', 'source'}
                or dossier not in unresolved
                or not isinstance(scope, dict)
                or set(scope) != {'binding_event_id', 'issuer_cik'}
                or not all(isinstance(value, str) for value in scope.values())):
            raise OpportunityStateError('invalid_unresolved_issuer_scope')
        binding = resolutions.get(scope['binding_event_id'])
        if (binding is None or binding.issuer is None
                or binding.issuer.cik != scope['issuer_cik']):
            raise OpportunityStateError('unresolved_scope_binding_mismatch')
        source = _source_row(row.get('source'), snapshot_rows)
        source_dossier = source.get('dossier_hash')
        if source.get('record_type') == 'identity_resolution' and isinstance(source.get('unresolved'), dict):
            source_dossier = source['unresolved'].get('dossier_hash')
        if source_dossier != dossier:
            raise OpportunityStateError('unresolved_scope_source_mismatch')
        if dossier in scopes and scopes[dossier] != scope:
            raise OpportunityStateError('unresolved_scope_conflict')
        scopes[dossier] = dict(scope)
    elif dossier in scopes:
        raise OpportunityStateError('unresolved_scope_erasure')
    unresolved.add(dossier)


def incomplete_history(index: OpportunityIndex) -> frozenset[str]:
    """Unscoped/unrepresented historical reviews cannot imply a clean install.

    Hashless gap rows carry no dossier hash; they are represented by
    missing_history_gaps and never enter the reviewed-dossier set.
    """
    reviewed = {row['dossier_hash'] for row in index.snapshot.rows.get(REVIEWS_STREAM, ())
                if isinstance(row, dict) and isinstance(row.get('dossier_hash'), str)}
    return frozenset((index.unresolved_dossiers | (reviewed - index.dossier_allowances.keys()))
                     - index.unresolved_issuer_scopes.keys())


def _policy_state(rows: tuple[dict, ...], resolutions: dict, aliases: dict,
                  grants: dict, conditions: dict, unresolved: set,
                  allowance_events: dict, scopes: dict, snapshot_rows: dict) -> int:
    version = 0
    for row in rows:
        if not isinstance(row, dict) or row.get('record_type') not in _KNOWN_RECORD_TYPES \
                or type(row.get('schema_version')) is not int or row['schema_version'] != 1 \
                or not _valid_timestamp(row.get('timestamp')):
            raise OpportunityStateError('opportunity_policy_state_unavailable')
        kind = row['record_type']
        if kind == 'activation':
            if type(row.get('policy_version')) is not int or row['policy_version'] <= 0:
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            version = max(version, row['policy_version'])
        elif kind == 'identity_resolution':
            if 'resolution' in row and 'unresolved' in row:
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            if 'resolution' in row:
                try:
                    resolution = _load_binding(row['resolution'])
                except (ValueError, TypeError, KeyError) as error:
                    raise OpportunityStateError('opportunity_policy_state_unavailable') from error
                resolutions[resolution.event_id] = resolution
                allowance_events.setdefault(
                    allowance_identifier(resolution.event_id, 0), resolution.event_id)
            elif 'unresolved' in row:
                _unresolved_record(row, resolutions, unresolved, scopes, snapshot_rows)
            else:
                raise OpportunityStateError('opportunity_policy_state_unavailable')
        elif kind == 'document_alias':
            alias, event_id = row.get('alias'), row.get('event_id')
            if not isinstance(alias, str) or not alias or not isinstance(event_id, str):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            aliases[alias] = event_id
        elif kind == 'reopen_grant':
            event_id = row.get('event_id')
            generation = row.get('generation')
            if not isinstance(event_id, str) or type(generation) is not int or generation < 1:
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            if (row.get('prior_allowance_id') != allowance_identifier(event_id, generation - 1)
                    or row.get('allowance_id') != allowance_identifier(event_id, generation)
                    or allowance_events.get(row.get('prior_allowance_id')) != event_id):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            grants[row['allowance_id']] = row
            allowance_events[row['allowance_id']] = event_id
        elif kind == 'condition_approval':
            condition_id = row.get('condition_id')
            if (not isinstance(condition_id, str) or not condition_id
                    or not isinstance(row.get('event_id'), str)
                    or not isinstance(row.get('condition'), dict)):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            conditions[condition_id] = row
        elif kind == 'missing_history':
            # Row-structure validation only here; source/field validation
            # against the referenced canonical row is the gap-source validator.
            if (row.get('kind') not in MISSING_HISTORY_KINDS
                    or row.get('reason') not in MISSING_HISTORY_REASONS):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
        elif kind == 'missing_history_clearance':
            # Envelope validation only; the exact per-gap source check against
            # the referenced row's own bytes runs in the state build.
            if (row.get('clearance_reason') not in CLEARANCE_REASONS
                    or not isinstance(row.get('gap_source'), dict)):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
    return version


def _candidate_links(rows: tuple[dict, ...], allowance_events: dict,
                     dossier_allowances: dict) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        keys = {'event_id', 'allowance_id'}
        if not keys & set(row):
            continue  # Legacy dossier hashes alone are not policy links.
        dossier = row.get('dossier_hash')
        event_id = row.get('event_id')
        allowance = row.get('allowance_id')
        if (not isinstance(dossier, str) or _DOSSIER_HASH.fullmatch(dossier) is None
                or not isinstance(event_id, str) or not isinstance(allowance, str)
                or allowance_events.get(allowance) != event_id):
            raise OpportunityStateError('opportunity_policy_state_unavailable')
        # A hash has one immutable generation; replay may never relocate reviews.
        if (dossier in dossier_allowances
                and dossier_allowances[dossier] != allowance):
            raise OpportunityStateError('opportunity_policy_state_unavailable')
        dossier_allowances[dossier] = allowance


def _gap_entry(snapshot_rows: dict, stream: str, sequence: int, record: dict) -> dict:
    return {'stream': stream, 'sequence': sequence,
            'row_sha256': _row_digest(snapshot_rows[stream][sequence - 1]),
            'kind': record['kind'],
            'symbol_evidence': record['symbol_evidence']}


def _state_parts(snapshot: LedgerSnapshot) -> dict:
    """Compute the full validated state; blockers/tolerance are reported, not raised.

    Fail-closed ordering (I-2): every `missing_history` policy record is
    validated against the referenced row's own canonical bytes BEFORE any
    raise, then hashless gap rows are classified. Referenced gaps are
    tolerated into `gaps`; unreferenced ones become typed blockers. Tolerance
    never creates a dossier→allowance entry, allowance review, or permission.
    """
    try:
        resolutions: dict[str, EventResolution] = {}
        aliases: dict[str, str] = {}
        grants: dict[str, dict] = {}
        conditions: dict[str, dict] = {}
        unresolved: set[str] = set()
        scopes: dict[str, dict[str, str]] = {}
        allowance_events: dict[str, str] = {}
        version = _policy_state(snapshot.rows.get(POLICY_STREAM, ()), resolutions,
                                aliases, grants, conditions, unresolved, allowance_events,
                                scopes, snapshot.rows)
        # A later binding row cannot silently change a previously scoped issuer.
        for scope in scopes.values():
            if resolutions[scope['binding_event_id']].issuer.cik != scope['issuer_cik']:
                raise OpportunityStateError('opportunity_policy_state_unavailable')
        dossier_allowances: dict[str, str] = {}
        # Reviewed historical source references bind to the original allowance,
        # never the current (possibly reopened) generation. Validate exact rows
        # on every load so imported history cannot be detached or repointed.
        for row in snapshot.rows.get(POLICY_STREAM, ()):
            if (row.get('record_type') == 'identity_resolution'
                    and 'resolution' in row and 'source' in row):
                source = _source_row(row['source'], snapshot.rows)
                if 'dossier_hash' not in source:
                    continue  # Identity provenance alone grants no dossier permission.
                event_id = _load_binding(row['resolution']).event_id
                if not isinstance(event_id, str):
                    raise OpportunityStateError('opportunity_policy_state_unavailable')
                _candidate_links(({'dossier_hash': source.get('dossier_hash'),
                                   'event_id': event_id,
                                   'allowance_id': allowance_identifier(event_id, 0)},),
                                 allowance_events, dossier_allowances)
        _candidate_links(snapshot.rows.get(CANDIDATES_STREAM, ()), allowance_events,
                         dossier_allowances)
        for dossier, scope in scopes.items():
            allowance = dossier_allowances.get(dossier)
            if allowance is not None and resolutions[allowance_events[allowance]].issuer.cik != scope['issuer_cik']:
                raise OpportunityStateError('unresolved_scope_binding_mismatch')
        # Gap validation precedes any raise (no partial index escape hatch).
        gap_records: dict[tuple[str, int], dict] = {}
        for row in snapshot.rows.get(POLICY_STREAM, ()):
            if isinstance(row, dict) and row.get('record_type') == 'missing_history':
                validated = _validate_gap_record(row, snapshot.rows)
                key = (validated['source']['stream'], validated['source']['sequence'])
                prior = gap_records.get(key)
                if prior is not None and prior != validated:
                    raise OpportunityStateError('missing_history_conflict')
                gap_records[key] = validated
        gaps: list[dict] = []
        blockers: list[dict] = []
        allowance_reviews: dict[str, tuple[dict, ...]] = {}
        missing_dossier_sequences = []
        matched: set[tuple[str, int]] = set()
        for sequence, row in enumerate(snapshot.rows.get(REVIEWS_STREAM, ()), 1):
            if not isinstance(row, dict) or not isinstance(row.get('evidence_id'), str):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            if 'dossier_hash' not in row:
                key = (REVIEWS_STREAM, sequence)
                record = gap_records.get(key)
                if record is not None:
                    gaps.append(_gap_entry(snapshot.rows, REVIEWS_STREAM,
                                           sequence, record))
                    matched.add(key)
                else:
                    missing_dossier_sequences.append(sequence)
                    blockers.append({'stream': REVIEWS_STREAM, 'sequence': sequence,
                                     'row_sha256': _row_digest(row)})
                continue  # Retained as a typed whole-index blocker below, never ignored.
            dossier = row.get('dossier_hash')
            if not isinstance(dossier, str):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            if dossier not in dossier_allowances:
                continue  # Unbound historical dossiers fail closed at decision time.
            allowance_reviews.setdefault(dossier_allowances[dossier], ())
            allowance_reviews[dossier_allowances[dossier]] += (row,)
        # Only hashless filled BUY trade rows are gap-classified; hashless
        # filled SELL rows are explicit non-blockers, asserted by test (I-2).
        for sequence, row in enumerate(snapshot.rows.get(TRADE_JOURNAL_STREAM, ()), 1):
            if (isinstance(row, dict) and 'dossier_hash' not in row
                    and row.get('action') == 'BUY' and row.get('status') == 'filled'):
                key = (TRADE_JOURNAL_STREAM, sequence)
                record = gap_records.get(key)
                if record is not None:
                    gaps.append(_gap_entry(snapshot.rows, TRADE_JOURNAL_STREAM,
                                           sequence, record))
                    matched.add(key)
                else:
                    blockers.append({'stream': TRADE_JOURNAL_STREAM,
                                     'sequence': sequence,
                                     'row_sha256': _row_digest(row)})
        unmatched = [key for key in gap_records if key not in matched]
        if unmatched:
            raise OpportunityStateError('missing_history_not_gap_row')
        # Per-gap clearance: a symbol unblocks only when every gap naming it
        # is individually cleared; the underlying records are kept forever.
        cleared: set[tuple[str, int]] = set()
        for row in snapshot.rows.get(POLICY_STREAM, ()):
            if not (isinstance(row, dict)
                    and row.get('record_type') == 'missing_history_clearance'):
                continue
            if set(row) != CLEARANCE_KEYS:
                raise OpportunityStateError('invalid_missing_history_clearance')
            source = row['gap_source']
            _gap_source_row(source, snapshot.rows)
            key = (source['stream'], source['sequence'])
            if key not in matched:
                raise OpportunityStateError('missing_history_clearance_unknown_gap')
            cleared.add(key)
        # Conservative per-symbol blocking, derived only from validated
        # issuer_evidence taken from the referenced row's own bytes. Exact
        # match after casefold() + trim; never an alias or suffix match.
        blocks: dict[str, tuple[dict, ...]] = {}
        for gap in gaps:
            if gap['symbol_evidence'] is None:
                continue
            if (gap['stream'], gap['sequence']) in cleared:
                continue
            key = gap['symbol_evidence'].strip().casefold()
            blocks[key] = blocks.get(key, ()) + (gap,)
        return {'version': version, 'resolutions': resolutions, 'aliases': aliases,
                'grants': grants, 'conditions': conditions, 'unresolved': unresolved,
                'scopes': scopes, 'allowance_events': allowance_events,
                'dossier_allowances': dossier_allowances,
                'allowance_reviews': allowance_reviews,
                'missing_dossier_sequences': tuple(missing_dossier_sequences),
                'gaps': tuple(gaps), 'blockers': tuple(blockers),
                'blocks': blocks}
    except (LedgerError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, OpportunityStateError):
            raise
        raise OpportunityStateError('opportunity_policy_state_unavailable') from error


def _index_from_parts(snapshot: LedgerSnapshot, parts: dict) -> OpportunityIndex:
    digest = sha256(_canonical({
        'version': 1,
        'activated_version': parts['version'],
        'resolutions': sorted(parts['resolutions']),
        'document_aliases': sorted(parts['aliases'].items()),
        'conditions': [[key, _canonical(row).decode('ascii')]
                       for key, row in sorted(parts['conditions'].items())],
        'unresolved_dossiers': sorted(parts['unresolved']),
        'unresolved_issuer_scopes': sorted(parts['scopes'].items()),
        'grants': sorted(parts['grants']),
        'dossier_allowances': sorted(parts['dossier_allowances'].items()),
        'allowance_reviews': [[_canonical(r).decode('ascii') for r in rows]
                              for _, rows in sorted(parts['allowance_reviews'].items())],
        'watermark': list(snapshot.watermark),
    })).hexdigest()
    return OpportunityIndex(snapshot, parts['version'], parts['resolutions'],
                            parts['aliases'], parts['dossier_allowances'],
                            parts['allowance_reviews'], parts['grants'],
                            parts['conditions'], frozenset(parts['unresolved']),
                            parts['allowance_events'], digest, parts['scopes'],
                            parts['gaps'], parts['blocks'])


def _build(snapshot: LedgerSnapshot) -> OpportunityIndex:
    parts = _state_parts(snapshot)
    if parts['blockers']:
        raise HistoricalDossierHashMissing(
            snapshot, parts['missing_dossier_sequences'], gaps=parts['gaps'],
            sources=parts['blockers'], state=parts)
    return _index_from_parts(snapshot, parts)


def load_index(root: Path) -> OpportunityIndex:
    """Build the validated index from one coherent read-only snapshot.

    The migration-validation read is the single coherent widened read
    (MIGRATION_SNAPSHOT_STREAMS); trade_journal rows are digest-checked for
    gap references only and never consumed by decision code.
    """
    try:
        snapshot = read_stream_snapshot_readonly(Path(root), MIGRATION_SNAPSHOT_STREAMS)
    except (LedgerError, OSError) as error:
        raise OpportunityStateError('opportunity_policy_state_unavailable') from error
    return _build(snapshot)


def _reload_if_changed(index: OpportunityIndex) -> OpportunityIndex:
    """Rebuild from one fresh coherent snapshot before every safety decision.

    Loading is strictly read-only, so reloading unconditionally is safe and
    guarantees a durable review appended after the index was built still
    spends its allowance (crash between review append and index rebuild).
    """
    try:
        fresh = load_index(index.snapshot.root)
    except OpportunityStateError:
        raise
    return fresh


def _current_allowance(index: OpportunityIndex, event_id: str) -> str:
    generation = 0
    for allowance, grant in index.grants.items():
        if grant.get('event_id') == event_id:
            generation = max(generation, grant['generation'])
    return allowance_identifier(event_id, generation)


def _validate_current_attempt(index: OpportunityIndex, *, dossier_hash: str,
                              proposal_hash: str, evidence_id: str) -> str:
    if index.activated_version <= 0:
        raise OpportunityStateError('opportunity_policy_not_activated')
    allowance = index.dossier_allowances.get(dossier_hash)
    if allowance is None or index.allowance_events.get(allowance) is None:
        raise OpportunityStateError('current_attempt_not_authorized')
    rows = index.allowance_reviews.get(allowance, ())
    approvals = [r for r in rows if r.get('evidence_id') == evidence_id
                 and _dual_approval_row(r)]
    if (len(approvals) != 1 or approvals[0].get('proposal_hash') != proposal_hash
            or allowance != _current_allowance(index, index.allowance_events[allowance])):
        raise OpportunityStateError('current_attempt_not_authorized')
    return allowance


def authorize_current_attempt(index: OpportunityIndex, *, dossier_hash: str,
                              proposal_hash: str, evidence_id: str) -> AttemptAuthorization:
    """Validate the exact persisted dual approval and current grant.

    No caller-provided approval boolean participates; everything is proven
    against the coherent index. Any mismatch is a typed failure.
    """
    if not isinstance(dossier_hash, str) or not isinstance(proposal_hash, str) \
            or not isinstance(evidence_id, str) or not dossier_hash \
            or not proposal_hash or not evidence_id:
        raise OpportunityStateError('current_attempt_not_authorized')
    allowance = _validate_current_attempt(
        index, dossier_hash=dossier_hash, proposal_hash=proposal_hash,
        evidence_id=evidence_id)
    digest = sha256(_canonical({
        'dossier_hash': dossier_hash, 'proposal_hash': proposal_hash,
        'evidence_id': evidence_id, 'allowance_id': allowance,
        'state_digest': index.state_digest})).hexdigest()
    return AttemptAuthorization(dossier_hash, proposal_hash, evidence_id,
                                allowance, _AttemptSeal(digest))


def _attempt_authorized(index: OpportunityIndex, attempt: object,
                        dossier_hash: str | None) -> bool:
    if not isinstance(attempt, AttemptAuthorization) \
            or not isinstance(attempt.seal, _AttemptSeal):
        return False
    if dossier_hash is not None and attempt.dossier_hash != dossier_hash:
        return False
    try:
        allowance = _validate_current_attempt(
            index, dossier_hash=attempt.dossier_hash,
            proposal_hash=attempt.proposal_hash, evidence_id=attempt.evidence_id)
    except OpportunityStateError:
        return False
    if allowance != attempt.allowance_id:
        return False
    digest = sha256(_canonical({
        'dossier_hash': attempt.dossier_hash,
        'proposal_hash': attempt.proposal_hash,
        'evidence_id': attempt.evidence_id, 'allowance_id': allowance,
        'state_digest': index.state_digest})).hexdigest()
    return attempt.seal.digest == digest


def _reopening_pending(index: OpportunityIndex, claim: object) -> bool:
    """Only a sealed claim bound to the spent prior allowance may advance research."""
    if not isinstance(claim, ReopeningClaim) or not claim_sealed(claim):
        return False
    return claim.prior_allowance_id in index.allowance_events


def _baseline_exclusions(root: Path) -> frozenset[str]:
    """Strictly read the broker baseline; it is a required durable file.

    Missing or malformed baseline state fails closed: a missing local record
    is never broker authorization that a symbol is flat.
    """
    path = Path(root) / 'private' / 'broker_baseline.json'
    if not path.exists():
        raise OpportunityStateError('broker_baseline_missing')
    try:
        value = json.loads(path.read_text(encoding='utf-8'))
        symbols = value.get('preexisting_symbols')
        if not isinstance(symbols, list):
            raise OpportunityStateError('broker_baseline_invalid')
        if any(not isinstance(symbol, str)
               or re.fullmatch(r'[A-Za-z][A-Za-z0-9.-]{0,9}', symbol) is None
               for symbol in symbols):
            raise OpportunityStateError('broker_baseline_invalid')
        return frozenset(symbol.upper() for symbol in symbols)
    except (OSError, ValueError, AttributeError) as error:
        raise OpportunityStateError('broker_baseline_invalid') from error


def local_entry_exclusions(index: OpportunityIndex) -> frozenset[str]:
    """Symbols locally excluded from new-entry consideration.

    Only the validated durable baseline supplies local symbol exclusions.
    Completed reviews spend event allowances, not ticker-wide permission.
    This index has no authoritative current remaining-share/order accounting.
    Absence from this set is not broker authorization; execution still proves
    broker truth before intent.
    """
    if not isinstance(index, OpportunityIndex):
        raise OpportunityStateError('opportunity_policy_state_unavailable')
    return _baseline_exclusions(index.snapshot.root)


def require_current_allowance(root: Path, candidate: dict, *,
                              attempt: AttemptAuthorization | None = None) -> PolicyDecision:
    """Reload authoritative state at a safety boundary and decide entry authority.

    The exact current-attempt exception is preserved: a sealed authorization
    matching the coherent index returns eligible even when the caller's view
    is stale. Without an attempt, only an unspent eligible allowance or a
    verified provisional reopening claim (durable, sealed, condition-backed)
    may pass; unknown, skip and absent bindings never authorize entry.
    Absent activation keeps the legacy compatibility floor with no new-entry
    denial; once activated, malformed or incompatible state fails closed.
    """
    root = Path(root)
    try:
        version = activation_version(root)
    except ActivationStateError as error:
        raise OpportunityStateError('opportunity_policy_state_unavailable') from error
    if version <= 0:
        return PolicyDecision('eligible', 'legacy_policy_floor', None, None)
    if version > 1:
        raise OpportunityStateError('opportunity_policy_version_unsupported')
    index = load_index(root)
    if not isinstance(candidate, dict):
        raise OpportunityStateError('opportunity_identity_unknown')
    try:
        resolution = _load_binding(candidate.get('opportunity_identity'))
    except (ValueError, TypeError, KeyError) as error:
        raise OpportunityStateError('opportunity_identity_unknown') from error
    dossier = candidate.get('dossier_hash')
    valid_dossier = (isinstance(dossier, str)
                     and _DOSSIER_HASH.fullmatch(dossier) is not None)
    claim = None
    if attempt is None and isinstance(dossier, str) and valid_dossier:
        # A claim is restored only from durable server-created rows; absence
        # of a claim is never authorization and never an entry permission.
        from opportunity_admin import restore_reopening_claim, OpportunityAdminError
        try:
            claim = restore_reopening_claim(
                index, dossier, now=dt.datetime.now(dt.timezone.utc))
        except (OpportunityAdminError, OpportunityStateError, ValueError,
                TypeError, KeyError):
            claim = None
    return event_decision(index, resolution,
                          dossier_hash=dossier if valid_dossier else None,
                          current_attempt=attempt, reopening_claim=claim)


def event_decision(index: OpportunityIndex, resolution: EventResolution, *,
                   dossier_hash: str | None = None,
                   current_attempt: AttemptAuthorization | None = None,
                   reopening_claim: ReopeningClaim | None = None) -> PolicyDecision:
    """Fail-closed entry policy decision for one resolved event identity.

    The index is reloaded when the durable watermarks moved before any
    safety decision; unknown, corrupt, lagging or unbound state can never
    mean eligible. `reopening_pending` is research-only and provisional.
    """
    index = _reload_if_changed(index)
    if not isinstance(resolution, EventResolution):
        return PolicyDecision('unknown', 'opportunity_identity_unknown', None, None)
    if resolution.status == 'conflict':
        return PolicyDecision('unknown', 'opportunity_identity_conflict',
                              resolution.event_id, None)
    if resolution.status != 'verified' or resolution.event_id is None:
        return PolicyDecision('unknown', 'opportunity_identity_unknown',
                              resolution.event_id, None)
    event_id = resolution.event_id
    if not isinstance(index, OpportunityIndex) or index.activated_version <= 0:
        return PolicyDecision('unknown', 'policy_not_activated', event_id, None)
    if event_id not in index.resolutions:
        return PolicyDecision('unknown', 'event_binding_missing', event_id, None)
    if dossier_hash is not None:
        if not isinstance(dossier_hash, str) or _DOSSIER_HASH.fullmatch(dossier_hash) is None:
            return PolicyDecision('unknown', 'opportunity_identity_unknown', event_id, None)
        if dossier_hash in index.unresolved_dossiers:
            return PolicyDecision('unknown', 'historical_binding_missing', event_id, None)
    if current_attempt is not None:
        if _attempt_authorized(index, current_attempt, dossier_hash):
            return PolicyDecision('eligible', 'current_attempt_authorized',
                                  event_id, current_attempt.allowance_id)
        return PolicyDecision('skip', 'current_attempt_unauthorized', event_id,
                              getattr(current_attempt, 'allowance_id', None))
    # Dissent remains attached to its canonical generation. Only the durable
    # validated grant chain advances the allowance; old spending is audit
    # history, not a veto of the explicitly authorized next consideration.
    current = _current_allowance(index, event_id)
    spent = [r for r in index.allowance_reviews.get(current, ()) if _spends(r)]
    if spent:
        if _reopening_pending(index, reopening_claim):
            return PolicyDecision('reopening_pending', 'reopening_claim_pending',
                                  event_id, current)
        return PolicyDecision('skip', 'unchanged_opportunity', event_id, current)
    if dossier_hash is not None and index.dossier_allowances.get(dossier_hash) != current:
        return PolicyDecision('unknown', 'dossier_binding_missing', event_id, None)
    return PolicyDecision('eligible', 'allowance_available', event_id, current)


@dataclass(frozen=True)
class PolicyContext:
    """Root-bound read-only Radar context; no absence implies broker flatness."""
    root: Path
    index: OpportunityIndex
    known_exclusions: frozenset[str]

    def __post_init__(self):
        object.__setattr__(self, 'root', Path(self.root).resolve())
        object.__setattr__(self, 'known_exclusions', frozenset(self.known_exclusions))


def load_policy_context(root: Path) -> PolicyContext:
    root = Path(root).resolve()
    try:
        version = activation_version(root)
        if version > 1:
            raise OpportunityStateError('opportunity_policy_version_unsupported')
        index = load_index(root)
        if index.activated_version != version:
            raise OpportunityStateError('opportunity_policy_state_changed')
        exclusions = local_entry_exclusions(index) if version else frozenset()
        return PolicyContext(root, index, exclusions)
    except ActivationStateError as error:
        raise OpportunityStateError('opportunity_policy_state_unavailable') from error


def refresh_policy_context(context: PolicyContext) -> PolicyContext:
    if (not isinstance(context, PolicyContext)
            or Path(context.index.snapshot.root).resolve() != context.root):
        raise OpportunityStateError('opportunity_policy_root_mismatch')
    fresh = load_policy_context(context.root)
    if fresh.index.activated_version < context.index.activated_version:
        raise OpportunityStateError('opportunity_policy_state_regressed')
    return fresh


def candidate_policy(context: PolicyContext, resolution: EventResolution, *,
                     symbol: str, dossier_hash: str | None = None,
                     reopening_claim: ReopeningClaim | None = None) -> PolicyDecision:
    """Research gate, never entry authority. Positive baseline facts dominate.

    A newly acquired current-report cover can establish a prospective identity;
    historical/index bindings still belong to the read-only canonical index.
    Reopening claims must satisfy the approved condition, not merely be sealed.
    """
    context = refresh_policy_context(context)
    index = context.index
    if symbol in context.known_exclusions:
        return PolicyDecision('skip', 'position_already_held', None, None)
    if index.activated_version != 1:
        return PolicyDecision('unknown', 'policy_not_activated', None, None)
    if not isinstance(resolution, EventResolution) or resolution.status != 'verified':
        reason = ('opportunity_identity_conflict' if isinstance(resolution, EventResolution)
                  and resolution.status == 'conflict' else 'opportunity_identity_unknown')
        return PolicyDecision('unknown', reason, None, None)
    try:
        candidate_identity(resolution)
    except (ValueError, TypeError, KeyError):
        return PolicyDecision('unknown', 'opportunity_identity_unknown', None, None)
    if resolution.issuer.symbol != symbol:
        return PolicyDecision('unknown', 'opportunity_identity_conflict', None, None)
    known = index.resolutions.get(resolution.event_id)
    if known is not None and (known.issuer.symbol, known.issuer.cik, known.issuer.legal_name,
                              known.family, known.period) != (
            resolution.issuer.symbol, resolution.issuer.cik, resolution.issuer.legal_name,
            resolution.family, resolution.period):
        return PolicyDecision('unknown', 'opportunity_identity_conflict', resolution.event_id, None)
    # Conservative re-entry blocking: a verified issuer symbol with an
    # unresolved unknown-history gap is unknown until every gap naming it is
    # reconciled. Blocking never grants, spends, or qualifies retry.
    if index.unknown_history_blocks.get(resolution.issuer.symbol.strip().casefold()):
        return PolicyDecision('unknown', 'unknown_history_unreconciled',
                              resolution.event_id, None)
    if reopening_claim is not None:
        from opportunity_admin import _verify_claim_against_index, OpportunityAdminError
        try:
            if reopening_claim.observation.event_id != resolution.event_id:
                raise ValueError('claim_event_mismatch')
            _verify_claim_against_index(index, reopening_claim,
                                       now=dt.datetime.now(dt.timezone.utc))
        except (OpportunityAdminError, ValueError, AttributeError):
            return PolicyDecision('skip', 'unchanged_opportunity', resolution.event_id, None)
    if resolution.event_id not in index.resolutions:
        # No historic binding may be silently erased by a prospective capture.
        if incomplete_history(index):
            raise OpportunityStateError('opportunity_policy_state_unavailable')
        if (dossier_hash is not None
                or any(scope['issuer_cik'] == resolution.issuer.cik
                       for scope in index.unresolved_issuer_scopes.values())
                or resolution.reason != 'current_report_cover'):
            return PolicyDecision('unknown', 'opportunity_identity_unknown', resolution.event_id, None)
        return PolicyDecision('eligible', 'allowance_available', resolution.event_id,
                              allowance_identifier(resolution.event_id, 0))
    result = event_decision(index, resolution, dossier_hash=dossier_hash,
                            reopening_claim=reopening_claim)
    if result.reason in {'event_binding_missing', 'historical_binding_missing', 'dossier_binding_missing'}:
        return PolicyDecision('unknown', 'opportunity_identity_unknown', result.event_id, None)
    return result
