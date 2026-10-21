# Recovery fair-byte reservation and post-rescue handoff — implementation report

## Result and scope

**DONE_WITH_CONCERNS; ready for independent review, not a claim that the historical incident now recovers.** Implemented on `fix/recovery-fair-handoff` in the isolated worktree, base `3ac1d1679dbcb797a492db7cff6a50b1fa7dc8fd`. No push, deployment, configuration/risk/source/earnings/trading-gate edits, dependency installation, live provider/model/news/broker/research/cron calls, subagents, or task-board mutation.

Final stable source/test bytes passed **1518/1518 full-tier tests and 1518/1518 raw-discovery tests, zero failures/errors/skips, both exit 0**. Relevant final focused run: 247 tests, exit 0. Baseline was 1503 tests; this change adds 15 tests, with no new test modules or manifest changes. `git diff --check` exits 0. The private verification record confirms unchanged source hashes and unchanged worktree operational state across both final runs.

## Actual retained incident result — important limitation

The real 5869-character GNW representation is now delivered through deterministic preparation and reaches the **single post-rescue model batch**. The frozen-clock replay nevertheless remains **`research_source_freshness_insufficient`, zero accepted publisher domains, no complete bundle**. The mock's genuinely quoted `October 19, 2026 15:37 ET` day proposal is rejected by the unchanged ORIGINAL-page validator: the captured representation is one flattened Markdown line, with navigation and a truncated title; existing `_contexts` supplies no admissible publication context. No timezone was guessed, ET was not converted to an instant, no synthetic publication label was added, and no parser rule was relaxed to obtain an acceptance count. ADVFN remains an undated UI negative control. **RCAT's historical seed bytes are unavailable and no RCAT recovery is claimed.** The routing/packing gaps are fixed; this retained flattened-context/parser limitation is not.

The incident test uses the real `_post_fetch_rescue_steps`, real deterministic recovery, real request encoder and original-page validator; only discovery/fetch/model outputs and clocks are mocked. It asserts the actual late GNW URL appears in the model request, exactly one subprocess-runner invocation, inadmissible-publication diagnostic, no final fetched/accepted evidence, and the concrete final failure code. Separate synthetic integration proves seed and late rescue pages compete in one batch. Another integration proves a deferred rescue can spend a previously unused batch and reaches synthesis with two distinct accepted publishers; it cannot reset a spent batch.

### Capture provenance

- GNW: exact cached page only, read using stdlib JSON from production `private/source_cache.json`, `checked_at=2026-10-21T15:43:06.273417Z`, length 5869. Text SHA256 `b9edb2af2ac2569181dbd162bf5b3fa98a76655e01d26156ff41f44a1086a2ce`.
- ADVFN: exact user-input page from retained session `20261021_154127_927eb8`, selected using a read-only SQLite URI and that exact session/role only; no storage helpers, broad transcript, credentials, or database copies. Text length 5825; SHA256 `3d761b176cd728629020ef88d549c501cec3052c717cfb19e22b05df5ca3bf38`, matching the incident's retained parsed-session witness.
- The incident directory's `retained_cache_projection.json` is actually empty (`[]`). The GNW page was instead found in the existing production source cache by exact article identity, completion timestamp, body length and quoted publication cue. The URL hashes in the prose incident report do **not** match the available original page URLs; those identifiers were not repaired or used as proof. Observed exact URL hashes are GNW `44a857e44511191ab4952dab2e61972e4148c8791d3060b9fd7ee3befa9610f9` and ADVFN `842d5dbdfd131d6dcfaaf4c2b9ee6a3e48815ab0b4bb0b7d428cb4b26fe0d3a6`.
- Private capture files, file hashes and original-text hashes: `test_artifacts/recovery-fair-handoff/capture-hashes.json`. Both text hashes are pinned in the tracked replay test. Captures are ignored and not committed.
- The pre-existing real corpus dataset plus 22 referenced immutable captures were copied byte-for-byte into this worktree, hash-verified. Existing ignored unpatched source fixture and 39 pinned baseline Python sources were provisioned without runtime DBs or credentials; hashes are in `fixture-hashes.json` and `baseline-source-hashes.json`. No source fixtures were patched.

## Current interfaces and invariants

### `publication_interpreter._prepare_request(pages, reasons)`

Signature and return contract are unchanged: original-page map keyed by bounded IDs, plus encoded JSON bytes. Canonical page validation, duplicates, invalid-present markers, URL/returned-URL bindings and maximum ten pages are unchanged.

Admission now reserves small wire contexts in the incoming fair-selector order **before any expansion to original bodies**. Large rows use verbatim windows around year tokens, at most 512 encoded bytes of quoted text including JSON escaping. Windows are never fabricated publication labels. Full bodies may replace reserved text only after all reservations, only if the entire request still fits. An uncompactable large row or irreducible schema/URL/title overhead emits `input_limit`. Request admission checks actual encoded JSON, not character estimates. Existing 8192 request bytes, 6000 original characters/page, ten model pages and 60000 total original characters remain unchanged. No splitting, retry, model override or new invocation.

The admitted map still contains the **ORIGINAL** retained page. `build_observation`, freshness evaluation, all conflict/exact-claim checks and observation hashes continue to operate on that original, never wire fragments. Omitting a model-visible conflict cannot authorize accepting it. Tests cover two large pages, all ten reservations across five owners, multibyte/escaped bytes, original hashes, hidden conflicts, exact-to-day refusal, updates vs publication, long URL overhead, byte boundary, duplicates and existing marker refusals.

### `publication_recovery.recover_publications(...)`

Adds keyword-only `allow_model: bool = True`; all existing keyword parameters and two-list return shape remain unchanged. `allow_model=False` performs deterministic/cache/scoped-refetch preparation but cannot spend the model batch. `RecoveryState` adds `remaining_seconds` (initially 90) and a run-local `deterministic_urls` set. `started_at` remains first entry time; `deadline` is now the current invocation's clamped absolute deadline, **not** an immutable elapsed-wall-clock expiry across rescue waiting. Internal `_recover_publications` owns the prior implementation; the public wrapper debits all elapsed recovery work in `finally`, including errors.

Deterministic preparation applies to bounded pages as well as oversized pages, and to newly scoped-refetched representations before model selection. Bounded originals retain exact text/cache identity and ordinary observation/receipt contracts. Oversized candidate contexts must additionally validate their proposed observation against the full original capture, so omitted original conflicts cannot become authority. Present observation markers are never removed. Successful deterministic admissions are capped at ten **per run**, separately from the unchanged ten-page one-shot model path (combined approved ceiling twenty); no admission-cap increase.

### Rescue interfaces and orchestration

`post_fetch_rescue_candidate` and `_post_fetch_rescue_steps` add optional `publication_handler=None`. Callback contract is `publication_handler(delivered_pages, *, deadline) -> prepared_pages`; direct callers without a callback retain their previous behavior. The live handler stores useful or unknown delivered originals in a run-local pool and runs deterministic recovery before filtering. It receives the current rescue launch deadline; it never launches the model itself.

Seeds are prepared deterministically first. Initial rescue collection runs for thin bundles only when no bundle is already complete. The single model opportunity then runs against the shared seed/rescue pool before final quality rejection. Already-complete bundles skip model selection and avoid unnecessary initial rescue. Deferred rescue keeps the same state; spent batches stay spent. A previously unused model opportunity can run after deferred collection, clamped to both deferred rescue and synthesis-launch reserves. Accepted helper results are re-filtered before incorporation; accepted replacements are retained in the shared pool.

## Timing accounting, before and after

Let `O` be the original active deadline, `D=30+45+5=80` the unchanged synthesis/enrichment/transition reserve, `R` remaining recovery work, `t` current monotonic time, and `E` unspent evidence work.

Before: first recovery fixed `deadline=min(start+90,O-D)` and spent its model opportunity before rescue. A later call would include rescue waiting in that absolute expiry. Evidence was paused for that one recovery stage using `E=max(0,evidence_deadline-t)` and resumed afterward; consumed evidence was not replenished.

After, at each recovery entry:

- `deadline=min(t+R,O-D, optional_current_stage_deadline)`.
- On exit, including exceptions: `R=max(0,R-max(0,t_exit-t_entry))`.
- Before that stage: `E=max(0,evidence_deadline-t_entry)`; after: `evidence_deadline=min(O-D,t_after+E)`.
- Initial rescue launch deadline is `min(evidence_deadline,O-D-R)`, reserving the still-unspent recovery allowance rather than consuming downstream headroom.
- Deferred recovery additionally clamps to `min(deferred_rescue_deadline,synthesis_deadline-30-5)`; the normal cumulative enrichment reserve and overall launch checks still apply.

The 90 seconds includes deterministic work, cache/scoped-refetch work, model request preparation, command construction, startup, pipes, validation and persistence inside recovery. Rescue waiting does not refill or consume that recovery allowance. Advancing-clock tests debit 20 preparation seconds, exclude 93 rescue-wait seconds, then debit 30 model seconds, leaving 40 of the original 90. The 180-second evidence allowance is not replenished; rescue helper deadlines are conservative fixed launch snapshots, so nested recovery can cause under-use of available evidence time rather than grant extra time. Active 690, outer 720, execution freshness 600, 30-second minimum synthesis, 45 cumulative enrichment and five-second transition margin are unchanged. These are bounded cooperative deadlines, not hard-real-time scheduling guarantees.

## TDD, first failures and verification

Private evidence root: `test_artifacts/recovery-fair-handoff` (directories 0700, files 0600). All logs and first failures retained. No private evidence was force-added.

The no-install runner clears inherited diagnostic `PYTHONPATH`, sets `HERMES_DISABLE_LAZY_INSTALLS=1`, `PYTHONDONTWRITEBYTECODE=1`, and the own-worktree `TRADEY_UNPATCHED_ROOT`, reuses existing `focused-coverage-25/.../tpy.sh`, and executes the pre-existing `publication-hybrid/task4/fix1/outer_suite.py`. Targeted/raw commands install tracked `tests/offline_test_guard.py` before test imports. The full runner installs it before discovery. Harmless real Python containment children remain enabled. Neither tripwire is an OS/network sandbox; application network/model seams are mocked.

Commands and outcomes (full exact final argv and hashes are also in private `verification.json`):

1. Relevant baseline: guarded unittest modules `test_publication_interpreter`, `test_publication_recovery`, `test_publication_integration`. First attempt: 104 tests, one environment error because `TRADEY_UNPATCHED_ROOT` was absent, exit 1 (`baseline.log`). After byte-verified source fixture provisioning: 104 tests pass, exit 0 (`baseline-fixtures.log`).
2. Fair-byte RED: one new regression; initially no page was admitted and its unchecked call indexing errored (`red-bytes.log`); changed to an explicit one-call assertion and observed the intended failure (`red-bytes-assertion.log`, exit 1). Minimal packing change then GREEN (`green-bytes.log`, exit 0).
3. Preparation/handoff RED: two new tests fail on missing `allow_model` keyword (`red-handoff.log`, exit 1); bounded preparation and active-work wrapper then GREEN (`green-handoff.log`, exit 0).
4. Live handoff RED: missing rescue handler (`red-live.log`, exit 1), then integrated seed/rescue pool and post-collection batch. Additional REDs independently preserved for original oversized conflict (`red-original-conflict.log`), fresh-refetch deterministic parsing (`red-refetch.log`), deadline propagation (`red-rescue-deadline.log`), and unused deferred opportunity (`red-deferred-unused.log`); all exit 1 before their respective minimal fixes.
5. Focused first run: 108 tests, 14 failures/five errors, exit 1; old model-only tests were exercising now-deterministic inputs. Their shared helper now explicitly isolates deterministic preparation for model/cache/refetch-specific assertions, while real deterministic paths have separate regressions. Bounded successful recovery was changed to retain original text, fixing receipt/cache identity rather than weakening expectations. Further focused run: 216 tests, one duplicate-quality diagnostic failure/one malformed-URL error; fixed deduplication and retained string-only URL handling. Next 217 tests pass. Extended runs of 134, 244 and final 247 tests pass. Logs retained under `focused-*.log`.
6. First full/raw attempt preserved as `first-full.log`, `first-raw.log`, `first-verification.json`: full discovery failed before running tests (`fastmcp` absent from base PM site, exit 1); raw ran 1414 tests with four failures/11 errors, exit 1. Environment diagnosis found the already-committed bridge dependency site, no install. Provisioned 39 exact ignored pinned-baseline `.py` fixtures, fixing the missing original fixture-path assertion. The fail-closed boundary self-test depended on complete full discovery and also cleared with this environment correction. Two behavior-specific expectations were updated: deferred deadline 615→610 retains the required five-second transition reserve; synthetic large bodies with no date context now launch zero model processes. Corrected focused environment/contracts: 18 tests pass, exit 0. These first full/raw failures were not overwritten or concealed.
7. Final stable-byte verification, **one full and one raw after diagnosis/correction**, invoked by `python test_artifacts/recovery-fair-handoff/verify.py` (exit 0):
   - `bash test_artifacts/recovery-fair-handoff/run.sh tests/run_tests.py full -v`: 67 modules, 1518 tests, zero failures/errors/skips; exit 0; test execution 122.962s, child wall 124.31177479797043s.
   - `bash test_artifacts/recovery-fair-handoff/run.sh -c 'import sys,unittest; sys.path.insert(0,"tests"); import offline_test_guard; offline_test_guard.install(); suite=unittest.defaultTestLoader.discover("tests"); result=unittest.TextTestRunner(verbosity=2).run(suite); raise SystemExit(not result.wasSuccessful())'`: 1518 tests, zero failures/errors/skips; exit 0; test execution 123.076s, child wall 124.42558188299881s.
   - Both: tracked unexpected actual Hermes attempts 0, unexpected local controls 0, expected blocked harmless local control 1; outer unexpected actual Hermes attempts 0, harmless local-control boundary visits 1. Both real corpus tests and the incident replay executed, no skips.

An early private shell runner accidentally sourced `tpy.sh` with positional arguments, duplicating early baseline/RED/GREEN executions; this was diagnosed and fixed before focused integration/full verification by saving/clearing positional arguments before sourcing. Logs remain unchanged; final verification executes each suite once.

## Isolation and stable bytes

Final full runner reports no operational-isolation failure. Independent stdlib before/after snapshots are identical:

- `autonomy_config.json`: `3cc01a9172cb0cc3abe835c33d09ab7a9c737c89b5f676e5abd67e4b29474d51`.
- `watchdog_config.json`: `86277317052224a110e284beed39df7ce20cf4b7dd02c94c72bdce2be56167ce`.
- No worktree private operational files or runtime databases were created. Snapshot scope is this worktree, not a claim about unrelated production activity.

Final tested production hashes:

- `alpha_radar.py`: `7dcbcae9825edee5c614be1e279b21b6cf7c60543ca00df2cc8524c197b77b15`.
- `publication_interpreter.py`: `d4e33c3cae7828114d3bdb3b5cfddb21298c471d87a35fa8efced27b731a6a12`.
- `publication_recovery.py`: `a051c81da3351f11f48b37f6dd1b2e81c424de8b5589f11b57d2325ffb2272d0`.

Full source/test hashes and exact argv are in `verification.json`; no production/test bytes changed after those two final passing runs. Self-review covered original-vs-wire authority, exact/hash/marker binding, full-original oversized conflict refusal, active-work debit on exceptions, one-shot state, cache timestamp identity, deadline clamps and unchanged trading gates. Only three production modules, five existing test modules, this report and the supplied approved brief are committed.

## Remaining limits for independent review

1. The historical GNW flattened context remains unsupported; this change **does not establish a historical two-source recovery**. Further parser-context design would require separately reviewed evidence/role rules, not relaxed validation or guessed ET offsets.
2. Compact windows are conservative and can omit model-visible context. Original validation remains authoritative, so omission causes abstention/refusal, not permission. Long URL/schema overhead can still make one-page-per-candidate transport physically impossible and emits `input_limit`.
3. Original mutable cache/fixture bodies are never modified; there is no new live-provider acceptance evidence. The original incident's GNW URL-hash discrepancy and empty saved cache projection remain evidence limitations, explicitly separated from the exact available captures.
4. Fixed rescue launch snapshots may under-use evidence allowance when nested deterministic recovery consumes time; no budget is increased. Existing subprocess supervisor limitations (including detached descendants and non-hard-real-time OS calls) are unchanged.
5. Independent parent review and release are outstanding. No push/deploy performed by this implementer.
