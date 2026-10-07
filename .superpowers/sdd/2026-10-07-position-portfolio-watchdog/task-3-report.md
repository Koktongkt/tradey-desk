# Task 3 report — exact lineage and forward-only private metadata

## Status and scope

**DONE_WITH_CONCERNS: implemented, tested, self-reviewed and committed; independent parent review remains required before release.**

- Worktree: `/opt/data/projects/tradey-desk/.worktrees/position-watchdog`, branch `feat/position-watchdog`.
- Base: `afbbfeb0a4f717ce10194aa167fdab6507bc77e8`.
- Implementation commit: `186d4851de4329482bce4c8d5bc8fdfdfdff3133`.
- This report is committed separately after the implementation. No push, deployment, live broker call, schedule/control change, operational append, historical rewrite, or live-product edit was performed. No subagents were dispatched. The progress ledger and whole plan were not read/modified.
- Read Task 3 brief first, then shared global context and approved spec; inspected existing types, broker normalized fields, source persistence sites and fixture shapes. Production rows were deliberately not read, per delegated no-live-read constraint. Fixture inspection emitted only top-level keys and nested key lists, not account IDs or private theses.

## Modified paths

1. `watchdog/lineage.py` — pure projection and cumulative-delta helper.
2. `private_lineage.py` — execution-side allowlisted private metadata helpers, shared to avoid circular imports.
3. `autotrader.py` — original persistence sites only: reviews/retry markers, private rejection/proposed/lifecycle rows, intent envelope, immediate/pending confirmed fills, original-bracket closure rows.
4. `managed_reconciliation.py` — replacement-OCO/shared reconciliation fill and closure persistence metadata. This execution-adjacent writer also needed propagation; leaving it unchanged would lose lineage on replacement exits.
5. `tests/test_watchdog_lineage.py` — 21 pure tests, registered fast.
6. `tests/test_watchdog_forward_lineage.py` — 9 isolated workflow tests, registered scenario.
7. `tests/test_manifest.json` — module classification only.
8. `.superpowers/sdd/2026-10-07-position-portfolio-watchdog/task-3-report.md` — this handoff.

## Persistence inventory and invariants

| Writer / serializer | Existing destinations and behavior | Forward additions / unchanged boundary |
|---|---|---|
| `autotrader.run`, review append (1360–1361) | `private/reviews.jsonl`, or dry-run reviews artifact; immutable proposal/reviews already available | Top-level `candidate_id`, existing `dossier_hash`, authoritative `proposal_hash`. Candidate-supplied parent/proposal fields are not trusted as execution identities. Reviewer bundle itself unchanged. |
| Reviewer rejection (1366) | `order_ledger.jsonl` and `public/disagreements.jsonl` | Only private ledger receives lineage. Public disagreement receives the original unextended sanitized row. |
| Proposed and derived lifecycle/rejection rows (1373 onward) | Private operational ledger / dry-run artifact | `candidate_id`, `dossier_hash`, `proposal_hash`, authoritative `parent_client_order_id=ref`; existing `client_order_id`, evidence and executable summary unchanged. Derived events inherit metadata via the existing `proposed` envelope. |
| Intent append (1399) | `private/order_intents.jsonl` before submission | Same top-level private fields. Nested `plan` is not changed. No additional broker/reviewer payload fields. |
| Immediate confirmed fill, `journal_confirmed_fill` (641–648; call after readback) | Existing journal writes only at status `filled`, using existing float quantity/price/basis | Optional fourth argument carries private lineage; original three-argument callers still work. Broker-confirmed IDs and Decimal-derived cumulative strings added to new row only. Existing status/numeric gates and legacy accounting fields unchanged. |
| Pending reconciliation (1097–1122) | Validate all pending readbacks before existing ledger/fill appends | Copy top-level intent metadata into new status/fill rows; retain nested plan and reconcile payload. No symbol-based metadata backfill. |
| Original bracket exits (956–1095) | Exact parent/leg validation; existing journal and `closed` ledger row | Intent lineage plus exact exit broker/client identity and cumulative strings. Parent is the validated original `ref`, even if a metadata envelope supplies a contradictory parent. Existing closure-key algorithm and execution/reconciliation policy unchanged. |
| Shared/replacement OCO `managed_reconciliation.reconcile_detailed` (212–280) | Existing exact registration/readback, quantity/protection gates, journal and closure ledger writes | Same lineage/fill metadata; row's existing authoritative parent wins, and closure ledger carries lineage. No watchdog import/call to this mutating reconciler. |
| Retry/reconciliation-block review markers (1204–1231) | Existing narrow retry decisions, best-effort semantics | Only candidate ID/dossier identity available at these sites; do not copy candidate-supplied proposal/parent order IDs. |
| `register_protection` (288–323) | Existing parent/replacement exact references; serializer appends supplied registration | Unchanged: already has authoritative `parent_client_order_id` and `protection_client_order_id`. Projection consumes these exact refs without ticker inference. |
| `durable_jsonl` / SQLite compatibility serialization | Existing append/read authority contract | Unchanged. New additive JSON fields use the original serializers. No migration, sync/repair or historical rewrite was added. Watchdog projection performs no I/O. |
| `public_dashboard` sanitizer, notifications, shadow decisions, diagnostics | Existing public allowlists/output and execution behavior | Unchanged; no lineage allowlist expansion. New private fields are not public projection inputs added by this task. |

New confirmed-fill row additions, where authoritative data is available:

```python
{
    'candidate_id': 'cid', 'dossier_hash': 'dh', 'proposal_hash': 'ph',
    'parent_client_order_id': 'parent',
    'broker_order_id': 'broker-id', 'client_order_id': 'parent-or-exit',
    'cumulative_filled_quantity': '3', 'cumulative_filled_notional': '488.40'
}
```

These illustrative values come from isolated fixtures, not a production account. Optional unknown identifiers are omitted, not synthesized. An old intent without candidate identity remains backward compatible and does not gain an inferred candidate. Cumulative fields are **observations**, not declarations of a new incremental BUY/SELL.

## Projection interface for downstream tasks

`build_lineage(op: OperationalSnapshot, broker: BrokerSnapshot) -> LineageResult` is pure and read-only. Stream names are the exact `DEFAULT_STREAMS` relative paths, notably `candidates.jsonl`, `private/reviews.jsonl`, `order_ledger.jsonl`, `private/order_intents.jsonl`, `trade_journal.jsonl`, and `private/protection_orders.jsonl`.

Joins use explicit candidate/dossier/proposal/evidence/client-order identities. Intent plan proposal hash is part of the same explicit relationship. Exact normalized broker IDs/client IDs bind orders; actual parent/leg relationships and explicit replacement registrations bind protective orders. Market symbol and side are validation checks only, never join keys. Candidate ID absent but unique explicit dossier present is supported with `candidate_id=None`, without inventing an ID. Missing both identities is retained as an unknown decision.

### Position row — every emitted position has these fields

- Identity: `position_id` (exact parent client order ID, not invented), `candidate_id` (optional), `dossier_hash` (optional), `proposal_hash` (optional from plan/intent), `evidence_ids` (list), `parent_client_order_id`, `broker_order_id`, `symbol`.
- Cumulative accounting: `entry_quantity`, `entry_notional`, `exit_quantity`, `exit_notional`, `remaining_quantity`; all Decimal in memory, except remaining is `None` when exact exits exceed entry.
- Independent ownership observation: `ownership` = `verified`, `discrepancy`, or `unknown`; `broker_symbol_quantity` is Decimal or None and is **not** the managed quantity.
- Original plan/baseline: `planned_exit_at`, `stop`, `target` (Decimal or None), `setup_type`, `horizon`, `thesis_baseline` (private allowlisted supplied `thesis`, `catalyst`, `assumptions`, `breakers`, `kpis`, `risks`). No original baseline is generated/enriched.
- Protection relationship: `protective_client_order_ids` includes all exactly related descendant and registered replacement refs (not a claim that these orders are currently effective/live protection).
- Evidence: `fill_observations`, `fills`, `fill_event_coverage='requested_interval_only'`, `delta_status='unknown'`, `operational_captured_at`, `broker_captured_at`.

Example fragment:

```python
{
    'position_id': 'parent', 'candidate_id': 'idea-a', 'dossier_hash': 'da',
    'parent_client_order_id': 'parent', 'broker_order_id': 'broker-parent',
    'entry_quantity': Decimal('2'), 'entry_notional': Decimal('20'),
    'exit_quantity': Decimal('1'), 'exit_notional': Decimal('12'),
    'remaining_quantity': Decimal('1'), 'ownership': 'discrepancy',
    'broker_symbol_quantity': Decimal('11'),
    'protective_client_order_ids': ['replacement'],
    'delta_status': 'unknown', 'fill_event_coverage': 'requested_interval_only'
}
```

The extra ten account shares are never attributed to this parent. Baseline/manual holdings are not acquired by symbol matching. Two ideas in one symbol remain separate parents; aggregate account quantity is compared only to the sum of exactly owned quantities.

`fill_observations` contains one row per exact entry/exit order:

```python
{
    'broker_order_id': 'o', 'client_order_id': 'ref', 'side': 'buy',
    'cumulative_quantity': Decimal('3'), 'cumulative_notional': Decimal('32'),
    'captured_at': '2026-10-07T15:00:00Z', 'trusted': True
}
```

`fills` contains compact exact broker **activity events** only: `activity_id`, `broker_order_id`, `side`, `quantity`, `notional`, `timestamp`. Duplicate activity IDs are not replayed. Side/symbol contradictions reject that activity and add a reason. Activity interval coverage is never presented as lifetime fill/accounting completeness. Cumulative totals come from orders; journal/account aggregate rows cannot substitute for execution-event identity.

### Decision row — common keys even for unknown identities

`candidate_id`, `dossier_hash`, `symbol`, `proposal_hashes`, `client_order_ids`, `evidence_ids`, `review_decisions`, `broker_statuses`, `status`, `coverage`.

`status` is observational: `researched`, `approved` (review observation, not authorization), `reviewer_rejected`, `submitted_unfilled`, `filled`, `closed`, `unknown`, or the existing linked ledger status such as `proposed`/`rejected`/`failed`/`submission_unknown`. Raw reviewer decisions and broker statuses remain separate. Consumers must not interpret `approved` as a fresh trading-policy result. Exact evidence_id links a rejection even when no client ID exists. `coverage` describes the local decision chain; consumers must also honor top-level source/lineage coverage.

### Coverage and reason contract

`LineageResult.coverage` keys:

- `status`: `complete` or `unknown`.
- `ambiguous_order_refs`: count of contradictory candidate/dossier, intent-plan or shared-exit references.
- `unattributed_journal_rows`: count of journal rows not bound to an exactly owned broker parent/exit.
- `duplicate_fill_observations`: repeated broker-order identity + cumulative-quantity observations, independent of filled_at.
- `managed_positions`: emitted position count.
- `fill_event_coverage`: `requested_interval_only`.
- `operational_complete`, `broker_complete`: copied summary flags, never upgraded.

Reasons are stable private codes: `operational_snapshot_incomplete`, `broker_snapshot_incomplete`, `lineage_contradictory`, `intent_lineage_unknown`, `intent_plan_conflict`, `referenced_order_missing`, `referenced_protection_missing`, `order_lineage_mismatch`, `managed_exit_exceeds_entry`, `managed_quantity_discrepancy`, `activity_order_mismatch`, `fill_observation_invalid`, `fill_observation_conflict`, `journal_lineage_unknown`, `candidate_identity_unknown`, plus supplied operational reason codes.

Invariants:

1. An incomplete source or unknown broker orders/references/activities domain cannot become complete/verified/trusted.
2. Conflicting candidate/dossier/parent ownership or conflicting duplicate intent plans do not choose the first match.
3. Journal rows do not change projected order quantities or invent executions; unlinked legacy BUY rows stay unattributed. Repeated cumulative quantities are deduplicated by broker identity and quantity; unequal total notional at that same quantity is a coverage conflict.
4. Missing referenced orders/protection are unknown, not an empty verified sleeve/protection set.
5. Remaining exact ownership is never silently replaced by broker-symbol account quantity. Excess exact exits yield `remaining_quantity=None` and discrepancy, not a negative owned lot.
6. A complete lineage snapshot is **not** proof of complete lifetime FIFO events, corporate actions, costs, distributions, protection efficacy, thesis baseline or performance baseline. Those domains belong to later tasks.

### Delta helper for monitoring-store integration

`cumulative_fill_delta(current, previous)` returns `{status, quantity, notional, reason}`. `previous` must be an explicitly trusted saved observation with the **same broker_order_id**, both cumulative quantity and total notional. Missing/untrusted previous state, an explicitly untrusted current observation, reversed/malformed provided clocks, decreasing quantities/notionals, or notional change without quantity change produce `status='unknown'`, null deltas and `reason='fill_delta_coverage_unknown'`. Identical observation gives zero/zero. Valid 2 shares/$20 → 3 shares/$32 yields 1 share/$12, not the latest average price times the delta.

`build_lineage` has no monitoring-store previous state, so emits `delta_status='unknown'` rather than treating cumulative entry quantity as a new BUY. Later store/accounting must persist trusted previous observations transactionally and call this helper, or use exact deduplicated activity IDs with their explicit interval coverage. Never initialize a historical quantity observation to a fabricated zero merely to replay an entry. If neither path proves the required delta/event history, accounting stays incomplete.

## TDD evidence — exact commands and observed results

All commands below ran from the isolated worktree. Missing-module/API/key errors in RED were expected absent-feature failures, not silently treated as passing tests. One fixture harness issue was corrected before the corresponding implementation (noted below).

Commands used:

```sh
# L: used at each pure projection slice
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage -v
# F: used at each persistence slice
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_forward_lineage -v
# C: combined focused run
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -v
# E: authoritative exit-parent fix
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_forward_lineage.ForwardLineageTests.test_both_protective_exit_writers_copy_lineage_from_intent -v
# S: common unknown-decision schema fix
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_unidentified_candidate_is_visible_unknown_decision -v
```

| Slice / command | RED observed | GREEN observed |
|---|---|---|
| Exact two-idea/legacy exclusion, L | 2 run; 2 errors (missing lineage module) | 2 passed |
| Contradictory refs, incomplete input, exact rejected evidence, L | 5 run; 1 failure, 2 missing-contract errors | 5 passed |
| Parent exits, repeated observations/intents, trusted cumulative delta, L | 8 run; 2 failures, 1 missing-helper error | 8 passed |
| Replacement refs/activity, missing parent, notional conflict, over-exit, dossier-only identity, L | 13 run; 4 failures, 1 error | 13 passed |
| Summary/domain completeness, conflicting intents, missing-ID decisions, activity mismatch, trusted clock/delta, L | 18 run; 5 failures | 18 passed |
| Forward immediate/pending fills, F | 2 run; 2 errors (old API/missing metadata) | 2 passed |
| Isolated submit/dry-run/reviewer rejection metadata, F | 5 run; 3 missing-field errors after harness correction | 5 passed |
| Both exit writers and retry reviews, F | 7 run; 2 missing-field errors | 7 passed |
| Review-only state, narrow retry provenance, reconciliation-block candidate ID, C | 28 run; 2 failures, 1 missing-field error | 28 passed |
| Exact authoritative exit parent wins, E | 1 run; 1 failure (`wrong-parent` copied) | 1 passed |
| Decimal planned levels and authoritative submitted/unfilled outcome, L | 21 run; 2 failures | combined C: 30 passed |
| Common unknown-decision schema, S | 1 run; 1 failure (three missing keys) | 1 passed, then combined C: 30 passed |

Harness correction: the initial F 5-test run had two setup TypeErrors because the repository dry-run reviews did not yield an approved order under the deliberately controlled test config. The isolated helper was corrected to supply APPROVE reviews with valid rubric scores; rerun showed the intended three missing-metadata errors before changing run persistence. No product fix was made to accommodate that harness error.

Final verification commands/results:

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -v
# Ran 30 tests in 0.610s; OK
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py fast
# 21 modules / 295 tests; Ran 295 in 11.145s; failures=0 errors=0 skipped=0
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py scenario
# 9 modules / 161 tests; Ran 161 in 5.045s; failures=0 errors=0 skipped=0

git diff --check
# No whitespace errors
python3 -m py_compile private_lineage.py watchdog/lineage.py autotrader.py managed_reconciliation.py tests/test_watchdog_lineage.py tests/test_watchdog_forward_lineage.py
# Exit 0
```

The fast runner prints an existing fixture `BLOCKER dry_run_no_execution` line; it is not a failed test. Both tier runners included their operational-isolation snapshot checks and reported no `OPERATIONAL_ISOLATION_FAILURE`. Earlier fast/scenario runs were also clean (287/159 before the final added test slices, then 295/161). No live service was called by these tests. Full-only and release smoke were not run for this task.

## Executable payload/hash/policy preservation evidence

- Focused submit test runs actual canonical proposal, actual aggregate review logic, actual normalization and `autotrader.run` against isolated files and mocked broker/reviewer/policy boundaries. Captured broker `place` payload equals the original expected `{order: plan, client_order_id: ref}` exactly. Persisted nested intent plan equals that executable plan. Actual reviewer bundle equals the independently built expected bundle. Only private persistence envelopes differ.
- Rejection test verifies none of the four added private lineage identifiers enters `public/disagreements.jsonl`; dry-run test checks metadata in test_artifacts and absence of operational ledger, intents and journal outputs.
- Existing fast/scenario safety, execution-policy, broker normalization, notification, reconciliation and public pipeline tests remain green.
- An AST comparison against base using `git show afbbfeb0a4f717ce10194aa167fdab6507bc77e8:autotrader.py` returned **Protected AST unchanged: True** for `build_canonical_proposal`, `build_review_bundle`, `authoritative_bundle`, `aggregate_proposal_reviews`, `idempotency_ref`, `validate_order_with_details`, `pre_review_validation`, `post_review_validation`, `broker_review_validation`, and `broker_order_notification_line`.
- The only changed autotrader function bodies were `journal_confirmed_fill`, `note_pre_submission_retryable`, `note_reconciliation_blocked`, `reconcile_managed_exits`, `reconcile_pending_orders`, and `run`, at their documented private persistence boundaries. Source review confirms existing broker operation dispatch/payloads, validators, enabled/broker-mode handling, reconciliation/closure policy and canonical hashes were not changed. Existing timestamp-based operational closure keys were intentionally not redesigned here; the watchdog independently treats cumulative observations by broker identity/quantity.
- Static added-source scan for secrets, shell=True/os.system, eval/exec, pickle and formatted SQL found no pattern hits. Watchdog lineage imports only Decimal/shared types, never operational readers/serializers or mutating broker/reconciliation code.

## Self-review, limitations and release handoff

Self-review found and RED-tested fixes for summary completeness disagreeing with domain coverage, conflicting duplicate intent plans, missing-ID decision omission, activity symbol/side mismatch, missing prior/current trust/clock evidence, exact authoritative parent metadata precedence, Decimal planned levels and common unknown-row shape. Cumulative quantity and notional deltas are both validated; no latest-average-price shortcut or initial cumulative BUY replay was introduced.

Remaining concerns are explicit integration/release boundaries, not waived requirements:

1. **Independent review is still pending.** The parent was instructed to perform fresh frozen-diff review after this commit; this subagent did not create another reviewer. Do not release on self-review alone.
2. The store/accounting integration must honor `delta_status='unknown'`, activity interval coverage and top-level coverage. This task does not supply a lifetime baseline or make legacy journals attributable.
3. A discrepancy can include legacy/manual quantity sharing a managed symbol; no excess account quantity is acquired. Protection membership here is not proof of live coverage (Task 4 must inspect actual normalized order fields).
4. Metadata remains private. No public allowlists were broadened; reporting must continue explicit sanitization. Review-only `approved` is an observed verdict, never fresh policy authorization.
5. All operational writer behavior remains unchanged except additive fields. Existing historical closure keys and entry-fill journal semantics were not rewritten; watchdog accounting must not sum repeated journal observations as new fills.
6. Before deployment, the controller must inventory/pause the affected autotrader, original-bracket and shared/replacement reconciliation writers, verify pause states, deploy/review/smoke, then restore approved states. No operational pause or schedule action was taken here.

## Fix round 1/5 — authoritative graph, intent consistency, journal corroboration

**DONE_WITH_CONCERNS: all three Important review blockers repaired and self-reviewed; parent scoped re-review remains required.**

- Fix base verified: `cbeb233470891cdd4d752373b26729c8b82c96e8`; clean starting worktree.
- Source/test commit: `e28cbc18229c49d00f22b9798775aadd27c1b017` (`fix(watchdog): require authoritative corroborated lineage identities`). This report is appended in a separate documentation commit.
- Modified only `watchdog/lineage.py`, `tests/test_watchdog_lineage.py`, `tests/test_watchdog_forward_lineage.py`, and this report. No new files. No subagents, controller-ledger edits, live reads/calls, historical rewrites, deployment, push, operational writes or control changes.
- Loaded TDD and systematic-debugging skills. Read the Task 3 brief first, global context, entire existing report/review, relevant source/tests and worktree AGENTS rules. Root causes matched the review: non-authoritative candidate tokens in construction and matching, union without envelope consistency, and first-success journal fallback that ignored remaining identifiers.

### Repairs and schema invariants

1. Stream-specific graph construction: candidates contribute only candidate/dossier identity; reviews contribute research/proposal/evidence identities, not client-order edges; authoritative ledger rows contribute their recorded execution relationships. Intents contribute only proposal-to-client edges for already recorded proposals. Proposal provenance is frozen before intent edges are connected, preventing an intent or client ledger path from inventing its proposal's owner. Candidate matching also ignores candidate-supplied proposal/client/evidence tokens. Candidate-only identity cannot substitute for missing review/proposed provenance or a missing intent proposal.
2. Every intent is checked before projection: envelope proposal hash equals nested-plan proposal hash whenever both are supplied; a BUY envelope parent equals its actual client-order ID. Supplied candidate/dossier identities must corroborate the authoritative chain. Contradictory refs are counted ambiguous, excluded from positions/trusted observations and shown as unknown decisions. Multiple valid proposals on separate intents for one candidate remain supported; this is not a global one-proposal restriction.
3. All journal broker/client/exit tokens must resolve to the same owned execution order; a supplied parent must equal that order's owned entry parent. No unresolved broker ID can fall back to a valid client token. Supplied candidate/dossier/proposal identities must match that position, and supplied evidence must be recorded for that exact entry proposal, not merely somewhere in the candidate component. Contradictions increment unattributed rows and surface `journal_lineage_unknown`/unknown top-level coverage. They never change broker-derived quantities, notionals, order ownership or activity events.
4. No new schema keys, persistence fields, migrations or reason codes. Existing coverage counters/reasons are reused. Position `evidence_ids` is now exact-proposal-specific; decision `evidence_ids` remains candidate-wide. Broker-local observation trust remains distinct from journal/domain coverage: consumers must still honor top-level unknown coverage. No ticker/time identity fallback was added.
5. No execution writer/helper was changed in this fix. Existing forward-only persistence, plans, proposal hashes, reviewer bundles, broker payloads, dry-run isolation and private/public boundaries remain unchanged. The new isolated workflow test runs real `autotrader.run` with controlled broker/reviewer boundaries, proves generated envelopes project completely, then proves the real intent plus model-injected tokens cannot replace removed review/ledger provenance.

### Exact RED/GREEN commands and observed results

All commands ran from `/opt/data/projects/tradey-desk/.worktrees/position-watchdog`. RED failures were assertion failures for wrong attribution, not syntax/import/setup errors. Subtest failure counts are distinguished from unittest test-method counts. Safety-positive controls that already passed are not claimed as RED behavior changes.

```sh
# R1: candidate execution tokens, six missing-chain variants
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_candidate_execution_tokens_cannot_complete_missing_chain -v
# RED: 1 test method; 3 subtest failures (review missing + proposal/client injection;
# plan proposal missing + client injection). Remaining negative variants already safe.
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage -v
# GREEN: 22 tests; OK.

# R2: intent's own candidate/dossier metadata cannot create missing proposal provenance
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_intent_identity_without_authoritative_proposal_chain_is_unknown -v
# RED: 1 test; 1 failure (incorrect emitted verified position).
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage -q
# GREEN: 23 tests; OK.

# R3: internal contradictions, including another legitimate proposal of same candidate
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_contradictory_intent_envelopes_cannot_be_rescued_by_union test_watchdog_lineage.LineageTests.test_separate_valid_proposals_for_same_candidate_remain_owned -v
# RED: 2 test methods; 2 contradictory-envelope subtest failures;
# separate-valid-proposals positive control passed.
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage -q
# GREEN: 25 tests; OK.

# R4: independently conflicting journal identifiers, with valid exit-parent control
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_journal_every_supplied_identity_must_corroborate_exact_order test_watchdog_lineage.LineageTests.test_journal_exit_identifiers_corroborate_parent_without_being_same_order -v
# RED: 2 test methods; 7 subtest failures (candidate, dossier, proposal, evidence,
# nonexistent broker ID, client ID, exit ID). Parent conflict and valid-exit controls passed.
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -q
# GREEN: 36 tests; OK.

# R5: evidence from another proposal of the same candidate cannot corroborate this entry
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_journal_evidence_must_belong_to_entry_proposal_not_just_candidate -v
# RED: 1 test; 1 failure (unattributed was 0 rather than 1).
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -q
# GREEN: 37 tests; OK. git diff --check also clean.

# R6: ledger client identity cannot replace absent intent proposal
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_client_ledger_identity_cannot_replace_missing_intent_proposal -v
# RED: 1 test; 1 failure (emitted position with proposal_hash=None).
# Applied the missing-proposal guard, then added the next focused provenance counterexample.

# R7: ledger client path cannot validate an unrecorded intent proposal
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_unreviewed_intent_proposal_cannot_join_via_ledger_client -v
# RED: 1 test; 1 failure (emitted verified position for unrecorded proposal).
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -q
# GREEN for R6/R7: 39 tests; OK.
```

R6's first guard was not separately executed GREEN before R7 was added; both guards were actually verified by the combined 39-test run. This sequencing deviation is disclosed rather than claiming an unrun command. Added post-fix preservation controls for a real conflicting broker ID versus client ID and the isolated real-persistence projection; no further product changes were needed for those controls.

Final verification (after all source/test edits):

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -v
# Ran 40 tests in 0.410s; OK (30 pure + 10 workflow).
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py fast
# 21 modules; Ran 304 tests in 10.634s; failures=0 errors=0 skipped=0.
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py scenario
# 9 modules; Ran 162 tests in 5.574s; failures=0 errors=0 skipped=0.
git diff --check
# Clean.
python3 -m py_compile watchdog/lineage.py tests/test_watchdog_lineage.py tests/test_watchdog_forward_lineage.py
# Exit 0.
```

Both tiers passed operational-isolation checks (no `OPERATIONAL_ISOLATION_FAILURE`). Existing fast fixture stdout `BLOCKER dry_run_no_execution` remains explicitly deferred as directed; it is not a failed test. Full-only suite/release smoke was not run.

### Self-review and concerns

- Reviewed the entire source/test diff before explicit-path commit; verified only projection and tests changed. Checked stream trust boundaries, metadata contradiction ordering before position creation, frozen proposal provenance, per-proposal journal evidence, exact exit/parent semantics and no journal-to-broker total mutation. Tests assert snapshots are not modified.
- Self-review found two additional union-rescue variants (missing intent proposal despite valid client ledger and unrecorded intent proposal joined through ledger client); both reproduced RED and were repaired with frozen provenance checks. It also found same-candidate cross-proposal evidence overreach, reproduced RED and narrowed position evidence to the actual proposal.
- Existing payload/hash/reviewer/public/dry-run safety tests all remain green. Execution writers and serializers are byte-unchanged in the fix commit; no new operational path exists.
- **Concern: fresh parent scoped re-review is still required; this is not release approval.** Existing downstream requirements to honor unknown coverage/initial deltas, production writer pause/readback and deployment smoke remain unchanged controller responsibilities.
- **Concern: intentionally conservative attribution.** Incomplete authoritative proposal/evidence metadata remains unknown/unattributed rather than rescued by candidate fields, order aliases or ticker/time. Journal contradictions do not erase otherwise valid broker-local cumulative evidence; consumers must not interpret that local evidence as complete journal/lifetime accounting coverage.
- No blocking tool/install/network failure encountered. No unrelated refactor or fixture-output cleanup was performed.

## Fix round 2/5 — incomplete/malformed intent identity cannot contaminate the lineage graph

**DONE: the re-review Important blocker (missing intent client-ID projection crash) is repaired via TDD, self-reviewed, and committed; parent scoped re-review remains required.**

- Fix base verified: `ea1fd081a9df162109ba2c57f997ea577482d95f`; clean starting worktree.
- Source/test commit: `9667dec` (`fix(watchdog): reject incomplete intent identities before lineage graph`). This report is appended in a separate documentation commit.
- Modified only `watchdog/lineage.py` and `tests/test_watchdog_lineage.py`. No execution writer, schema, payload, hash or policy change; no subagents, pushes, controller-ledger edits, live reads/calls, operational writes or schedule/control changes. `tests/test_watchdog_forward_lineage.py` untouched and still green.
- Loaded TDD and systematic-debugging skills; re-read the brief, global context, prior report/review. Root cause confirmed as reviewed: intent edges connected `('client_order_id', None)`/non-string tokens into the proposal component, and heterogeneous values reached the `sorted()` at the decision stage (`lineage.py:280`), raising `TypeError`. Operational input validation does not check intent-field presence, so the projection must defend itself.

### Repair

`build_lineage` now pre-validates every intent row before any graph/hash/sort operation. An intent is excluded (reason `intent_lineage_unknown`; valid intents and the rest of the graph unaffected) when: `client_order_id` is absent/non-string/empty; `plan` is absent/non-dict; any present `candidate_id`/`dossier_hash`/`proposal_hash`/`evidence_id`/`client_order_id`/`parent_client_order_id` is non-string or empty; plan `proposal_hash` is present but non-string/empty; or no proposal hash exists in plan or envelope. No identity is ever stringified or fabricated from malformed data; no new schema keys, reason codes or persistence fields; no ticker/time fallback. Existing valid envelope-proposal-only intents (plan proposal absent, envelope present) remain attributable — verified by a dedicated positive-control test.

### TDD evidence — exact commands and observed results

All commands ran from `/opt/data/projects/tradey-desk/.worktrees/position-watchdog`.

```sh
# RED 1: regression required by review — one valid intent plus same-proposal intent with missing/None/empty/non-string client ID, either order
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_invalid_intent_client_ids_do_not_contaminate_valid_attribution -v
# RED observed: 1 method; 12 errors (TypeError at lineage.py:280 str/None and int/str sorts;
# unhashable list/dict at lineage.py:63) + 2 failures (empty-string '' leaked into
# decisions[0]['client_order_ids'] as ['', 'parent']). All expected-contamination failures.

# GREEN after guard
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage -q
# Ran 31 tests; OK

# RED 2: broader malformed-field sweep — proposal_hash, plan.proposal_hash, candidate_id, dossier_hash, evidence_id, parent_client_order_id, plan, each None/''/7/False/[]/{...}
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_malformed_intent_identity_fields_remain_unknown_without_graph_edges -v
# RED observed: 40 failures (invalid envelopes silently created conflicting/extra graph state,
# flipped coverage or changed positions/decisions) + 2 errors (AttributeError int.get at
# lineage.py:67; TypeError unhashable dict at lineage.py:68). All expected failures.

# GREEN after extended guard
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -q
# Ran 42 tests; OK

# RED 3: incomplete-intent identity pinning (client_order_id / plan.proposal_hash / plan each deleted alone) — must stay unknown, not fabricate identity
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage.LineageTests.test_incomplete_intent_alone_cannot_fabricate_order_identity test_watchdog_lineage.LineageTests.test_valid_envelope_proposal_without_plan_proposal_remains_attributable -v
# RED observed: incomplete variants failed (decisions kept stale/empty refs, coverage not unknown);
# envelope-proposal positive control failed (position no longer attributed). Expected failures.

# GREEN
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -q
# Ran 44 tests; OK
```

Final verification (after all edits):

```sh
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python -m unittest test_watchdog_lineage test_watchdog_forward_lineage -q
# Ran 44 tests in 0.448s; OK
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py fast
# TIER_RESULT fast tests=308 failures=0 errors=0 skipped=0
PYTHONPATH=.:tests uv run --with 'fastmcp<4' python tests/run_tests.py scenario
# TIER_RESULT scenario tests=162 failures=0 errors=0 skipped=0
git diff --check
# Clean.
python3 -m py_compile watchdog/lineage.py tests/test_watchdog_lineage.py
# Exit 0.
```

Both tier runners reported no `OPERATIONAL_ISOLATION_FAILURE`. The known fast fixture stdout line `BLOCKER dry_run_no_execution` remains disclosed and deferred; it is not a failed test. Full-only suite/release smoke not run, unchanged from prior rounds.

### Self-review, preservation and concerns

- Reviewed the full diff before the explicit-path commit: only intent pre-validation and tests changed; guard runs before `connect`, `proposal_links`, ambiguity checks, position creation and decision sorting, so no malformed value can reach graph nodes, hashable sets or `sorted()`.
- Valid attribution preserved: focused (44) and fast (308) suites include the two-ideas, separate-valid-proposals, dossier-only, exit-corroboration and real-persistence projection controls — all green. Decisions for candidates whose only intents are invalid show no fabricated client refs (`client_order_ids == []`).
- Incomplete evidence stays explicitly unknown: every excluded intent contributes `intent_lineage_unknown`, top-level coverage `unknown`; no rescue by candidate fields, ledger paths or ticker/time.
- Self-review initially extended the guard to require a proposal hash on every intent; the envelope-proposal positive control caught this overreach and the guard was narrowed to accept envelope-provided proposals (RED→GREEN documented above).
- **Concern: fresh parent scoped re-review is still required; this is not release approval.** Prior round's downstream concerns (unknown-coverage/delta handling by store/accounting, writer pause before deploy, deployment smoke) remain unchanged controller responsibilities.
