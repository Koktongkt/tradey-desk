# Evidence-bundle reliability implementation

Approved scope: retain original acquisition evidence, recover grounded body/publication within the existing one-shot allowance, improve gap-directed focused retrieval/rescue, and compare actual isolated live outcomes. No deployment/push/main/config/cron/Hermes changes, installs, new providers, budget increases or evidence/risk exceptions. Base2c677694c6dd3182152bd703b7111f2ce3f46d5e on existing isolated discovery worktree. Implement inlineTDD; one fresh whole-increment review at end.

Spec authority: docs/superpowers/specs/2026-10-22-discovery-quality-first-design.md section3F plus this bounded witness contract. Earlier discovery work is completed, not to be repeated.

## Global constraints and witness contract

- Keep690 active/720 outer,90 cumulative recovery, existing one model interpretation batch,10 model pages,8192-byte interpretation input,100000-byte extraction output, existing source-age rules, two distinct publishers, extraction concurrency/call/candidate caps and trading controls.
- Preserve the full useful representation the configured provider actually returns before head/tail truncation, with locally computed digest, exact requested/returned locations and title. Do not claim original HTML if only Markdown was fetched. Provider metadata alone is not authenticated publisher publication evidence. Missing originals/capacity omissions abstain explicitly; no refetch solely to manufacture historical proof. Strip provider-injected internal capture/hash/observation claims at trusted ingestion.
- Original-capture field is internal process-provenance data, not a signature or publisher authentication. Validate complete raw envelope before retaining/projection; never evade existing size/error limits by dropping fields. Retain private captures through worker/focused reuse/cache/direct paths. Present-invalid publication_observation inclNone remains non-overridable.
- Independent witness grammar: exact current-article title/URL association, explicit publication label paired to its date in an article header/definition-list/table or clearly attributed publication dateline; exclude event/update/related/navigation/copyright contexts. Validate complete original publication claims for conflicts and exact/day precision. The failed layout parser is NOT the witness validator. A quoted date, unsupported body, model confidence or arbitrary location never grants evidence authority.
- Existing date parsing/precision utilities may be reused; failed layout recognition may not be an acceptance predicate. Keep real exact instants, never invent zone/year/midnight. Unknown semantics abstain.
- Body fallback is exact retained passage selection from the same article, not generated prose. Combine optional body support with publication proposals in the SAME batch. Only independently validated outputs enter the existing source filter. Existing model protocol remains supported; unknown/extra/malformed fields fail closed unless explicitly part of the new schema.
- Search/rescue changes use same call/turn/time budgets. Keep scout URLs, exact search-result provenance, soft primary/independent/wire goals and unknown-domain eligibility. Prioritize a missing different publisher and same-event relevance; do not claim syndicated copies are editorially independent. Existing round-robin and deferred-synthesis reservations stay intact.

### Task 1: Preserve and validate retained captures

Interfaces: trusted provider/direct ingestion -> internal bounded capture -> extraction worker/normalizer/focused reuse/cache -> recovery validator.
Files: new retained_article.py plus research_extraction.py, extraction_worker.py, alpha_radar.py and boundary tests as required.
Steps: write failing preservation/hash/request-binding/capacity/spoof tests; run guarded focused runner and retain RED; implement minimal internal capture contract and independently test header/body witnesses including a layout the old parser fails; run GREEN and existing extraction/provenance tests; commit.
Expected: exact originals retained within unchanged caps; no provider-forged internal field acceptance; no publication/body acceptance from preservation alone. All negative event/update/related/conflict/future/precision cases reject. Ruling required if a useful original cannot safely fit.

### Task 2: Ground one-shot interpretation and gap-directed retrieval/rescue

Interfaces: Task1 captured witnesses -> existing publication interpreter/recovery -> unchanged source filter and synthesis. Focused search/receipt binding and rescue operation continuations retain existing APIs.
Files: publication_observation.py, publication_interpreter.py, publication_recovery.py, focused_search.py, alpha_radar.py and targeted tests.
Steps: write failing unfamiliar-layout publication/body recovery integration plus invalid-present/source-error/conflict/precision tests; retain RED; implement one-batch independent witness validation and bounded body passage attachment. Add failing focused/rescue tests for same-event missing-publisher targeting, duplicate-attempt avoidance and preserved shared budgets; implement minimal gap-directed instructions/scheduling. Run GREEN and old recovery/focused/deadline suites; commit.
Expected: a deterministic-parser miss can produce one validated source from exact original evidence; invalid publication or fabricated body never counts. No new model/recovery budget. Two accepted publishers still required. Rescue stops when satisfied and makes no late or repeated calls.

### Task 3: Evaluate and review actual bundle outcomes

Interfaces: changed increment -> immutable corpus replay/full/raw suites -> bounded live test with prior frozen source as comparator.
Steps: freeze current sources/private corpus and labels before scoring. Run guarded full/raw with all prerequisites present; no silent skips, unexpected model calls or operational mutations. Perform one fresh-context review, fix Important/Critical findings with RED→GREEN and rerun gates. Run actual isolated live scans through real intake/receipt/qualification with independent inner test_artifacts SQLite roots and720 outer ceilings, same config and existing providers; source acquisition/model calls authorized for this task, no broker/execution/reviewer calls or candidate publication. Preserve harness failures and distinguish development fixtures, retained historical replay and prospective live outcomes. Commit tested source, not private raw evidence. Report accepted-source/bundle/synthesis/final-qualified counts, typed blockers, latency and unchanged protections; zero final candidates remains a real result, not an excuse to weaken gates.
Expected: working exercised code and honest measured results. No production activation or claim of market-wide coverage from a single run.

## Review Focus

1. Provider-injected capture/hash/metadata or cross-URL/cache rebound cannot acquire publication/body authority.
2. The new fallback must work beyond the old layout recognizer but reject nearby event/update/related dates, conflicts and exact-to-day downgrades.
3. Capture growth, body proposals, I/O, startup and rescue cannot reset original caps/deadlines or create a second interpretation batch.
4. Missing/oversized/error originals abstain, never gain invented content or dates; successful model output is not evidence without independently validated support.
5. Focused/rescue changes must preserve source provenance and fair opportunity, avoid repeated URLs and protect a slow-but-sourceable candidate and synthesis reservation.
6. Report same-event two-publisher bundles and final real qualification separately from projection/corpus/fixture successes; unknown or zero gains remain explicit.
