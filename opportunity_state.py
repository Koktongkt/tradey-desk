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

from opportunity_activation import _KNOWN_RECORD_TYPES
from opportunity_identity import EventResolution, _load_binding
from sqlite_ledger import (
    LedgerError,
    LedgerSnapshot,
    read_stream_snapshot_readonly,
)

POLICY_STREAM = 'private/opportunity_policy.jsonl'
REVIEWS_STREAM = 'private/reviews.jsonl'
CANDIDATES_STREAM = 'candidates.jsonl'
INDEX_STREAMS = (POLICY_STREAM, REVIEWS_STREAM, CANDIDATES_STREAM)

# Exact reuse of the candidate_retry completed-review vocabulary. A decision
# outside this set (or fatal flags) is a completed dissent; reconciliation
# markers and empty review output never spend an untouched allowance.
_EXEMPT_DECISIONS = frozenset(
    {None, 'APPROVE', 'reconciliation_blocked', 'execution_retryable'})
_DOSSIER_HASH = re.compile(r'[0-9a-f]{64}')


class OpportunityStateError(RuntimeError):
    """Opportunity state is unavailable, incoherent, or unsupported."""


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


def _completed_dissent(row: dict) -> bool:
    return any(r.get('decision') not in _EXEMPT_DECISIONS or bool(r.get('fatal_flags'))
               for r in _completed_decisions(row))


def _spends(row: dict) -> bool:
    """A completed review with real decisions; empty/marker output never spends."""
    return any(r.get('decision') not in ('reconciliation_blocked', 'execution_retryable')
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


def _policy_state(rows: tuple[dict, ...], resolutions: dict, aliases: dict,
                  grants: dict, conditions: dict, unresolved: set,
                  allowance_events: dict) -> int:
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
            if 'resolution' in row:
                try:
                    resolution = _load_binding(row['resolution'])
                except (ValueError, TypeError, KeyError) as error:
                    raise OpportunityStateError('opportunity_policy_state_unavailable') from error
                resolutions[resolution.event_id] = resolution
                allowance_events.setdefault(
                    allowance_identifier(resolution.event_id, 0), resolution.event_id)
            elif 'unresolved' in row:
                record = row['unresolved']
                if (not isinstance(record, dict)
                        or not isinstance(record.get('dossier_hash'), str)
                        or _DOSSIER_HASH.fullmatch(record['dossier_hash']) is None
                        or record.get('status') not in ('unknown', 'conflict')
                        or not isinstance(record.get('reason'), str)):
                    raise OpportunityStateError('opportunity_policy_state_unavailable')
                unresolved.add(record['dossier_hash'])
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
                    or row.get('allowance_id') != allowance_identifier(event_id, generation)):
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
    return version


def _candidate_links(rows: tuple[dict, ...], allowance_events: dict,
                     dossier_allowances: dict) -> None:
    for row in rows:
        if not isinstance(row, dict):
            continue
        keys = {'dossier_hash', 'event_id', 'allowance_id'}
        if not keys & set(row):
            continue  # Ordinary candidate rows carry no policy links yet.
        dossier = row.get('dossier_hash')
        event_id = row.get('event_id')
        allowance = row.get('allowance_id')
        if (not isinstance(dossier, str) or _DOSSIER_HASH.fullmatch(dossier) is None
                or not isinstance(event_id, str) or not isinstance(allowance, str)
                or allowance_events.get(allowance) != event_id):
            raise OpportunityStateError('opportunity_policy_state_unavailable')
        if (dossier in dossier_allowances
                and allowance_events.get(dossier_allowances[dossier]) != event_id):
            raise OpportunityStateError('opportunity_policy_state_unavailable')
        dossier_allowances[dossier] = allowance


def _build(snapshot: LedgerSnapshot) -> OpportunityIndex:
    try:
        resolutions: dict[str, EventResolution] = {}
        aliases: dict[str, str] = {}
        grants: dict[str, dict] = {}
        conditions: dict[str, dict] = {}
        unresolved: set[str] = set()
        allowance_events: dict[str, str] = {}
        version = _policy_state(snapshot.rows.get(POLICY_STREAM, ()), resolutions,
                                aliases, grants, conditions, unresolved, allowance_events)
        dossier_allowances: dict[str, str] = {}
        _candidate_links(snapshot.rows.get(CANDIDATES_STREAM, ()), allowance_events,
                         dossier_allowances)
        allowance_reviews: dict[str, tuple[dict, ...]] = {}
        for row in snapshot.rows.get(REVIEWS_STREAM, ()):
            if not isinstance(row, dict):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            dossier = row.get('dossier_hash')
            if not isinstance(dossier, str) or not isinstance(row.get('evidence_id'), str):
                raise OpportunityStateError('opportunity_policy_state_unavailable')
            if dossier not in dossier_allowances:
                continue  # Unbound historical dossiers fail closed at decision time.
            allowance_reviews.setdefault(dossier_allowances[dossier], ())
            allowance_reviews[dossier_allowances[dossier]] += (row,)
        digest = sha256(_canonical({
            'version': 1,
            'activated_version': version,
            'resolutions': sorted(resolutions),
            'document_aliases': sorted(aliases.items()),
            'conditions': [[key, _canonical(row).decode('ascii')]
                           for key, row in sorted(conditions.items())],
            'unresolved_dossiers': sorted(unresolved),
            'grants': sorted(grants),
            'dossier_allowances': sorted(dossier_allowances.items()),
            'allowance_reviews': [[_canonical(r).decode('ascii') for r in rows]
                                  for _, rows in sorted(allowance_reviews.items())],
            'watermark': list(snapshot.watermark),
        })).hexdigest()
    except (LedgerError, ValueError, TypeError, KeyError) as error:
        if isinstance(error, OpportunityStateError):
            raise
        raise OpportunityStateError('opportunity_policy_state_unavailable') from error
    return OpportunityIndex(snapshot, version, resolutions, aliases,
                            dossier_allowances, allowance_reviews, grants,
                            conditions, frozenset(unresolved), allowance_events, digest)


def load_index(root: Path) -> OpportunityIndex:
    """Build the validated index from one coherent read-only snapshot."""
    try:
        snapshot = read_stream_snapshot_readonly(Path(root), INDEX_STREAMS)
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
    if not isinstance(claim, ReopeningClaim) or claim.seal is None:
        return False
    if not isinstance(claim.observation, ConditionObservation) \
            or claim.observation.seal is None:
        return False
    return claim.prior_allowance_id in index.allowance_events


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
    allowance_reviews = [r for a, rows in index.allowance_reviews.items()
                         for r in rows if index.allowance_events.get(a) == event_id]
    spent = [r for r in allowance_reviews if _spends(r)]
    if spent:
        if _reopening_pending(index, reopening_claim):
            return PolicyDecision('reopening_pending', 'reopening_claim_pending',
                                  event_id, _current_allowance(index, event_id))
        return PolicyDecision('skip', 'unchanged_opportunity', event_id,
                              _current_allowance(index, event_id))
    current = _current_allowance(index, event_id)
    if dossier_hash is not None and index.dossier_allowances.get(dossier_hash) != current:
        return PolicyDecision('unknown', 'dossier_binding_missing', event_id, None)
    return PolicyDecision('eligible', 'allowance_available', event_id, current)
