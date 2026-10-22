# Script-only Vercel MCP dashboard transport

## Activation (review/merge first)

The opt-in entrypoint is `cron/dashboard_mcp.sh`. Existing `cron/dashboard.sh`,
`deploy_dashboard.sh`, `dashboard_deployment.py` and non-dashboard jobs remain
unchanged. Do not route this entrypoint through `run_cycle.py dashboard` (that
would invoke the old CLI transport).

After reviewing/merging this branch, change only the existing dashboard shim
`~/.hermes/scripts/tradey_dashboard.sh` to exec the repository's
`cron/dashboard_mcp.sh`. Alternatively change this one cron's script target.
Keep cron `c95f73d0422f`, `no_agent=true`, enabled status, workdir, delivery origin
and schedule `12,32,52 * * * 1-5` unchanged. Read back the exact shim and cron after
activation. No Hermes restart/configuration edit is needed. Rollback is the
previous shim target `cron/dashboard.sh`.

## Guarantees

- Existing `run_cycle.in_window('dashboard')` predicate, silent outside-window
  return, silent success and allowlisted `SYSTEM_FAILURE dashboard_*` failures.
- Existing guardian/subreaper (`dashboard_process.run_owned`) owns the 300-second
  outer envelope and each build/deploy stage. Helper absolute budget 290 seconds;
  build 90 seconds; one MCP worker 90 seconds; worker 85-second absolute budget,
  connect up to 30 seconds, individual RPC up to 25 seconds of remaining budget.
- Deterministic Python/batch shell, no LLM agent/prompt payload, MCP sampling
  and elicitation explicitly disabled in the adapter-local connection override.
  No global Hermes configuration/core change. No trading/research calls added. The normal existing public build is
  reused unchanged (including its existing read-only portfolio refresh).
- Installed Hermes runtime discovered through `hermes --print-runtime-command`;
  existing bootstrap, `MCPServerTask` connection and OAuth lifecycle are reused.
  This installed release has no `MCPClient` facade/public single-server client;
  narrowly scoped internal `_connect_server`/loop hooks are used without modifying
  Hermes. Runtime format changes fail closed. Only server `vercel` is connected.
- MCP `create_deployment` inline files, fixed team/project/production target.
  No Vercel REST client, copied/exported tokens, CLI deployment/fallback, Git
  source or whole-repository upload. API tool descriptions mentioning CLI
  fallback are documentation only; adapter never executes that fallback.
- Only `public/` files; dotfiles (including `.vercel`) excluded from uploads;
  `.vercel/project.json` must match both expected IDs. Symlinks, hardlinks,
  nonregular files and private/state/secrets/node_modules components rejected.
  UTF-8 or base64 for binary; 8 MiB raw/12 MiB serialized caps. `index.html` and
  `dashboard.json` required. Existing sanitizer remains the content boundary;
  the payload builder is not a replacement sanitizer for arbitrary public files.
- Exactly one create invocation; no automatic create retry on timeout/unknown
  result. Poll exact deployment ID, require same project + production + READY
  and expected alias membership. Safe private structured diagnostics/receipts,
  0700 directories/0600 files; last 30 receipt files retained. No raw remote error
  body/credential is included in cron alerts. This entrypoint doesn't append
  `run_cycle` schedule/deployment decision-audit rows; structural deployment
  diagnostics replace those logs for this opt-in path.

## Verification and retained first-smoke incident

Evidence is in ignored `test_artifacts/dashboard-mcp/` (private permissions).
Fresh-worker read-only control authenticated against the exact target and found
239 native MCP tools, including inline-files deployment capability.

The **first** production smoke created
`dpl_GLq9BJ5J6W2mXbrMqQHnZNvy9nwD` but returned a generic worker failure:
native Vercel API tools wrap data as `result.deployment`, rather than the flat
fixture shape. No duplicate create was attempted. Read-only MCP inspection
identified that envelope and nested `project.id`; normalization was corrected.
The corrected adapter's read-only verification subsequently found that exact ID,
correct project, production, READY and `tradey-desk-psi.vercel.app` membership.
Original failed smoke evidence is retained; read-only recovery was not a cold
create-through-receipt success.

After the callback fix, one expressly authorized final-adapter-revision smoke
created `dpl_DqR9dnJK9zNf2oWNC8eMVKd2cvjm`. Its real worker and helper both exited
0, with an owner-only final receipt. Native calls were list-projects, exactly
one CREATE, two same-ID GETs and alias listing; the second GET was READY for the
fixed project/production, with the expected alias. No create retry occurred.
`fix1-native-envelopes.json` retains credential-free native result envelopes
before normalization, bound to adapter and staged-manifest SHA-256 provenance.
The regression replays these actual CREATE/GET/alias envelopes through the final
native adapter and normalizer using a stub session, asserting one CREATE,
same-ID/project/target/READY/alias and a private receipt; offline tests do not
connect to MCP. No manual normalization was used to turn the live worker green.

All three final-smoke artifacts returned HTTP 200 on the production alias with
SHA-256 equal to their staged files (`fix1-http-verification.json`,
`fix1-smoke-manifest.json`). During the first smoke the immutable deployment URL
returned a protection page; protection/bypass settings were not changed.
Alias membership plus alias artifact hashes remain the verified live path.

The smoke build called only `public_dashboard.build_data`/`html_template`, reusing
an already-sanitized portfolio snapshot from the current public dashboard and
current local audit files. `fetch_live_portfolio` was explicitly disabled: no
broker refresh, research or order call was made by the smoke. Only the three
sanitized files in `smoke-manifest.json` were uploaded.

### Tests

Run from this worktree, not production:

```sh
export HERMES_DISABLE_LAZY_INSTALLS=1 PYTHONDONTWRITEBYTECODE=1
export TRADEY_UNPATCHED_ROOT=/home/hermes/apps/hermes/projects/tradey-desk/test_artifacts/focused-coverage-25/task6-unpatched-runtime
. /home/hermes/apps/hermes/projects/tradey-desk/.worktrees/focused-coverage-25/test_artifacts/focused-coverage-25/tpy.sh
tpy -c "import sys; sys.path.insert(0,'tests'); import offline_test_guard as g; g.install(); import unittest; unittest.main(module='test_dashboard_mcp',argv=['tests','-v'])"
tpy -c "import sys; sys.path.insert(0,'tests'); import offline_test_guard as g; g.install(); import runpy; sys.argv=['tests/run_tests.py','full']; runpy.run_path('tests/run_tests.py',run_name='__main__')"
tpy -c "import sys; sys.path.insert(0,'tests'); import offline_test_guard as g; g.install(); import unittest; unittest.main(module=None,argv=['tests','discover','-s','tests','-v'])"
```

Fixture prerequisites: existing installed committed dependency environment (no
install), existing pinned unpatched runtime at SHA
`d923a5eb487a17c0a68801bba9ef0f56c81040a8`, ignored
`test_artifacts/project-extraction/`, and a source-only copy of the existing
`task6-baseline-835c56c` fixture beneath this worktree's
`test_artifacts/focused-coverage-25/`. Also required are the parent-provisioned
25 immutable files enumerated/hash-bound by `fixture-provision-parent.json`:
`publication-hybrid-validation/dataset.json`, its 22 referenced original captures
(including r07), and the retained ADVFN/GNW incident pages beneath
`recovery-fair-handoff/`. The native replay requires private
`dashboard-mcp/fix1-native-envelopes.json`, SHA-256
`cd597723d18a0f2ebadfc7ec34477b8c7e9417bab96008f4e4f21272ad98c927`.
Missing replay evidence fails rather than skipping. No operational data/DBs,
credentials or private runtime configuration were copied.

- Initial isolated pipeline baseline: 52 tests passed.
- Initial adapter tests: 13; final focused gate: **14 passed, zero skips**.
  The new mocked connection test was first observed failing on enabled
  elicitation (`fix1-red.log`, exit 1), then passed after the adapter-only fix.
  The prior synthetic envelope test now replays the saved native response.
- Before provisioning, raw/full each passed 1531 with four private-fixture skips;
  those historical results were not the zero-skip release gate.
- Final supported full: **1532 tests, 0 failures/errors/skips**, exit 0
  (`fix1-full.log`); final raw discovery: **1532 tests, 0 failures/errors/skips**,
  exit 0 (`fix1-raw.log`). Both first post-fix release runs passed.
- Both full/raw outer guards were installed before discovery/imports. Final
  counters: expected blocked local control 1, unexpected actual Hermes attempts 0,
  unexpected local controls 0. Nested intentionally failing controls are expected;
  real-PID guardian cleanup/outer-timeout fixtures passed. The tripwire is not a
  general network sandbox; the native-connection tests use stub modules/sessions.
- Original unprepared full-run failure (missing ignored fixtures/environment and
  missing initial test-manifest classification) remains retained separately.
- Final smoke worker/helper/outer exit 0 and HTTP hashes are recorded separately
  from offline release runs. `fix1-report.md` and before/after manifests document
  isolation, exact hashes, fixture prerequisites and command exits.

No cron/shim, production source branch, Hermes core/config/gateway, provider,
research/broker settings, or enabled/trading-mode settings were changed.
