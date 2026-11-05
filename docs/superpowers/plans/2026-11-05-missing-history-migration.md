# Missing-History Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Durably represent the 78 proven-unrecoverable canonical rows (72 hashless review rows, 6 hashless filled BUY trade rows) as fail-closed `missing_history` policy records, and add conservative per-symbol blocking plus a reviewed per-symbol clearance path — without inventing any hash, association or authority, and without importing or activating anything on production.

**Architecture:** Extend the approved repair `2ddecea` as a strict superset: one new append-only record type (`missing_history`, optional `missing_history_clearance`) in the existing `private/opportunity_policy.jsonl` stream, one dedicated gap-source validator (separate from `_source_row` so binding sources can never name `trade_journal.jsonl`), one derived per-symbol block set, one decision check in `candidate_policy`, and the migration-validation scan extended from `REVIEWS_STREAM` to `MIGRATION_SOURCE_STREAMS`. Gap validation runs before the `HistoricalDossierHashMissing` raise; unreferenced gap-classified hashless rows always still raise.

**Tech Stack:** Existing Python application interpreter, stdlib `unittest`/`dataclasses`/`hashlib`, existing SQLite/JSONL ledger API. No new package, service, model call or network access; all synthetic tests run under the existing offline socket/urlopen guard.

**Spec:** `/home/hermes/.hermes/diagnostics/tradey-opportunity-activation-20261105/DESIGN-PROPOSAL-missing-history.md` (amended, approved 2026-11-05), as reviewed by `DESIGN-REVIEW.md` (findings I-1..I-4, M-1..M-5 resolved) and read against the approved base spec `docs/superpowers/specs/2026-11-04-opportunity-entry-policy-design.md` §7 and repair review `REPAIR-REVIEW.md`.

**Status:** PLAN FOR USER REVIEW. Implementation is not authorized by this document. No production import, apply, activation, digest production/approval, deployment, push, merge, broker call or network request is performed by any task in this plan.

## Global Constraints

- Fail-closed: every unreferenced gap-classified hashless row still raises `HistoricalDossierHashMissing`; a digest mismatch is a typed state-unavailable failure, never a skip.
- Gap sources use a dedicated allowlist `MIGRATION_SOURCE_STREAMS = (REVIEWS_STREAM, TRADE_JOURNAL_STREAM)`; the shared `_source_row` / `INDEX_STREAMS` boundary for binding sources is unchanged (DESIGN-REVIEW I-3).
- `issuer_evidence.symbol` is extractable only from a `symbol` key at **any depth** of the referenced row's own canonical bytes (user decision 2026-11-05). The 5 `proposal_hash` hint rows contain no `symbol` key anywhere and can never carry `issuer_evidence`.
- Only the 6 hashless filled **BUY** trade rows are gap-classified; the 6 hashless filled SELL rows are explicit non-blockers — asserted by test, never silently exempted.
- `unknown_history_blocks` is populated only from validated `issuer_evidence` (row's own bytes). Blocking **never grants BUY**, never creates an allowance, never proves dual approval, never qualifies `pre_submission_retryable`.
- Symbol matching for blocking is exact after `casefold()` + whitespace trim; no alias mapping, no exchange-suffix normalization. A non-matching string does not block (never grants).
- Clearance is **per-gap**; a symbol unblocks only when every gap naming it is bound to a specific dossier via reviewed evidence or individually cleared. Clearance needs its own approved manifest digest and reason `permanently_unattributable_user_acknowledged`.
- The legacy `proposal_hash` is recorded as a hint only and is asserted never to equal any canonical dossier hash at import (`hint_not_dossier`).
- Immutable hash→allowance links, replay idempotence (canonical dedupe), the approved-digest gate, and rollback-floor v0 semantics are unchanged. `missing_history`/clearance records are inert at v0; reader support and any activation must land together.
- Synthetic fixtures only for RED/GREEN; no real issuers, rows or digests in source or tests. Real canonical data is touched only by the Task 8 rehearsal on an authenticated **disposable copy** — production bytes/mtime/mode verified unchanged pre/post, no import/apply ever run.
- Production ROOT remains `7c81de800495acb8b2a6c7e5096128437307d785`, policy INACTIVE, throughout this plan.

## Explicitly out of scope

- **SEC retrieval workstream** (proposal §3.3 pipeline: retained-capture observations, bounded SEC GET batches, 197-URL inventory, 403 ladder): a **separate workstream** requiring its own design and independent review. Reference only; no task here fetches, scripts or plans retrieval. The 124 hashes are covered by the already-shipped 2ddecea `identity_resolution` mechanism fed by later manifests; the evidence pipeline is not built here.
- Any production import (`import_manifest`), `activate`, manifest digest production, or digest approval on the production root. Task 9 verifies the activation **gate checklist readiness** only; every gate item requiring user digest approval remains a separate future decision (proposal §7).
- Fabricating hashes/associations from today's cache or retrieved documents; altering recovery conclusions; changing review/broker semantics or the 2ddecea binding gate.
- Push, merge, deployment, canary, credential or dependency changes.

## Review Focus

1. **Partial index regression:** a root with one referenced and one unreferenced hashless row must still raise carrying the unreferenced row's exact ref (the exact 2ddecea regression risk) — Task 3, test T12.
2. **Invention gate:** an `issuer_evidence.symbol` absent from the referenced row's canonical bytes must fail import/state build — Task 3, test T9.
3. **Boundary widening:** a `missing_history` source naming a non-`MIGRATION_SOURCE_STREAMS` stream, or a row that has a `dossier_hash`, must fail; `_source_row` must still reject `trade_journal.jsonl` — Task 3, test T10; Task 2, test T2b.
4. **Rollback skew:** after code revert to `7c81de8`, the full policy stream (including previously imported unresolved records) must fail as a typed state-unavailable condition, never mistaken for corruption; v0 floor behavior unchanged — Task 7, test T7; Task 9 checklist.
5. **Over-broad clearance:** clearing one of two gaps naming the same symbol must keep the symbol blocked — Task 5, test T11.

## Files and conventions

- Modify `opportunity_state.py` (constants, `_policy_state`, `_build`, `OpportunityIndex`, `candidate_policy`, `audit`-facing fields), `opportunity_admin.py` (`validate_manifest` record validators, import conflict/assertion rules), `opportunity_activation.py` (`_KNOWN_RECORD_TYPES`), `sqlite_ledger.py` (add `trade_journal.jsonl` to the migration-validation snapshot inputs only).
- Tests extend `tests/test_opportunity_state.py`, `tests/test_opportunity_admin.py`, `tests/test_opportunity_activation.py`; synthetic fixtures extend `tests/opportunity_fixtures.py`.
- Verified execution convention: identical to the base plan (`P=/home/hermes/.local/share/tradey/venv-linux/bin/python`, `offline_test_guard`, `PYTHONDONTWRITEBYTECODE=1`, `HERMES_DISABLE_LAZY_INSTALLS=1`, `TRADEY_UNPATCHED_ROOT=...`, guarded `unit MODULE` helper). Run from this worktree only. Baseline before any edit: focused 38 / full 1,901 / raw 1,901, exit 0, zero skips.
- One writer at a time; tasks are strictly sequential (each consumes the previous task's interfaces). No parallel edits to `opportunity_state.py`.

### Task 0: Gap fixtures and unchanged baseline

**Files:** Modify `tests/opportunity_fixtures.py`, `tests/test_opportunity_state.py`; no production source change.

**Interfaces:**
- Produces fixture helpers consumed by Tasks 1–8:
  - `gap_review_row(*, with_symbol: bool, with_hint: bool, dossier_hash: str | None) -> dict` — a synthetic hashless legacy review row: `{evidence_id, reviews: [{decision, symbol?}, ...], timestamp}` (67-row shape, symbol nested at `reviews[i].symbol`), optional 64-hex `proposal_hash` hint variant (5-row shape, no symbol anywhere), or a `dossier_hash`-carrying control.
  - `gap_trade_row(*, action: str, status: str = 'filled') -> dict` — a synthetic hashless filled trade row (`action: 'BUY'|'SELL'`, top-level `symbol`, no identifier fields).
  - `make_gap_root(path, *, review_gaps: int, hint_rows: int, buy_gaps: int, sell_rows: int, bound_rows: int = 0) -> Path` — provisions a temporary root whose canonical streams contain exactly these shapes (fictional symbols only), via canonical writers.

- [ ] **Step 1: capture the unchanged baseline.** Focused + full + raw with isolation; expect 38/1901/1901, exit 0, zero skips, unchanged operational bytes. Record hashes as this plan's baseline evidence.
- [ ] **Step 2: write RED test** pinning current behavior as the seam contract:

```python
def test_hashless_buy_trade_row_is_not_yet_scanned(self):
    root = make_gap_root(self.tmp, review_gaps=0, buy_gaps=1, sell_rows=0)
    with self.assertRaisesRegex(HistoricalDossierHashMissing, 'historical_dossier_hash_missing'):
        load_index(root)          # today only REVIEWS_STREAM raises; BUY row unscanned
```

- [ ] **Step 3: run RED** (`unit test_opportunity_state`); expected failure is the missing scan behavior, not a setup error.
- [ ] **Step 4: commit** `test: add synthetic missing-history fixtures and baseline` (fixtures + test only; no source change in this task).

### Task 1: `missing_history` record type in the policy reader

**Files:** Modify `opportunity_state.py:_policy_state`, `opportunity_activation.py:_KNOWN_RECORD_TYPES`, `tests/test_opportunity_state.py`.

**Interfaces:**
- Consumes: Task 0 fixtures; existing `_KNOWN_RECORD_TYPES` / `_policy_state` schema discipline (`record_type`, `schema_version == 1`, `_valid_timestamp`).
- Produces (in `opportunity_state.py`):
  - `MISSING_HISTORY_KINDS = ('legacy_review_unlinked', 'filled_buy_unlinked')`
  - `MISSING_HISTORY_REASONS = ('recovery_exhausted_exact_link_unavailable',)`
  - `_KNOWN_RECORD_TYPES` gains `'missing_history'` (schema_version 1 only).

- [ ] **Step 1: write RED tests.** A structurally invalid `missing_history` row (bad `kind`, `reason` outside the fixed vocabulary, missing key, non-1 schema_version, malformed timestamp) raises `opportunity_policy_state_unavailable`; a well-formed row is accepted by the reader and sets no version/permission.

```python
def test_missing_history_bad_reason_fails_closed(self):
    rows = (missing_history_row(reason='invented_reason'),)
    with self.assertRaisesRegex(OpportunityStateError, 'opportunity_policy_state_unavailable'):
        _policy_state(rows, {}, {}, {}, {}, set(), {}, {}, {})
```

- [ ] **Step 2: run RED** (`unit test_opportunity_state test_opportunity_activation`) — unknown record type rejected today.
- [ ] **Step 3: implement** the vocabulary constants and add the record type to `_KNOWN_RECORD_TYPES` with kind/reason validation in `_policy_state` (row structure only; source/field validation is Task 2).
- [ ] **Step 4: verify GREEN** on both modules.
- [ ] **Step 5: commit** `feat: accept missing_history policy record type`.

### Task 2: Dedicated gap-source validator and row-bytes evidence

**Files:** Modify `opportunity_state.py`, `sqlite_ledger.py` (migration-validation snapshot inputs), `tests/test_opportunity_state.py`.

**Interfaces:**
- Consumes: `_source_row` digest/sequence discipline (opportunity_state.py:275–293) as the pattern — not widened.
- Produces (in `opportunity_state.py`):
  - `TRADE_JOURNAL_STREAM = 'trade_journal.jsonl'`; `MIGRATION_SOURCE_STREAMS = (REVIEWS_STREAM, TRADE_JOURNAL_STREAM)`.
  - `_gap_source_row(source, snapshot_rows: dict) -> dict` — exact `{stream, sequence, row_sha256}` key set, one-based sequence, stream ∈ `MIGRATION_SOURCE_STREAMS`, canonical UTF-8 (`ensure_ascii=False`) row digest recomputed on every call; mismatch raises the existing typed digest-mismatch error.
  - `extract_row_symbol(row) -> str | None` — first `symbol`-keyed value found at any depth of the row's JSON structure; returns None when absent.
  - `_validate_gap_record(row, snapshot_rows) -> dict` — full §3.1 validation: `kind` ∈ `MISSING_HISTORY_KINDS`; `source` via `_gap_source_row`; `observed_fields` exactly equal to the referenced row's key set; `issuer_evidence` either null or `{"symbol": S}` where `S == extract_row_symbol(referenced_row)` (fail otherwise); `hint` null or exactly `{"legacy_proposal_hash": <64hex>}`; `reason` ∈ vocabulary.
- `sqlite_ledger.py`: the read-only snapshot used for migration validation includes `trade_journal.jsonl` rows (read-only; decision code never consumes it beyond digest-checking gap references; it can never appear as a binding source).

- [ ] **Step 1: write RED tests.** Both streams: valid gap sources for a `REVIEWS_STREAM` row and a `trade_journal.jsonl` row validate; digest mutation on reload fails for both streams; `observed_fields` mismatch fails; `issuer_evidence` symbol not present in the row fails; a hint-row gap with non-null `issuer_evidence` fails; a source stream outside `MIGRATION_SOURCE_STREAMS` fails via the gap validator; `_source_row` still rejects a `trade_journal.jsonl` source (boundary unchanged).

```python
def test_gap_source_digest_mutation_fails_on_trade_journal(self):
    source = {'stream': 'trade_journal.jsonl', 'sequence': 3, 'row_sha256': mutated_digest}
    with self.assertRaisesRegex(OpportunityStateError, 'manifest_source_digest_mismatch'):
        _gap_source_row(source, snapshot_with_trade_rows)
```

- [ ] **Step 2: run RED.**
- [ ] **Step 3: implement** `_gap_source_row`, `extract_row_symbol`, `_validate_gap_record`, and the snapshot stream addition.
- [ ] **Step 4: verify GREEN** (`unit test_opportunity_state test_sqlite_ledger`); assert no write path gained access to trade_journal.
- [ ] **Step 5: commit** `feat: add fail-closed gap-source validator for migration records`.

### Task 3: Gap scan, tolerance-vs-raise ordering and blocker conversion

**Files:** Modify `opportunity_state.py:_build`/`OpportunityIndex`, `opportunity_admin.py:audit_history`, `tests/test_opportunity_state.py`.

**Interfaces:**
- Consumes: Task 2 validator; existing `missing_dossier_sequences` scan (opportunity_state.py:458–473) and `HistoricalDossierHashMissing` raise.
- Produces:
  - `OpportunityIndex.missing_history_gaps: tuple[dict, ...]` — one entry per exactly-referenced hashless gap row (`{'stream', 'sequence', 'row_sha256', 'kind', 'symbol_evidence': str | None}`); tolerance never creates a dossier→allowance map entry, never attaches to `allowance_reviews`, never grants or spends.
  - `_build` scans `MIGRATION_SOURCE_STREAMS`: hashless rows in `REVIEWS_STREAM` are gap-classified; in `trade_journal.jsonl` only hashless filled rows with `action == 'BUY'` are gap-classified. Every gap-classified hashless row must be exactly referenced by a validated `missing_history` record or be added to `missing_dossier_sequences` — then the existing raise fires (ordering: gap validation **before** the raise; no partial index). `audit_history` reports `missing_history_gaps` (count + exact references) alongside `incomplete_history_cases`.

- [ ] **Step 1: write RED tests** (the core contract, per proposal §6):
  - T1: no gap record → `HistoricalDossierHashMissing` persists; exact record → index builds, `missing_history_gaps` reported, no allowance/permission created, an *additional* unreferenced hashless row still blocks (mixed root, carrying the unreferenced row's exact ref) — T12.
  - T2: digest/field mutation of a gap source fails closed on reload, both streams.
  - T9: `issuer_evidence.symbol` absent from the row's bytes fails.
  - T10: gap record referencing a `dossier_hash`-carrying row, or a row in a non-migration stream, fails.
  - T13: the hashless filled SELL rows are neither required nor blockers: a root with SELL rows and zero gap records builds an index with empty `missing_history_gaps`; SELL rows never raise, never grant.
  - Gap-row audit counts and references match the fixture roots exactly.

```python
def test_mixed_root_still_raises_for_unreferenced_row(self):
    root = make_gap_root(self.tmp, review_gaps=1, buy_gaps=1, sell_rows=0)
    import_manifest(root, manifest_referencing_only_review_gap(),
                    approved_manifest_sha256=digest_of(manifest_referencing_only_review_gap()))
    with self.assertRaisesRegex(HistoricalDossierHashMissing, exact_ref_of_buy_row):
        load_index(root)
```

- [ ] **Step 2: run RED** (`unit test_opportunity_state test_opportunity_admin`).
- [ ] **Step 3: implement** the extended scan, classification rule, tolerance set, ordering invariant and audit reporting.
- [ ] **Step 4: verify GREEN** plus full existing state/admin suites (all 2ddecea tests pass unchanged).
- [ ] **Step 5: commit** `feat: extend migration validation to trade_journal gaps with tolerance ordering`.

### Task 4: Per-symbol conservative blocking (`unknown_history_blocks`)

**Files:** Modify `opportunity_state.py` (`_build`, `candidate_policy`), `tests/test_opportunity_state.py`.

**Interfaces:**
- Consumes: Task 3's `missing_history_gaps` with symbol evidence.
- Produces:
  - `OpportunityIndex.unknown_history_blocks: dict[str, tuple[dict, ...]]` — symbol (normalized: `casefold()`, whitespace-trimmed) → tuple of gap refs, built **only** from validated `issuer_evidence`.
  - One check in `candidate_policy`, after identity verification and before any eligible outcome: if the candidate's verified issuer symbol (same normalization) is in `unknown_history_blocks`, return `PolicyDecision('unknown', 'unknown_history_unreconciled', event_id, None)`.

- [ ] **Step 1: write RED tests** (T3): a symbol with an evidence gap returns `('unknown', 'unknown_history_unreconciled')`; the same event without a gap is unaffected; a non-matching (case/whitespace-variant beyond trim, alias, exchange-suffix) symbol string does **not** block; `missing_history` row count unchanged by decisions; blocking never grants/spends/qualifies retry (assert no allowance map entry, no dual-approval credit).

```python
def test_symbol_variant_does_not_block(self):
    result = candidate_policy(self.context_with_zs_gap, self.verified_zs_resolution,
                              symbol='ZS.F')
    self.assertNotEqual(result.reason, 'unknown_history_unreconciled')
```

- [ ] **Step 2: run RED.**
- [ ] **Step 3: implement** the derived set and the single decision check.
- [ ] **Step 4: verify GREEN** (`unit test_opportunity_state test_opportunity_radar`) — no eligible outcome reachable for a blocked symbol.
- [ ] **Step 5: commit** `feat: block re-entry for symbol-evidenced unknown-history gaps`.

### Task 5: Per-gap clearance record

**Files:** Modify `opportunity_state.py` (`_policy_state`, `_build`), `opportunity_activation.py:_KNOWN_RECORD_TYPES`, `tests/test_opportunity_state.py`.

**Interfaces:**
- Produces: record type `missing_history_clearance` (schema_version 1) with exact `gap_source` ref (validated by `_gap_source_row` against the **same** referenced row's bytes) and `clearance_reason` fixed vocabulary `('permanently_unattributable_user_acknowledged',)`. `unknown_history_blocks` is rebuilt from remaining uncleared gaps only; the underlying `missing_history` record is kept forever.

- [ ] **Step 1: write RED tests** (T11): two gaps naming one symbol, one cleared → symbol still blocked; both cleared → unblocked; clearance referencing a nonexistent/mismatched gap fails closed; clearance without an approved digest is refused at import.

```python
def test_partial_clearance_keeps_symbol_blocked(self):
    index = load_index(self.root_two_gaps_one_cleared)
    self.assertIn('aaa', index.unknown_history_blocks)
```

- [ ] **Step 2: run RED.**
- [ ] **Step 3: implement** the record type and per-gap rebuild.
- [ ] **Step 4: verify GREEN.**
- [ ] **Step 5: commit** `feat: add per-gap missing_history_clearance record`.

### Task 6: Import/validation wiring, idempotence and `hint_not_dossier`

**Files:** Modify `opportunity_admin.py` (`validate_manifest`, `import_manifest`), `tests/test_opportunity_admin.py`.

**Interfaces:**
- Consumes: Tasks 1–5 validators.
- Produces:
  - `_validated_missing_history_record(record, index) -> dict` and `_validated_clearance_record(record, index) -> dict` wired into `validate_manifest`.
  - Import rules: duplicate `missing_history` records referencing one row with any digest/field difference fail `missing_history_conflict`; identical replay is a no-op via the existing `_canonical` dedupe; `hint_not_dossier` assertion (hint `legacy_proposal_hash` ≠ any canonical dossier hash in the snapshot) at import; approved-digest gate unchanged.

- [ ] **Step 1: write RED tests** (T4, T5): hint hash equal to a dossier hash fails import; conflicting gap records fail; same-manifest replay appends nothing; approval digest mismatch refused; combined synthetic manifest (gaps + bindings + scopes) validates.

```python
def test_replay_of_same_approved_manifest_appends_nothing(self):
    before = policy_row_count(self.root)
    import_manifest(self.root, self.manifest, approved_manifest_sha256=self.digest)
    import_manifest(self.root, self.manifest, approved_manifest_sha256=self.digest)
    self.assertEqual(policy_row_count(self.root), before + len(self.manifest['records']))
```

- [ ] **Step 2: run RED.**
- [ ] **Step 3: implement** the two validators and import rules.
- [ ] **Step 4: verify GREEN** (`unit test_opportunity_admin test_opportunity_state`).
- [ ] **Step 5: commit** `feat: validate and import missing-history and clearance records`.

### Task 7: Combined coverage, floor and rollback-guard tests

**Files:** Extend `tests/test_opportunity_state.py`, `tests/test_opportunity_admin.py`, `tests/test_opportunity_activation.py`.

**Interfaces:** Consumes Tasks 1–6. Produces the synthetic proof of the §3.4/§3.5 invariants.

- [ ] **Step 1: write RED tests** (T6, T7):
  - Combined synthetic manifest (78-shaped gap set + 124-shaped unresolved-with-source set, zero invented scopes) yields `incomplete_history == ∅` and `validate_manifest(...)['valid'] is True` on a synthetic root.
  - Floor: v0 root containing `missing_history`/clearance records, no activation → `require_current_allowance` returns `legacy_policy_floor` eligible unchanged; blocking records are inert at v0.
  - Rollback guard: loading migrated policy rows with the pre-migration reader (`_KNOWN_RECORD_TYPES` without the new types) raises the typed `opportunity_policy_state_unavailable` over the **entire** stream — asserted exactly, so a post-revert condition is never mistaken for corruption.

```python
def test_pre_migration_reader_fails_typed_on_missing_history_stream(self):
    with self.assertRaisesRegex(OpportunityStateError, 'opportunity_policy_state_unavailable'):
        legacy_style_policy_state(self.migrated_rows)
```

- [ ] **Step 2: run RED** (`unit test_opportunity_state test_opportunity_admin test_opportunity_activation`).
- [ ] **Step 3: implement** any remaining wiring the combined cases expose (expected: none or minimal).
- [ ] **Step 4: verify GREEN.**
- [ ] **Step 5: commit** `test: prove combined migration coverage, v0 floor and rollback skew`.

### Task 8: Real-copy rehearsal on the disposable authenticated copy

**Files:** No source change. Private rehearsal receipts under the diagnostics directory (0600); nothing enters source or publishable fixtures.

**Interfaces:** Uses the retained `real-history-copy/` disposable copy and the existing INCOMPLETE proposal as input. Production root is never imported, applied to, or activated.

- [ ] **Step 1: verify copy isolation.** Authenticate the disposable copy state (readiness.json `rehearsal_copy_unchanged: true` basis) and record pre-state byte/mtime/mode maps; deny network and mutation entrypoints in the harness as in prior rehearsals.
- [ ] **Step 2: build the real migration manifest as an INCOMPLETE proposal**: 78 gap records from the audited canonical refs (67 nested-symbol review gaps, 5 hint-row gaps with `issuer_evidence: null`, 6 BUY trade gaps), 124 unresolved-with-source records, zero invented scopes. No approved digest is produced.
- [ ] **Step 3: validate.** With the contract implemented: `validate_manifest` on the copy returns **valid** for the gap+unresolved manifest while activation still fails `activation_incomplete_history` (unresolved, unscoped) — proving both the representation and the remaining gate. Record exact outcomes.
- [ ] **Step 4: verify production untouched.** Compare production bytes/mtime/mode pre/post (91-entry class probe as in prior receipts); assert equality. Digest all receipts; store 0600.
- [ ] **Step 5: commit** `docs: record real-copy migration rehearsal receipts` (receipts referenced, never real data in source).

### Task 9: Activation-gate checklist verification (final; no activation performed)

**Files:** Modify `docs/opportunity-entry-policy.md` (missing-history section: record types, blocking, clearance, rollback semantics); add `docs/superpowers/plans/2026-11-05-missing-history-migration.md` gate record (this file's checklist filled with evidence pointers). No production mutation.

**Interfaces:** Consumes Tasks 0–8 outputs. Produces the verified checklist state handed to the separately-authorized activation procedure.

- [ ] **Step 1: run the full verification battery.** Focused + full + raw on the final tree: exit 0, zero failures/errors/skips, full/raw counts equal, isolation checks pass, all 2ddecea tests unchanged.
- [ ] **Step 2: verify each gate item and record evidence** (all items must be checkable, none ticked by assertion alone):
  - 78 `missing_history` records constructible with exact refs, validated, no conflicts (Task 8 receipts).
  - Gap-source boundary separate from `_source_row`; trade_journal gaps validated before the raise (Tasks 2–3 tests).
  - 124 hashes: binding mechanism shipped by 2ddecea remains; coverage depends on the **separate retrieval workstream** and later reviewed manifests — recorded as open, not hidden.
  - `audit_history` on the disposable copy: blocked only by `activation_incomplete_history`, `incomplete_history_cases` nonempty exactly as expected pre-binding.
  - Synthetic RED/GREEN suite complete; 1,901+ baseline green.
  - Real-copy rehearsal receipts complete; production untouched.
  - Rollback rehearsal incl. v0 floor: code-revert path fixture-tested (Task 7 rollback guard) with the typed stream-unavailable outcome asserted.
  - **Not satisfied by this plan, deliberately:** real production audit pass, validated real manifest, user-approved canonical digests (gaps manifest, bindings/scopes manifests, any clearance manifests, final activation digest), independent implementation review. These remain separate user decisions per proposal §7.
- [ ] **Step 3: run RED→GREEN docs check** where behavior is documented (reason tokens, clearance semantics, rollback statement) and confirm the documented rollback = code revert to `7c81de8` + never import a manifest the old reader cannot parse.
- [ ] **Step 4: commit** `docs: document missing-history migration contract and activation gate`.
- [ ] **Step 5: stop.** Report the checklist state. No import, apply, activation, push, merge or deployment is executed by this plan.

## Self-review

- **Spec coverage:** §3.1 schema/validation → Tasks 1–3, 6; §3.2 blocking → Task 4; §3.4 clearance → Task 5; §3.5 invariants → Tasks 6–7 (+ unchanged-by-construction interfaces); §6 tests 1–13 mapped: 1→T3, 2→T2/T3, 3→T4, 4→T6, 5→T6, 6→T7, 7→T7, 8→T9, 9→T2/T3, 10→T3, 11→T5, 12→T3, 13→T3; real-copy rehearsal → Task 8; activation gate → Task 9. I-1 (any-depth symbol, hint rows null evidence) → Task 2; I-2 (scan/ordering/SELL non-blockers) → Task 3; I-3 (separate boundary) → Task 2; I-4 (T9/T10/T2-both-streams/T11/T12) → Tasks 2/3/5; M-1 per-gap clearance → Task 5; M-2 exact matching → Task 4; M-3 rollback assertion → Task 7; M-5 real key set in schema → Task 1 fixtures.
- **Out of scope honored:** retrieval workstream referenced only (Task 9 evidence note); no production import/activation/digest anywhere.
- **Dependency order:** strictly linear 0→9; one writer; each task's Interfaces block carries the exact names later tasks consume.

---
