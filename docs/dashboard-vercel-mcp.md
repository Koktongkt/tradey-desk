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
  disabled. No trading/research calls added. The normal existing public build is
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

## Verification and outstanding concern

Evidence is in ignored `test_artifacts/dashboard-mcp/` (private permissions).
Fresh-worker read-only control authenticated against the exact target and found
239 native MCP tools, including inline-files deployment capability.

Exactly one production mutation was sent. It created
`dpl_GLq9BJ5J6W2mXbrMqQHnZNvy9nwD`. The initial worker returned a generic failure
because native Vercel API tools wrap data as `result.deployment`, rather than the
flat fixture shape. No duplicate create was attempted. Read-only MCP inspection
identified that envelope and nested `project.id`; regression tests and adapter
normalization were corrected. The corrected adapter's read-only verification
returned this exact ID, correct project, production, READY and
`tradey-desk-psi.vercel.app` alias membership. A second production create was
**not** performed; successful cold create-through-final-receipt on the final
revision is therefore not claimed. Review this residual before cron activation.

All three published artifacts returned HTTP 200 on the production alias and
matched their staging SHA-256 hashes. The immutable deployment URL is protected
and returned a different authentication page; no protection/bypass settings were
changed. Alias membership plus alias artifact hashes are the verified live path.

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
tpy -m unittest discover -s tests -p test_dashboard_mcp.py -v
tpy -m unittest discover -s tests -v
tpy tests/run_tests.py full
```

Fixture prerequisites: existing installed committed dependency environment (no
install), existing pinned unpatched runtime at SHA
`d923a5eb487a17c0a68801bba9ef0f56c81040a8`, ignored
`test_artifacts/project-extraction/`, and a source-only copy of the existing
`task6-baseline-835c56c` fixture beneath this worktree's
`test_artifacts/focused-coverage-25/`. No operational/private data copied.

- Initial isolated pipeline baseline: 52 tests passed.
- New adapter/entrypoint tests: 13 passed (including real guardian/outer output
  filtering, payload encoding/exclusions/links/caps, auth/unknown response,
  no-duplicate create, cross-project failure, failed state, timeout, READY,
  read-only resume and private receipt retention).
- Raw discovery: 1531 tests, 0 failures/errors, 4 skips.
- Full supported runner: 1531 tests, 0 failures/errors, 4 skips.
- Both full outputs: expected blocked local control 1; unexpected actual Hermes
  attempts 0; unexpected local controls 0. Existing real-PID guard cleanup and
  outer-timeout fixtures passed.
- The first unprepared full run failed on missing ignored fixtures/environment
  and missing new test-manifest classification; those were corrected before the
  two clean final full runs. See retained original log for distinction.

No cron/shim, production source branch, Hermes core/config/gateway, provider,
research/broker settings, or enabled/trading-mode settings were changed.
