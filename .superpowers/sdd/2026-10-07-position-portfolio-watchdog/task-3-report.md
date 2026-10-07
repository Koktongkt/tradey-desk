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
