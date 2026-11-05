# Opportunity entry policy — integration reference

Status: implemented and verified against the synthetic test suite; **not
activated in production and not deployed**. This document describes the
reviewed integration surface of the opportunity entry policy (Tasks 0–7):
what is enforced, what is explicitly not covered, and how operators must
interact with it. All examples and fixtures in the test suite are explicitly
synthetic; no real issuer, trade, or broker data participates.

## Versioning and the compatibility floor

- `SUPPORTED_POLICY_VERSION = 1` (`opportunity_activation.py`): the executed
  code enforces policy version 1 **only once an activation record exists**.
- Absent activation keeps the accepted Task 0 legacy compatibility floor:
  legacy Radar/reuse/autotrader behavior continues and mere absence of
  activation never denies a new entry.
- Once any activation record exists, malformed, unreadable, unknown or
  incompatible state denies new entry **fail-closed**. An activated version
  above 1 raises `opportunity_policy_version_unsupported`.
- Rollback after activation is to the tested compatibility floor (floor
  source `SUPPORTED_POLICY_VERSION = 0`), never to unguarded old main. The
  floor's lifecycle/protection/reconciliation paths continue; its entry path
  blocks with `opportunity_policy_version_unsupported` when it encounters an
  activated v1 root. This rollback behavior is rehearsed by
  `tests/test_opportunity_workflow.py`
  (`test_floor_rollback_blocks_entry_but_preserves_protection`) against a
  digest-authenticated pinned floor source copy supplied outside publishable
  source.
- Never delete policy records, clear obligations, cancel broker protection,
  or weaken the activation guard to obtain green.

## Decision flow

Lifecycle first, always: entry expiry, pending-order reconciliation, managed
protection and exit reconciliation precede every entry-policy decision and
continue under an activated policy. Only then does the entry boundary run:
`opportunity_state.require_current_allowance` reloads one coherent read-only
snapshot (unconditionally — a stale in-memory index is never trusted) and
returns a `PolicyDecision(outcome, reason, event_id, allowance_id)`.
Outcomes are `eligible`, `skip`, `unknown`, `reopening_pending`; only
`eligible` (or a verified provisional reopening claim) permits an attempt to
continue toward paid review. `reopening_pending` is research-only and
provisional.

Research intake (`alpha_radar`) binds every candidate to a verified event
identity, appends the trusted `identity_resolution` record itself, and links
the candidate dossier to the current allowance generation in
`candidates.jsonl`. Spending is generation-local: a completed review (any
real decision; empty/marker output such as `reconciliation_blocked` or
`execution_retryable` never spends) attaches to the canonical generation, and
only a durable `reopen_grant` record advances the allowance. Reuse/fallback
cannot resurrect spent or held work; the exact-dossier safe retry is
preserved and remains overridden by held/pending exclusion.

After a fill, no add-on reaches reviewers: positive broker positions are
`held` truth (`position_already_held`) and block before sizing and before any
paid review, regardless of caps, headroom or a new event.

## Reason tokens

Policy decisions (`opportunity_state`):

- `legacy_policy_floor` — eligible without activation (version 0).
- `policy_not_activated` — unknown for an activated-index-absent state.
- `opportunity_identity_unknown` — unresolvable/unverified identity.
- `opportunity_identity_conflict` — contradicting issuer/event evidence.
- `event_binding_missing` — event not present in the canonical index.
- `historical_binding_missing` — dossier appears in unresolved history.
- `dossier_binding_missing` — dossier not bound to the current generation.
- `allowance_available` — unspent current generation, eligible.
- `unchanged_opportunity` — current generation already spent (skip).
- `reopening_claim_pending` — sealed verified claim on a spent generation.
- `current_attempt_authorized` / `current_attempt_unauthorized` — sealed
  exact-attempt authorization re-proven (or not) against a fresh index.
- `position_already_held` — positive local exclusion or broker position.
- `unknown_history_unreconciled` — the verified issuer symbol has an open
  unknown-history gap (`unknown_history_blocks`); research stays unknown
  until every gap naming the symbol is bound or individually cleared.

Typed failures (`OpportunityStateError` / `ActivationStateError` /
`EntryStateError` / admin errors), all fail-closed:

- `opportunity_policy_state_unavailable` — malformed, unreadable, diverged or
  incoherent policy/ledger state; also the CLI blocker for corrupt state.
- `opportunity_policy_version_unsupported` — activated version above the
  runtime's supported version (including the floor meeting an activated v1).
- `opportunity_policy_not_activated`, `current_attempt_not_authorized`,
  `opportunity_candidate_binding_changed`, `opportunity_policy_root_mismatch`,
  `opportunity_policy_state_changed`, `opportunity_policy_state_regressed`.
- `broker_baseline_missing` / `broker_baseline_invalid` — the durable broker
  baseline is required; absence is never broker flatness.
- Entry evidence: `entry_evidence_invalid`, `entry_evidence_unverified`,
  `entry_evidence_overlong`, `entry_evidence_stale`, `positions_unverified`,
  `entry_symbol_invalid`; BUY outcomes map to `position_already_held`,
  `pending_qualification_required`, `same_symbol_pending_entry`,
  `flat_complete`.
- Admin: `approval_digest_mismatch`, `manifest_validation_failed`,
  `activation_incomplete_history`, `activation_version_regression`,
  `invalid_reopening_approval`, `observation_evidence_missing`,
  `prior_allowance_mismatch`, `event_not_spent`, `unknown_event`,
  `policy_append_failed`, `activation_append_failed`, `claim_*` failures.
- Missing-history migration: `invalid_missing_history_record`,
  `missing_history_observed_fields_mismatch`,
  `missing_history_symbol_evidence_unsubstantiated`,
  `missing_history_not_gap_row`, `missing_history_conflict`,
  `missing_history_hint_not_dossier`, `invalid_missing_history_clearance`,
  `missing_history_clearance_unknown_gap`, `clearance_manifest_isolated`.
- Autotrader CLI blockers also include `reopening_claim_unverified`,
  `reopening_commit:<error>`; a committed reopening claim ends the attempt
  deterministically with `DECISION reopening_committed` and never reaches
  paid review in the same run.

These tokens are mirrored in `run_cycle.py`'s `ALLOWED_FAILURE_TOKENS`, so a
deterministic policy blocker audits as `{"decision": "blocked",
"reason": <token>}` with exit 2 — never as an unspecified blocker and never
as a success label or a market-condition retry reason.

## Preconditions and run classification

- Activated policy requires pending-entry qualification enabled: with an
  activated policy, `evaluate_buy` hard-requires a valid pending proof even
  when `pending_entry_policy` is disabled in config. Activation implicitly
  requires pending qualification to be on; a disabled qualifier fails closed.
- Run classification of a mixed run: if the last attempted candidate ends
  with a non-policy `status: none` outcome while other candidates were
  policy-skipped, the run classifies as the non-policy outcome
  (`no_fresh_setup` family), not healthy policy exhaustion
  (`no_new_eligible_opportunity`). Both are exit-0 classes; only the audit
  reason differs.

## Entry evidence: bounded observation (new fields)

With an activated policy, broker truth is carried as a versioned
`entry_observation` dict on the snapshot (`entry_eligibility.entry_observation`):

`version` (1), `started_at`, `finished_at` (aware UTC, `finished_at >=
started_at`), `duration_seconds` (finite, non-negative),
`positions_complete` / `open_orders_complete` (must be `True`),
`position_count`, `open_order_count`, `position_digests`,
`open_order_digests` (canonical row digests), plus the validated `positions`
(each row: symbol, `side == 'long'`, finite positive `qty`) and `open_orders`
rows.

Limits: maximum observation age **120 seconds** from read start and maximum
monotonic read duration **120 seconds**. Future, naive or missing timestamps
fail closed. Quote freshness remains separately enforced. These bounds are
shared with the same 120-second limits documented in the brief.

## Resolver coverage limits (explicit, not hidden)

- Event identity resolution covers only explicitly reviewed, durably recorded
  bindings plus prospective `current_report_cover` captures that round-trip
  into the canonical index. There is **no** automatic semantic-materiality
  detector and no free-text-to-condition conversion.
- Historical reviews that cannot be attributed to a binding are unresolved
  history. They never imply a clean install: unscoped unresolved history is a
  typed failure (`opportunity_policy_state_unavailable`) and blocks
  activation. Only an explicitly reviewed manifest record with an optional
  `issuer_scope {binding_event_id, issuer_cik}` referencing a verified
  resolution and an exact canonical source row may scope ambiguity. Inferred
  or default issuer mappings are never created.
- Missing historical hashes/rows stay **unknown**; they are reported by the
  read-only admin audit and are never back-filled from models, sources or
  heuristics. Unknown-state behavior is always fail-closed: unknown identity,
  unknown position truth or unknown policy state can never authorize paid
  review or a BUY.

## Admin approval rules (`opportunity_admin`)

- `import_manifest(root, manifest, approved_manifest_sha256=...)` requires the
  explicit reviewed canonical digest (`canonical_manifest_digest`); approval
  is never inferred from source or model text. Import is idempotent,
  revalidates under the entry lock, and rejects hidden resets, changed
  digests/sequences, scope conflicts, erasure or repointing.
- `activate(root, manifest, approved_manifest_sha256=...)` imports then
  appends one activation provenance record; idempotent; refuses incomplete
  unscoped history (`activation_incomplete_history`) and version regression.
- `grant_reopening(root, approval, approved_manifest_sha256=...)` requires a
  durably recorded sealed observation, references the spent prior allowance,
  and derives the grant idempotently. Each grant is one-shot; history is
  append-only. `commit_reopening_claim` revalidates under the entry lock.
- The CLI is read-only by default (`audit`, `validate`); every mutation needs
  an explicit flag and `--apply`, and writes artifacts with mode 0600.
  **Apply remains separately authorized**: nothing in this repository
  activates or bootstraps production.

## Legacy-history audit compatibility

A legacy candidate's `dossier_hash` alone is not a policy link and grants no
allowance. Presence of either `event_id` or `allowance_id` still requires the
complete, valid immutable link; partial new-policy rows remain fail-closed.
A reviewed identity-resolution record with an exact canonical source row
containing a dossier hash binds that dossier to generation zero. Subsequent
reopening cannot relocate its historical spending, and changed source
sequences/digests or conflicting dossier bindings are refused on index reload.
Identity provenance without a source dossier hash grants no dossier permission.
Retained pre-decision reviewer `action: BUY` / `action: HOLD` outputs are
completed paid-review history and conservatively spend a bound allowance;
they never prove dual-review approval or safe retry. Explicit marker decisions
still do not spend, and original review payloads are never rewritten.

When retained reviews lack original dossier hashes, `audit_history` returns a
**blocked diagnostic**, not a usable index: `index_available: false`,
`blockers: [historical_dossier_hash_missing]`, canonical watermarks, row counts,
and exact `missing_dossier_sources` (stream, sequence, UTF-8 canonical row
SHA-256) plus any tolerated `missing_history_gaps`. Every row is still
validated; unrelated corrupt/partial policy state
is not hidden by that diagnostic. Index loading and activation remain blocked
with `opportunity_policy_state_unavailable`; manifest validation/import
tolerate the typed blocked state only so reviewed migration manifests can be
validated and imported (never approved or applied by the audit itself).
The audit does not invent a hash, infer an issuer, discard dissent, or approve
a migration. Missing original associations require authenticated historical
evidence or a separately reviewed migration design, not current-cache hashes.

## Migration / bootstrap rehearsal (private)

The historical audit/import/activation rehearsal runs only on an
authenticated **disposable copy** of retained local history, never on
production, and its evidence (source manifests, exact digests, probe scripts,
rehearsal receipts, elapsed times and lookup counts) is kept outside
publishable source under `private/task7-evidence/`. Missing historical
hashes remain unknown in the rehearsal; unresolved cases stay explicit in the
manifest proposal, which is **reviewed, not applied**. No unmeasured speedup
or coverage claim is made; measured values live in the rehearsal receipts.

## Missing-history migration contract

Proven-unrecoverable canonical rows (hashless legacy review rows and hashless
filled BUY trade rows) are represented as fail-closed `missing_history`
records (schema_version 1) in `private/opportunity_policy.jsonl`:

- Fixed vocabularies: `kind` ∈ {`legacy_review_unlinked`,
  `filled_buy_unlinked`}; `reason` ∈
  {`recovery_exhausted_exact_link_unavailable`}. Each record carries an exact
  `source` ref (stream ∈ {`private/reviews.jsonl`, `trade_journal.jsonl`},
  one-based sequence, recomputed UTF-8 canonical row SHA-256), `observed_fields`
  exactly equal to the referenced row's key set, optional `issuer_evidence`
  (`{"symbol": S}` where `S` is the first `symbol`-keyed value found at any
  depth of the referenced row's own canonical bytes — absent symbols force
  `issuer_evidence: null`), and an optional `hint`
  (`{"legacy_proposal_hash": <64hex>}`, asserted never to equal any canonical
  dossier hash at import: `missing_history_hint_not_dossier`).
- Every hashless gap-classified row must be exactly referenced by a validated
  `missing_history` record; unreferenced gaps still raise the typed
  whole-index blocker (gap validation runs before the raise — no partial
  index). Hashless filled SELL trade rows are non-blockers.
- The migration-validation read is one coherent widened snapshot
  (`MIGRATION_SNAPSHOT_STREAMS` = index streams + `trade_journal.jsonl`;
  gap sources use the dedicated allowlist `MIGRATION_SOURCE_STREAMS` =
  {`private/reviews.jsonl`, `trade_journal.jsonl`}, separate from the
  unchanged binding-source `INDEX_STREAMS` boundary):
  `trade_journal.jsonl` rows are digest-checked for gap references only,
  never a binding source and never consumed by decision code. The shared
  binding-source boundary is unchanged.
- `unknown_history_blocks` maps each normalized symbol (exact after
  `casefold()` + whitespace trim; no alias or exchange-suffix matching) to its
  open gap refs, derived only from validated `issuer_evidence`.
  `candidate_policy` returns `unknown_history_unreconciled` for a verified
  issuer symbol in that set. Blocking never grants, spends, proves dual
  approval, or qualifies retry.
- Optional per-gap `missing_history_clearance` records (schema_version 1;
  `clearance_reason` ∈ {`permanently_unattributable_user_acknowledged`},
  exact `gap_source` ref) unblock one gap at a time: a symbol unblocks only
  when every gap naming it is bound or individually cleared. Clearance
  records travel only in their own dedicated approved manifest
  (`clearance_manifest_isolated` otherwise), and the underlying
  `missing_history` records are kept forever.
- Manifest validation/import tolerate the typed blocked state so migration
  manifests can land while gaps remain uncovered; activation still requires
  the full coverage gate (`activation_incomplete_history`).
- Rollback semantics: rollback is a code revert to the pre-migration reader
  (`7c81de800495acb8b2a6c7e5096128437307d785`-era). A migrated policy stream
  read by the pre-migration reader fails typed
  (`opportunity_policy_state_unavailable`) over the **entire** stream — never
  mistaken for corruption, never partially accepted. Therefore never import
  a manifest the old reader cannot parse: after a revert, the records are
  inert-but-present and the whole stream is unavailable until the newer
  reader is restored. `missing_history`/clearance records are inert at the
  v0 floor (no activation): the legacy floor decision is unchanged.

## Residual limitations

- **External-writer race**: the index is built from one coherent read-only
  snapshot and reloaded before every safety decision, but a writer outside
  the canonical ledger lock appending between a reload and a downstream
  durable action can still interleave. The window is bounded by the reload
  discipline, not eliminated; crash recovery relies on durable review/grant
  rows (a crash after a durable review but before any index refresh can never
  create a new allowance — verified by
  `test_crash_after_durable_review_or_grant_before_index_refresh`).
- The activation projection depends on the canonical jsonl + database
  sidecar; a missing/diverged sidecar is incomplete state and blocks, never a
  silent downgrade to the legacy floor.
- No deployment, publication, activation, or order canary is performed by
  this work. The authorized deployment sequence (freeze, pause, promote,
  approved idempotent import/activation, verify, floor-aware rollback) is
  documented in the approved plan and is **not executed** here; publication
  and production activation require separate explicit approval.
