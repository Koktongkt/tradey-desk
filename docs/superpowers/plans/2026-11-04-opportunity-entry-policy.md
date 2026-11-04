# Opportunity Identity and No-Add-On Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Stop repeated reviews of unchanged spent opportunities, continue Radar's existing shortlist, and prohibit new BUY entries for held/pending symbols without disrupting protection or reconciliation.

**Architecture:** Keep existing dossier/proposal hashes and durable trade history. Add trusted event resolution and a rebuildable local allowance index over the existing ledger, plus one shared BUY-state evaluator using existing broker reads. Introduce a tested compatibility-floor guard before activation so rollback cannot silently restore permissive new entries.

**Tech Stack:** Existing Python application interpreter, stdlib dataclasses/Decimal/hashlib/HTMLParser/sqlite3/unittest, existing transactional SQLite/JSONL ledger and broker adapter. No new package, service, provider, embedding or model call.

**Spec:** `docs/superpowers/specs/2026-11-04-opportunity-entry-policy-design.md`, approved in chat; local design commit `4161ba9ec8be38c8dc331462aec00432789d7b8a` on runtime base `67d372f8099fb05fab33b9fc537eaa986abb2f95`.

**Status:** PLAN FOR USER REVIEW. Runtime implementation and execution method have not yet been approved. Design/plan commits stay local; live activation, publication and production promotion require separate authorization.

## Global Constraints

- Paper mode only; no add-ons. A new day, event, dossier, setup label, low market value or unused position headroom cannot override positive shares or unresolved entry obligations.
- Preserve existing $500 position cap, $10,000 account cap, three daily submissions including pending/unknown, three qualified pending parents, planned-risk/source/earnings/quote gates, attached protection and dual independent approval.
- Preserve current providers, model choices, cadence, phase/absolute deadlines, candidate cap and broker call budgets. Do not add Radar broker polling, rediscovery, a sixth candidate or deadline reset.
- Entry evidence: maximum age from read start **120 seconds**, maximum monotonic read duration **120 seconds**; reject future/naive/missing timestamps. Quote freshness remains separately enforced.
- Unknown event identity cannot authorize paid review/BUY; state corruption is a typed failure, not an empty registry. No automatic semantic-materiality detector or free-text-to-condition conversion.
- Reopening requires explicit evidence-backed approval or a previously approved deterministic condition; no default conditions. Each grant is one-shot and history is append-only.
- Keep lifecycle, expiry, protective SELLs, reconciliation, exact fill ownership and original pending-parent continuation ahead of new-entry policy decisions. Never auto-adopt broker holdings.
- Use canonical read-only storage APIs for observations; no importer, schema initializer or projection repair from Radar. Live source/data and schedules remain untouched during development.
- Keep real issuers, historical review/trade details, source-row identifiers and bootstrap manifests outside publishable source/tests. Public fixtures are explicitly synthetic.
- Existing exact-dossier safe retry remains unchanged and is overridden by held/pending exclusion. Do not broaden timestamp-based reuse or autotrader latest-candidate consumption incidentally.
- No deployment/activation or order canary in the ordinary test suite; no Hermes edits, gateway restart, dependency install or new credentials.

## Review Focus

1. A changed URL/representation digest in a mutable earnings release must not create a fresh allowance; test in Task 1 and Task 3.
2. Current-attempt dual approval must remain able to submit its own exact proposal, while the same approval cannot authorize another dossier; test in Task 2 and Task 6.
3. Absent legacy policy state, a lagging projection or an unavailable storage lock must not mean fresh/unspent; test in Task 0, Task 2 and Task 7.
4. A pending fill during non-atomic broker reads must not be misrepresented as flat after exact-parent refresh; test in Task 4 and Task 6.
5. Source-only rollback after activation must stop new entries without suppressing protective reconciliation; test in Task 0 and Task 7.

## Files and interface conventions

New runtime responsibilities:
- `opportunity_activation.py`: minimal version/activation guard retained in the rollback floor.
- `opportunity_identity.py`: pure, receipt-grounded issuer/document/event resolution and trusted observations.
- `opportunity_state.py`: coherent history index, allowance decisions, current-attempt authorization and deterministic condition evaluation.
- `opportunity_admin.py`: local-only audit, reviewed-manifest import, explicit reopening and activation commands; not exposed to discovery/reviewer subprocesses.
- `entry_eligibility.py`: strict positions and broker-observation/BUY eligibility, independent of economic sizing.

Existing integration: `sqlite_ledger.py`, `alpha_radar.py`, `broker_mcp_bridge.py`, `autotrader.py`, `run_cycle.py`; existing `candidate_retry`, `pending_policy`, earnings spending and reconciliation remain authoritative for their current jobs. Register each new `test_*.py` exactly once in `tests/test_manifest.json`. Shared synthetic support lives in `tests/opportunity_fixtures.py`, not a new testing framework.

Types below are frozen dataclasses; collection fields use tuples or defensive copies. Untrusted candidate/model dictionaries never become trusted types merely by matching their JSON shape. All digest inputs are canonical, versioned and finite. Validate identifiers before deriving canonical side keys; preserve original source identifiers/URLs.

## Verified execution convention

Run from the isolated design/implementation worktree, never the live root. At execution start confirm branch/path/HEAD and obtain fresh approval if source has diverged from the spec base. Reuse the previously verified application environment without resolving packages:

The representative unittest methods below are the named initial regressions, not complete fixture transcripts. Their Case `setUp` uses a TemporaryDirectory, explicit aware clock and the state/transport cases specified in its own Step 1; no ambient production roots or undefined production API are implied. Additional matrix rows belong in labeled subtests with fresh mutable state.

```bash
P=/home/hermes/.local/share/tradey/venv-linux/bin/python
export PYTHONDONTWRITEBYTECODE=1 HERMES_DISABLE_LAZY_INSTALLS=1
export TRADEY_UNPATCHED_ROOT=/home/hermes/apps/hermes/projects/tradey-desk/test_artifacts/focused-coverage-25/task6-unpatched-runtime
export PYTHONPATH=/home/hermes/.local/share/tradey/venv-linux/lib/python3.14/site-packages:/home/hermes/.hermes/hermes-agent:/home/hermes/.hermes/installs/019d0d114d22b7e6/environments/a63fde7d80404a4597f0bc0e914a8f74/venv/lib/python3.14/site-packages
unit() { "$P" -c 'import sys;sys.path.insert(0,"tests");import offline_test_guard as g;g.install();import unittest;unittest.main(module=None,argv=["tests","-v",*sys.argv[1:]])' "$@"; }
```

`unit MODULE` below means that exact guarded helper with bare module names. Preserve first RED logs, final GREEN logs, interpreter/dependency origins and source hashes in private external evidence. Inventory/copy hash-verified ignored immutable fixtures and create required ignored artifact parents before the unchanged baseline. Run canonical full and guarded raw discovery on unchanged runtime first; previously observed baseline is 1,671, not a promised current result or final feature count. All dates in new unit/scenario fixtures are explicit aware clocks, not the real day.

---

### Task 0: Activation compatibility floor and unchanged baseline

**Files:** Create `opportunity_activation.py`, `tests/test_opportunity_activation.py`; modify `sqlite_ledger.py:DEFAULT_STREAMS`, `autotrader.py:_run_locked`, test manifest. Create external evidence/fixture manifests only; no operational activation.

**Interfaces:**
- Produces `POLICY_STREAM = "private/opportunity_policy.jsonl"` and `SUPPORTED_POLICY_VERSION = 0` in the floor.
- `activation_version(root: Path) -> int`: strict read-only inspection of activation records; absent stream and no activation => 0. Unreadable/corrupt state raises `ActivationStateError`; unknown positive versions are returned, not ignored.
- `require_supported_activation(root: Path, *, supported: int) -> None`: raises `ActivationStateError("opportunity_policy_version_unsupported")` when active version exceeds support. Feature integration later declares support 1; floor retains support 0.

- [ ] **Step 1 — capture baseline and write RED tests.** Authenticate source/fixture hashes and execute unchanged full/raw with isolation before edits. Tests pin: no activation permits legacy mode; version 1 denies floor entry; malformed activation/unknown record schema/read failure blocks rather than returning zero; lifecycle executes before the new-entry guard. Use existing temporary-root trading fixtures with all normal gates valid so an old unguarded run reaches the mocked reviewer, proving the negative control is not a setup failure.

```python
def test_floor_denies_activated_v1(self):
    with self.assertRaisesRegex(ActivationStateError, "opportunity_policy_version_unsupported"):
        require_supported_activation(self.root_with_active_v1, supported=0)
```
- [ ] **Step 2 — run RED.** `unit test_opportunity_activation`; preserve missing-feature/explicit unexpected-review assertion failures, zero real broker/model attempts.
- [ ] **Step 3 — implement the minimal floor.** Add the private stream to the canonical registry, read activation with the existing non-repairing reader, and guard normal new entry after existing reconciliation/exit handling but before candidate/snapshot/review. Activation records use `record_type="activation", schema_version=1, policy_version:int, manifest_sha256:str, timestamp:aware UTC`. No deactivation/reset command. No activation record is written by imports or tests outside their temporary roots.
- [ ] **Step 4 — verify GREEN.** `unit test_opportunity_activation test_managed_reconciliation test_pipeline`; canonical `fast`, `scenario`, `full` and guarded raw must be green with unchanged operational bytes/metadata. Pin the exact clean floor tree for later rollback rehearsal. No old trade behavior changes while inactive except fail-closed malformed policy state.
- [ ] **Step 5 — commit/review gate.** Commit only owned floor changes as `feat: add fail-closed opportunity activation compatibility guard`; record this SHA as `COMPATIBILITY_FLOOR` in private evidence. Review its independent protection/entry behavior before Task 1. Never choose pre-floor `67d372f` as post-activation rollback target.

### Task 1: Trusted issuer, document and event resolution

**Files:** Create `opportunity_identity.py`, `tests/test_opportunity_identity.py`, `tests/opportunity_fixtures.py`; modify trusted acquisition/receipt seams `alpha_radar.py:289–314,2103–2181` only to preserve needed provenance, and manifest.

**Interfaces:**
- `IssuerBinding(symbol:str, cik:str, legal_name:str, support_ref:str)`; `DocumentObservation(document_id:str, url:str, returned_url:str, content_sha256:str, publication_value:str, precision:str, retained_ref:str)`.
- `EventResolution(status:str, event_id:str|None, issuer:IssuerBinding|None, family:str|None, period:str|None, documents:tuple[DocumentObservation,...], support_refs:tuple[str,...], reason:str)`; statuses exactly `verified`, `unknown`, `conflict`.
- `resolve_event(symbol: str, pages: list[dict], *, known_resolutions: tuple[dict,...]) -> EventResolution` is pure and does no fetching. `candidate_identity(resolution: EventResolution) -> dict` emits only trusted versioned public-to-private lineage fields; no raw article text.
- `retain_observations(root:Path, resolution:EventResolution, pages:list[dict]) -> EventResolution` persists each validated bounded representation once at `private/opportunity_evidence/<canonical_capture_sha256>.json`, returning immutable receipt references without changing event identity. Use existing capture size limits; private 0700/0600 ownership, no links/overwrites with different bytes, staged atomic write and fsync before ledger references. Fail durable intake if persistence fails. Models cannot choose paths or supply trusted captures. Lookup/index decisions remain read-only; these immutable acquisition blobs are not a second decision database or copies of articles in multiple streams.
- Synthetic support: `earnings_pages(*, period="2026-Q3", representation="original") -> list[dict]` builds complete synthetic retained pages using existing trusted retention helpers; `make_root(path:Path, *, active:bool=False) -> Path` provisions only temporary ledgers/config through canonical writers. Bindings use a fictional issuer and never real incident identifiers.

- [ ] **Step 1 — write RED tests.** Same report/known alias with changed prose/title/research timestamp/price/source order/extra secondary article gives equal event IDs; different verified reporting period differs; malformed identifier fails, not repaired. Same accession with distinct event subjects conflicts unless explicitly resolved. Mutable URL/content change does not authorize a new event. Publication day/next earnings/exit date alone cannot identify the report. Model-supplied `event_id`/CIK and unsupported retained captures cannot establish authority.

```python
def test_changed_representation_does_not_change_report_identity(self):
    a = resolve_event("ACME", earnings_pages(), known_resolutions=())
    b = resolve_event("ACME", earnings_pages(representation="changed"), known_resolutions=())
    self.assertEqual((a.status, b.status), ("verified", "verified"))
    self.assertEqual(a.event_id, b.event_id)
```
- [ ] **Step 2 — run RED.** `unit test_opportunity_identity`; retain nonzero tests and expected missing resolver/equality failures.
- [ ] **Step 3 — implement resolver v1.** Validate retained representations and receipt digests via existing helpers. For new automated earnings binding, parse exact Inline XBRL `dei:TradingSymbol`, `dei:EntityCentralIndexKey`, `dei:EntityRegistrantName` from complete trusted SEC cover content; symbol/CIK must agree with the filing locator. Accept explicit previously reviewed issuer/document bindings when cover fields are absent; do not perform an extra SEC lookup or infer from a model ticker. Accept reporting period only from a complete primary source's exact quarter/year or period-end support bound to the matched issuer/release relationship; collect all matches and reject ambiguity/conflict. Registry-approved document/period relationships handle historical missing markup; unsupported event families remain unknown. Canonical event descriptor uses version + issuer CIK + family + supported reporting period/release relationship, not observation membership. A new primary locator alone cannot create an allowance. Keep original URL and precision plus exact retained support references; do not reconstruct missing historic content from a current cache.
- [ ] **Step 4 — verify GREEN.** `unit test_opportunity_identity test_alpha_radar test_publication_observation test_publication_integration`. Add synthetic multi-item filing, wrong issuer, conflicting period and incomplete-representation rows. Existing source verification still rejects the same bad citations; no network/model calls added.
- [ ] **Step 5 — commit/review gate.** `feat: resolve stable opportunity identity from trusted evidence`; review parser support, alias collision and unknown-coverage behavior before consumers use it.

### Task 2: Coherent read-only history and allowance index

**Files:** Modify `sqlite_ledger.py` read-only API; create `opportunity_state.py`, `tests/test_opportunity_state.py`; extend `tests/test_sqlite_ledger.py` and manifest.

**Interfaces:**
- In `sqlite_ledger.py`, `LedgerSnapshot(root:Path, rows:dict[str,tuple[dict,...]], watermark:tuple[tuple[str,int,str],...])` and `read_stream_snapshot_readonly(root:Path, streams:tuple[str,...]) -> LedgerSnapshot`.
- In `opportunity_state.py`, `OpportunityStateError`, `PolicyDecision(outcome:str, reason:str, event_id:str|None, allowance_id:str|None)`; outcomes `eligible`, `skip`, `unknown`, `reopening_pending`. The last is research-only/provisional: it may permit persistence and the existing broker precheck, never paid review or submission.
- Shared state types: `ConditionObservation(event_id:str, metric:str, value:Decimal, units:str, source_kind:str, observed_at:datetime, evidence_ref:str, seal:object)` and `ReopeningClaim(condition_id:str, prior_allowance_id:str, observation:ConditionObservation, seal:object)`. Task 3 adds the trusted factories/condition validation; unsealed or unsupported claims never authorize anything.
- `OpportunityIndex(snapshot:LedgerSnapshot, activated_version:int, resolutions:dict[str,EventResolution], document_aliases:dict[str,str], dossier_allowances:dict[str,str], allowance_reviews:dict[str,tuple[dict,...]], grants:dict[str,dict], conditions:dict[str,dict], unresolved_dossiers:frozenset[str])` owns validated state; internal maps are not model input.
- `load_index(root:Path) -> OpportunityIndex`; `event_decision(index:OpportunityIndex, resolution:EventResolution, *, dossier_hash:str|None=None, current_attempt:AttemptAuthorization|None=None, reopening_claim:ReopeningClaim|None=None) -> PolicyDecision`.
- `AttemptAuthorization(dossier_hash:str, proposal_hash:str, evidence_id:str, allowance_id:str, seal:object)`; `authorize_current_attempt(index:OpportunityIndex, *, dossier_hash:str, proposal_hash:str, evidence_id:str) -> AttemptAuthorization` validates exact persisted dual approval and current grant, not a caller-provided approval boolean.
- Initial allowance ID is a canonical digest of resolver version/event ID/initial generation; a linked explicit grant supplies later generations. Existing completed reviews, not a second spending cache, are authoritative.
- Extend existing `candidate_retry.pre_submission_retryable(dossier_hash, reviews, ledger_path, *, ledger_rows:list[dict]|None=None) -> bool`: supplied rows come only from the coherent canonical index and undergo the unchanged exact proof; without supplied rows retain the existing reader contract. Radar passes preloaded rows instead of invoking an ordinary schema/import-capable reader inside a policy lookup. Do not create a weaker parallel retry algorithm.

- [ ] **Step 1 — write RED tests.** A complete HOLD/disagreement spends regenerated dossiers; later markers or approval cannot erase it. Current exact dual approval authorizes only its own proposal; another dossier cannot borrow it. Empty review/reconciliation-only output does not spend an untouched allowance. Unknown identity, corrupt/lagging projection, missing active-history binding and wrong-root snapshot cannot mean eligible. Crash after review append before rebuilding the index still spends the event.

```python
def test_new_dossier_cannot_erase_same_event_hold(self):
    result = event_decision(self.index_with_completed_hold, self.same_event,
                            dossier_hash=self.regenerated_dossier_hash)
    self.assertEqual((result.outcome, result.reason), ("skip", "unchanged_opportunity"))
```
- [ ] **Step 2 — run RED.** `unit test_opportunity_state test_sqlite_ledger`; expected missing APIs/policy assertion failures, not production imports or accesses.
- [ ] **Step 3 — implement consistent observation.** Under the existing storage/projection lock order, use one read-only immutable SQLite view after canonical recovery/schema/integrity/projection validation. Reuse existing canonical validators; refactor their shared internals rather than call schema-initializing `_connect`. Existing lock absent => typed state unavailable; do not create private parents/locks from this new observer. Clean temporary fixture creation is a separate canonical writer step. Cover custom registered streams, absent projections and `test_artifacts` root selection. Build dictionaries once per coherent view; watermark each required stream with sequence and canonical digest. Before safety decisions, reload if relevant watermarks changed. Preserve all old exact-dossier age/retry conditions; this index is an additional event policy, not a reason to broaden reuse.
- [ ] **Step 4 — verify GREEN.** `unit test_opportunity_state test_sqlite_ledger test_bridge_and_reuse test_blocker_diagnostics test_autotrader_reconciliation`. Prove no attempted SQLite writes/import/repair; run both missing-database and migrated-database fixtures. An absent unactivated policy stream is not automatically permission when reviewed historical candidates need binding. No optional on-disk performance index in v1.
- [ ] **Step 5 — commit/review gate.** `feat: enforce event review allowances from coherent durable history`; review exact-current-attempt exemption, historical dissent and crash behavior.

### Task 3: Explicit resolution/reopening and reviewed activation manifests

**Files:** Create `opportunity_admin.py`, `tests/test_opportunity_admin.py`; extend `opportunity_state.py` and manifest. Public fixtures contain no real ledger rows.

**Interfaces:**
- `audit_history(root:Path) -> dict`: read-only, returns version/base watermarks, proposed bindings and unresolved cases without guessing.
- `validate_manifest(root:Path, manifest:dict) -> dict`: verifies exact source sequences/digests, resolver versions, supported evidence/aliases and absence of hidden resets. Writes nothing.
- `import_manifest(root:Path, manifest:dict, *, approved_manifest_sha256:str) -> dict`: idempotent canonical append under `entry_state.lock`; requires caller's explicit reviewed digest, never an inferred approval from source/model text.
- `grant_reopening(root:Path, approval:dict, *, approved_manifest_sha256:str) -> str`; `activate(root:Path, manifest:dict, *, approved_manifest_sha256:str) -> dict`. Neither changes old trades/reviews. Callers must have explicit human approval; no agent auto-approval, discovery/reviewer tool exposure or default CLI mutation.
- `Condition(condition_id:str, event_id:str, allowance_id:str, metric:str, operator:str, threshold:str, units:str, source_kind:str, expires_at:str, observation_max_age_seconds:int, baseline_ref:str)`; reuse Task 2's `ConditionObservation` and `ReopeningClaim` types.
- `observe_completed_close(adapter_result:dict, *, event_id:str, evidence_ref:str) -> ConditionObservation` is a trusted acquisition factory, called only on the existing synchronized-price adapter result. `evaluate_condition(condition:Condition, observation:ConditionObservation, *, now:datetime) -> bool` rejects raw dictionaries/unsealed observations. Durable reconstruction must verify its canonical candidate/observation lineage through the index, not accept model-authored observation fields.
- `make_reopening_claim(index:OpportunityIndex, resolution:EventResolution, observation:ConditionObservation, *, now:datetime) -> ReopeningClaim|None`; `serialize_reopening_claim(claim:ReopeningClaim) -> dict`; `restore_reopening_claim(index:OpportunityIndex, dossier_hash:str, *, now:datetime) -> ReopeningClaim`; `commit_reopening_claim(root:Path, claim:ReopeningClaim, *, dossier_hash:str, now:datetime) -> str`. Provisional claims are serialized only from sealed server-created observations before candidate hashing; restoration requires that exact canonical candidate/observation lineage and a currently approved, fresh, unconsumed condition. Commit revalidates under the entry lock and returns the one-shot durable allowance ID. No serialization field itself grants authority.

- [ ] **Step 1 — write RED tests.** Exact reviewed manifest imports once; changed source row/digest/alias, unsupported version and missing approval digest fail. Activation requires reviewed history coverage and preserves earliest dissent. Changed page/new headline cannot grant reopening. One approved condition consumes only once; stale/wrong-unit/wrong-event/future observations and replay deny. Inspection/audit never writes. Approval authorization cannot be created from a model/candidate `approved=true` field.

```python
def test_model_json_cannot_satisfy_approved_condition(self):
    self.assertFalse(evaluate_condition(self.approved_condition,
        {"metric": "completed_close_usd", "value": "1", "approved": True}, now=self.now))
```
- [ ] **Step 2 — run RED.** `unit test_opportunity_admin`; require missing functions/incorrect allowance behavior, nonzero test count.
- [ ] **Step 3 — implement local administrative boundary.** CLI subcommands: `audit` and `validate` default read-only; `import`, `reopen`, `activate` require `--manifest FILE --approved-sha256 DIGEST --apply`. The execution agent must first show the manifest/digest and obtain the explicit authorization required by the spec; flags are integrity binding, not cryptographic proof of human consent. Manifests use the existing canonical JSON encoding (sorted keys, compact separators, finite values, UTF-8, no trailing newline); `audit --out FILE` writes that exact 0600 artifact. CLI verifies both raw artifact digest and parsed canonical digest against the approval before mutation; API functions verify the same canonical digest. Preserve all mutations through existing canonical append and lock order. Supported record types: `identity_resolution`, `document_alias`, `reopen_grant`, `condition_approval`, `activation`; strict schema/version validation. A `reopen_grant` holds its authorization/condition consumption in one durable record, derived idempotently from prior allowance + approval/condition ID + verified observation. No separate consume/grant pair or reset/deactivation command. Initial automatic condition adapter supports only approved `completed_close_usd`, exact source `massive_consolidated_completed_daily`, units `USD`, operator `<=` or `>=`, finite positive Decimal threshold; it uses the trusted enrichment observation, never candidate/model price fields. Observation age uses the adapter's original `market_prices_at` aggregate timestamp, not retrieval time or an invented close instant. Other metrics/sources remain unsatisfied. No initial/default approvals or conditions. A source change without explicit approved grant remains spent.
- [ ] **Step 4 — verify GREEN.** `unit test_opportunity_admin test_opportunity_state`; simulate lost append acknowledgement and resume/replay, explicit approval versus attempted auto-approval, empty or partial historical manifests, expiry equality and one-shot generations. A satisfied condition can produce `reopening_pending` research, survive trusted persistence, then commit once under the entry lock; it cannot deadlock behind its own spent-event gate or authorize reviews before commit. Forged/expired claims, altered observation lineage and replay fail closed. Separate unresolved historical cases explicitly; never fabricate receipt hashes or overwrite source rows.
- [ ] **Step 5 — commit/review gate.** `feat: add auditable opportunity resolution and reopening controls`; review all mutation entry points and activation/rollback semantics. Do not run mutation commands against live state.

### Task 4: Strict broker position observations and shared BUY evaluator

**Files:** Create `entry_eligibility.py`, `tests/test_entry_eligibility.py`; modify `broker_mcp_bridge.py:43–54,221–314`, `autotrader.py:BROKER_FIELDS/authoritative_bundle`, `tests/test_broker_bridge.py`, coherent synthetic snapshot fixtures and manifest. Keep portfolio/dashboard projection behavior outside new-entry authorization unchanged.

**Interfaces:**
- `EntryStateError`; `EntryDecision(outcome:str, reason:str)` with `eligible`, `held`, `pending`, `unknown`.
- `strict_positions(normalized:object) -> list[dict]`: only the explicit successful normalized list is valid, retaining original supported row values; malformed data never becomes `[]`.
- `entry_observation(*, started_at:datetime, finished_at:datetime, duration_seconds:float, positions:list[dict], open_orders:list[dict]) -> dict` emits version 1, aware UTC times, duration, completeness flags and canonical row digests after trusted acquisition validation.
- `evaluate_buy(symbol:str, snapshot:dict, *, pending_proof:pending_policy.Proof|None, now:datetime, max_age_seconds:int=120, max_read_seconds:int=120) -> EntryDecision`.
- `local_entry_exclusions(index:OpportunityIndex) -> frozenset[str]` uses exact durable lineage and baseline exclusions only; absence is not broker authorization.

- [ ] **Step 1 — write RED tests.** Held 16 shares, held fractional dust, missing/zero market value and below-cap holdings all block. Properly empty complete positions/no obligation is eligible. Missing/error/non-envelope dict positions, bool/null/empty/NaN/infinite/negative/zero quantities, duplicates and unsupported sides fail closed. Valid positive numeric strings work. Exactly 120-second age/read duration passes; above 120, future, naive and missing times fail even with a fresh quote. Existing same-symbol pending, partial and submission-unknown block; other-symbol qualified capacity/protective SELL children retain old semantics.

```python
def test_positive_shares_block_even_when_market_value_is_zero(self):
    result = evaluate_buy("ACME", self.valid_snapshot_with_held_shares,
        pending_proof=self.snapshot_bound_pending_proof, now=self.now)
    self.assertEqual((result.outcome, result.reason), ("held", "position_already_held"))
```
- [ ] **Step 2 — run RED.** `unit test_entry_eligibility test_broker_bridge`; observe old malformed-to-empty or held-headroom permission failure in a non-vacuous direct boundary test.
- [ ] **Step 3 — implement the broker-owned observation.** Normalize `get_all_positions` strictly for security and non-security transport paths after existing `unwrap`; do not add accepted arbitrary error wrappers. Measure start/end and monotonic duration around existing snapshot/review reads, including their actual read window; keep request counts/order/concurrency unchanged. Generate `entry_observation` only in the trusted bridge and include it in broker-owned field rebinding. Validate all position rows, normalized symbols and explicit `side="long"`; reject unsupported shorts/zero rows, do not net quantities. Call the existing pending qualifier/proof validator rather than rescan order names as weaker authority. A missing/mismatched proof never authorizes entry. Keep original broker fields unchanged for all other consumers.
- [ ] **Step 4 — verify GREEN.** `unit test_entry_eligibility test_broker_bridge test_pending_capacity test_managed_reconciliation`; characterize actual supported envelope fixtures before rejecting shapes. Confirm same mock call budget, original readback ordering and funding reservation semantics. Add split-read fill and stale-positions/fresh-exact-parent tests; repeat qualification over old positions must not pretend to refresh the portfolio.
- [ ] **Step 5 — commit/review gate.** `feat: reject held or uncertain BUY state with bounded broker evidence`; review completeness/side contracts and fixture updates for genuine behavior, not weakened assertions.

### Task 5: Radar shortlist, intake, reuse/fallback and truthful outcomes

**Files:** Modify `alpha_radar.py` acquisition/loop/intake/persistence/reuse seams and `run_cycle.py:124–213`; add `tests/test_opportunity_radar.py`, extend affected source/reuse/cycle tests and manifest. Do not redesign discovery lanes or enable another discovery version.

**Interfaces:**
- `PolicyContext(root:Path, index:OpportunityIndex, known_exclusions:frozenset[str])` in `opportunity_state.py`; `load_policy_context(root:Path) -> PolicyContext` and `refresh_policy_context(context:PolicyContext) -> PolicyContext`.
- `candidate_policy(context:PolicyContext, resolution:EventResolution, *, symbol:str, dossier_hash:str|None=None, reopening_claim:ReopeningClaim|None=None) -> PolicyDecision` combines event disposition and positive local exclusion facts; no broker polling. A valid `reopening_pending` result can persist research with trusted claim metadata but is never an execution authorization.
- Candidate persistence adds trusted `opportunity_identity` and matched observation references before the existing dossier hash. Untrusted identity fields are stripped/rebound before use.
- Healthy exhaustion exact output: `DECISION skipped no_new_eligible_opportunity`; candidate reasons remain `unchanged_opportunity`, `opportunity_identity_unknown`, `opportunity_identity_conflict`, `position_already_held`, `same_symbol_pending_entry`. Storage/transport/timeouts remain separate typed failures.

- [ ] **Step 1 — write RED tests.** Spent/held first lead is skipped and a genuinely eligible second lead is synthesized/intaken; no synthesis for a proven repeat. Mutable URL or mixed old/new bundle is not prematurely discarded. Identity unresolved after allowed retrieval continues shortlist. All-policy-skipped returns the exact normal result without an uninitialized local; genuine scout/source failure is not relabeled healthy. Test both discovery configurations, reranking/rescue, direct intake, reuse, fresh helper and error fallback. Wrong-root/corrupt context cannot become eligible in an exception handler.

```python
def test_spent_first_lead_advances_to_second_without_extra_discovery(self):
    result = alpha_radar.live_research(self.cfg, intake=self.real_temporary_intake)
    self.assertEqual(result["symbol"], "NEXT")
    self.assertEqual(self.synthesized_symbols, ["NEXT"])
    self.assertEqual(self.discovery_calls, 1)
```
- [ ] **Step 2 — run RED.** `unit test_opportunity_radar`; include an old-runtime control demonstrating the repeated first candidate previously won, not an invalid second-candidate fixture.
- [ ] **Step 3 — integrate shared decisions.** One read-only context at run start, cheap proved exclusions before focused work, grounded resolution before synthesis when possible, shared intake gate and watermark refresh before append. Permit only existing bounded retrieval to resolve unknown/mutable observations. When an approved condition needs trusted completed-close evidence, do not grant an early skip or permission from stale data; use existing bounded enrichment, evaluate the condition, and leave grant consumption to the entry-locked administrator/consumer path. Retain original candidate/deadline accounting; a pre-synthesis cheap skip starts no expensive attempt, and a late skip does not refund consumed time/attempts. Keep existing exact-dossier freshness/retry rules and root-scoped reuse; filter both normal and error fallback. Preserve receipt/observation refs instead of dropping authority before identity is durably bound. Extend `run_cycle` audit and notice for the exact healthy-exhaustion token; no success label for storage or provider errors.
- [ ] **Step 4 — verify GREEN.** `unit test_opportunity_radar test_alpha_radar test_focused_reuse test_pipeline test_cycle`. Assert no sixth candidate/extra discovery/budget refill, same transport/model call ceilings, no canonical operational writes in any fixture path, and policy reasons with no private IDs in public output. Strip model-authored condition/identity metadata before rebinding trusted adapter observations; a later verification timestamp must not refresh a stale aggregate observation.
- [ ] **Step 5 — commit/review gate.** `feat: advance Radar past spent and already-owned opportunities`; review every producer/reuse/fallback route and counter/clock evidence.

### Task 6: Entry-locked execution enforcement and own-approval binding

**Files:** Modify `autotrader.py:315–365,473–641,1169–1205,1263–1480`, integrating existing `pending_policy`, `candidate_retry` and activation guard; add `tests/test_opportunity_execution.py`, update coherent fixtures/manifest. Do not weaken original validators or replace position lineage.

**Interfaces:**
- Existing proposal/pre-review/post-review/broker-review signatures retain compatibility; they call `evaluate_buy` using their explicit trusted snapshot/proof and attach deterministic held/pending/unknown errors.
- `require_current_allowance(root:Path, candidate:dict, *, attempt:AttemptAuthorization|None=None) -> PolicyDecision` in `opportunity_state.py` reloads authoritative state at safety boundaries, preserving the exact current-attempt exception. A verified provisional reopening claim permits only the existing broker precheck; after held/pending/risk checks pass, commit its grant under the existing entry lock and reload before any paid reviewer call. Do not consume a claim merely because a held symbol was presented.
- Feature `SUPPORTED_POLICY_VERSION=1`; malformed, absent required activation/history or incompatible activation denies new entry. Lifecycle/protection still precedes entry policy. No activation is implicit in this code change.

- [ ] **Step 1 — write RED tests.** Every entry wrapper and direct proposal path blocks held/pending/unknown state before paid review. A stale previously-qualified candidate cannot bypass the new guard. A current exact dual approval may pass normal final validation and submit once; another hash/proposal/evidence ID cannot borrow it. HOLD/disagreement prevents regenerated review. Existing legitimate exact-dossier market-condition retry still works while flat, but not after new holdings/pending or submission uncertainty. Mocked model/broker functions have nonzero successful controls.

```python
def test_held_candidate_never_reaches_review_or_placement(self):
    self.assertEqual(autotrader._run_locked(self.args), 2)
    self.reviewer_mock.assert_not_called()
    self.assertNotIn("place", self.broker_operations)
```
- [ ] **Step 2 — run RED.** `unit test_opportunity_execution`; negative controls must fail the intended no-review/no-place/allowance assertions, not import/setup errors.
- [ ] **Step 3 — implement exact flow.** Preserve expiry/pending/managed/protective reconciliation before candidate logic. Keep latest-candidate consumption and no recursive research/new consumer loop. Before initial snapshot accept only an eligible allowance or a verified provisional reopening claim; the latter permits existing broker prechecks, not reviews. After held/pending/risk checks pass, commit that claim's grant under the entry lock and reload before paid reviews. Apply shared BUY predicate before sizing and all deterministic validation wrappers, persist existing review lineage, and authorize only the current exact approved attempt. Respect pre-submission retry proof without adding structural blockers to its allowlist. Recheck event state, fresh broker positions/orders, exact pending/state proof and 120-second bounds immediately before intent under `entry_state.lock`; abort changed/stale/repair-required evidence without fetching again. Never invalidate a valid proof by writing intent before the final assertion. Preserve intent-before-place, exact readback, daily counting and submission-unknown obligations. Human grants are imported explicitly; no claim/grant can be manufactured from model text.
- [ ] **Step 4 — verify GREEN.** `unit test_opportunity_execution test_pipeline test_safety test_pending_capacity test_managed_reconciliation test_bridge_and_reuse test_autotrader_reconciliation`; use real existing gate functions and storage with only transport/model boundaries replaced. Test two competing executions, a fill during reviewers, a fill/torn state during final read, external mutation residual as a documented limitation, and exact-ref replay after lost acknowledgement. Protective SELLs and previously-authorized parent continuation must still work. Update old add-on/headroom assertions only where the explicitly approved no-add-on contract replaces them; retain separate flat-position $500-cap and risk-boundary coverage, never delete a safety case to obtain green.
- [ ] **Step 5 — commit/review gate.** `feat: enforce stable opportunity and no-add-on policy at entry boundaries`; review complete paid-review-to-intent authority, current-attempt exception, all old risk gates and no extra broker calls.

### Task 7: End-to-end isolation, private bootstrap and rollback rehearsal

**Files:** Add `tests/test_opportunity_workflow.py` classified `scenario`; update focused tests/manifest and create `docs/opportunity-entry-policy.md`. External private evidence holds source manifests, synthetic crash probes, historical audit/import rehearsal and compatibility-floor source copies; no real account fixture enters source.

**Interfaces:** Uses the exact APIs above. No new trading authority, public endpoint or background job. Admin audit/validate can run read-only on retained local state; apply remains separately authorized.

- [ ] **Step 1 — write RED scenario/rollback tests.** Execute real Radar-to-review orchestration in temporary roots: repeated report spent after first HOLD; later rewritten candidates advance; a genuinely new supported event reaches unchanged normal gates; after a fill no add-on reaches reviewers. Reuse/fallback cannot resurrect spent/held work. Crash after durable review/grant but before index refresh cannot create a new allowance. Rollback-floor source with activated v1 must block new entries while allowing protection/lifecycle; malformed/incomplete activation cannot silently disable this guard. Inject wrong results into each important table row and require intended assertion failures with zero setup errors.

```python
def test_floor_rollback_blocks_entry_but_preserves_protection(self):
    self.floor_guard_and_lifecycle_scenario()  # local scenario body executes pinned floor source
    self.assertTrue(self.protection_reconciled)
    self.assertFalse(self.new_entry_submitted)
    self.assertEqual(self.blocker, "opportunity_policy_version_unsupported")
```
- [ ] **Step 2 — run RED.** `unit test_opportunity_workflow`; authenticate the floor source copy and isolated root before replay. Do not mutate production or fabricate a source replay response.
- [ ] **Step 3 — implement only missing integration/docs.** Add no generic framework. Document supported resolver coverage, unknown-state behavior, all reason tokens, explicit admin approval rules, new observation fields, 120-second limits and residual external-writer race. Prepare a private read-only historical resolution audit and explicitly reviewed manifest proposal with exact source digests; unresolved cases remain explicit. Rehearse import/activation/idempotency only on an authenticated disposable history copy, preserving missing historical hashes as unknown. Record elapsed time/lookup counts; no claim of speedup or complete market coverage without measurement.
- [ ] **Step 4 — run acceptance.** Focused new/affected modules, canonical `fast`, `scenario`, `full`, and guarded `discover -s tests -q`. Require real exit zero, zero failures/errors/skips, full/raw count equality and full content/metadata isolation, including absent new policy stream/DB sidecars and a database-present fixture. Compare runtime paths and unchanged workflow contracts; new feature tests legitimately increase discovery count. Freeze all tracked/untracked feature bytes and obtain independent adversarial whole-branch review. Reviewers must inspect real trace/provenance/mutation results, not just summaries. Fix blockers with RED regressions and re-review exact final hashes.
- [ ] **Step 5 — commit/handoff, not deploy.** `test: verify opportunity lifecycle isolation and safe rollback`; report actual files/footprint/tests, unresolved coverage and private manifest status. Ask separately for publication/production activation. Do not publish private historical data or automatically apply administrative manifests.

## Future authorized deployment sequence (not executed by this plan)

1. Freeze reviewed implementation/floor/source hashes, verify existing auth and push readiness, ignored production fixtures and exact runtime. Review the private historical manifest/digest and explicit activation scope; unresolved identity coverage is not hidden.
2. Pause/read back affected producer/execution/operational-writer jobs, preserve original settings and verify quiescence with documented UID/visibility limits. Persist full operational content/metadata baseline outside production.
3. Promote reviewed source only. Run production full/raw and isolation before any policy activation, with jobs paused and no live order canary. Before activation, failure can restore the pre-activation source without rewriting broker journals.
4. Under approved admin authorization, revalidate current historical watermarks/manifest and append identity/reopening/activation records idempotently; changed source history requires a fresh review of the changed manifest. Verify exact records by readback. Preserve every original trade/review row. An unavailable/incomplete binding or failed durable acknowledgement blocks entries, not a retry-until-green loop.
5. Verify source, policy version and read-only activation/index status; publish only source and verify remote ref separately. Resume original settings only after successful checks. Observe actual executions separately from out-of-hours no-ops.
6. After activation, rollback is to the tested **COMPATIBILITY_FLOOR**, not unguarded old main: activated v1 blocks new entry in floor version 0. Keep entry-producing/execution jobs paused during recovery; verified compatible protection/reconciliation jobs may continue. Do not delete policy records, clear obligations, cancel broker protection or weaken the activation guard to obtain green. Rehearse this before release.

## Self-review and execution handoff

Coverage mapping: spec identity/provenance -> Task 1; allowance/concurrency -> Task 2; reopening/history activation -> Task 3; no-add-on/broker freshness -> Task 4; shortlist/reuse/fallback/outcomes -> Task 5; execution/protection/own approval -> Task 6; migration/rollback/isolation/release -> Task 0 and Task 7. All five Review Focus cases have owning tests above.

Before handing off, check actual existing test filenames, interface names/type fields, current-attempt allowance behavior, read-only lock semantics and private-data exclusion. Keep one implementation writer per worktree; task-by-task reviews precede subsequent dependent tasks. Do not parallelize interface-changing edits to the same core files.

Recommended execution: **Subagent-driven**, one fresh implementation worker and one fresh reviewer per task, followed by final whole-branch review. These gates affect paid reviews and order authority, so earlier independent rejection of a flawed identity/storage/entry contract is worth the extra contexts. **Native** remains an option: parent implements all tasks, then one fresh final reviewer; faster/cheaper but no independent task gate.

User must review this plan and select an execution method before runtime implementation starts. Neither choice authorizes pushing, operational bootstrap or deployment by itself.
