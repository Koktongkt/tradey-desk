# Dashboard deployment reliability contract

`deploy_dashboard.sh` invokes `dashboard_deployment.py`. Successful build and deployment are silent. Child stdout/stderr are **never** forwarded to the scheduler, Telegram, decision audit, or public dashboard. `VERCEL_TOKEN` is optional: absent/empty token preserves Vercel's existing cached-login behavior; do not copy cached credentials into this repository.

The approved CLI invocation is exact, not floating:

```
npx --yes --package=vercel@63.1.2 -- vercel deploy <public-directory> --prod --yes
```

This may acquire the exact approved package on a normal production fire. Installing or invoking it against production is not part of offline verification. Pinning does not establish that version drift caused an earlier failure.

## Public failure protocol

Failure exits 1 and writes exactly one stdout line: `SYSTEM_FAILURE <token>`. Only these dashboard tokens are accepted by `run_cycle.parse_failure_event`; extra fields, private text, multiline output, unknown tokens and composite dashboard reasons are rejected:

| Token | Meaning |
|---|---|
| `dashboard_build_failed` | Local sanitized dashboard build exited nonzero |
| `dashboard_build_timeout` | Local build exceeded its deadline/shared budget |
| `dashboard_deploy_failed` | Unclassified CLI/deployment failure; no automatic retry |
| `dashboard_deploy_timeout` | CLI/deployment child exceeded its deadline |
| `dashboard_deploy_auth` | Recognized authentication/authorization failure |
| `dashboard_deploy_config` | Recognized project/configuration/argument or process-launch failure |
| `dashboard_deploy_build` | Recognized remote build/compilation failure |
| `dashboard_deploy_network` | Explicit transient network error code |
| `dashboard_deploy_rate_limit` | Recognized HTTP 429/rate-limit response |
| `dashboard_deploy_service` | Recognized transient HTTP 500/502/503/504 or gateway/service response |
| `dashboard_cli_missing` | Required CLI/runtime executable unavailable |
| `dashboard_timeout` | Outer executor's 300-second deadline expired; child stage unknown |

Decision audit retains the exact allowlisted token as `reason`. No classification is claimed for a historic incident whose original stderr was destroyed. Categories are recognized indicators, not a reconstruction of the full external cause.

## Retry and deadline ownership

The executor runs dashboard deployment **once**, even if a caller mistakenly requests more attempts. Non-dashboard executor retry/timeout semantics are unchanged. The helper owns all dashboard retries: local build once; deployment at most three attempts, with 2-second then 4-second backoff. Only classified network, rate-limit, transient service, and deployment timeout failures may retry. Auth/config/remote-build/unknown failures do not retry. Permanent indicators outrank transient indicators, including indicators observed before bounded output was discarded.

Each child has at most 90 seconds. One monotonic 290-second helper budget covers build, all deployment attempts and backoff, leaving ten seconds inside the existing 300-second outer envelope. A retry starts only when its backoff fits the remaining budget. All child pipes are drained with a bounded 64-KiB raw byte tail held only in memory; safe recognized categories survive truncation. Local `EACCES`/permission-denied indicators classify as permanent configuration failures before transient markers.

`dashboard_process.py` places every attempt, and the outer executor, behind a dedicated Linux pidfd caller-lifetime guardian. It reuses only `broker_supervisor.supervise`/cleanup mechanics, not broker operations, `broker_process`, or entry-lock inheritance. The guardian is an isolated subreaper; the shared runtime's `prctl` is unchanged. Its supervised collector drains and bounds raw output before emitting bounded JSON. The outer collector emits only a small allowlisted failure token. Every exit (success, failure, timeout, helper SIGTERM/SIGKILL, or caller death) kills and reaps ordinary and detached descendants, including descendants with closed pipes. Cleanup acknowledgement precedes a normal return and therefore precedes any retry. Standalone `run_attempt` also has its own independent guardian.

The 290/300-second limits are execution deadlines, not a claim that kernel process cleanup is instantaneous. An attempt guardian allows 0.2 seconds for the collector's completion protocol and cleanup has a 0.6-second bounded reap window; the outer guardian has no 0.2-second execution extension. Caller communication has a bounded 1.2-second acknowledgement allowance, with bounded exceptional cleanup. Unconfirmed containment raises instead of granting success or retry. Kernel-uninterruptible tasks, storage stalls, external SIGKILL/OOM of the guardian itself, or an externally stopped guardian that is never resumed are outside the cleanup guarantee. On caller death the guardian can reap its descendants but cannot reap itself; its exit is owned by init/the adopting reaper. This requires Linux pidfds, `/proc`, and subreaper support and fails before child launch if these are unavailable.

## Private diagnostics

Per-attempt records live in `private/dashboard_deploy_diagnostics/`, under the existing ignored `/private/` subtree and outside the only publication target, `public/`. Both private directory components are owner-only `0700`; new records are `0600`. JSON contains only stage, attempt, numeric return code, duration in milliseconds, and a fixed classification. Raw stderr/stdout, tokens, account/project/order IDs, URLs, filesystem paths, command arguments and arbitrary error messages are **not stored at all**. This structural allowlist is safer than regex-redacting free-form messages. Match the timestamp in the private record filename to the scheduler fire; inspect the safe category to choose auth/config/build/network troubleshooting. If richer provider-side evidence is needed, access it separately in a private operator session, never paste it into public output.

Retention keeps the newest 30 recognized owned regular records under a nonblocking directory lock. Directory/file descriptors use `O_NOFOLLOW`, creation uses `O_EXCL`, and pruning never follows symlinks or operates on hardlinked/unowned/non-record entries. A symlinked diagnostics directory is refused. The repository root is a trusted operator-controlled directory. Unexpected foreign files are left untouched rather than removed. Diagnostic failures, lock contention, unavailable storage or unsafe paths are best effort and cannot replace the build/deployment result. No raw diagnostic fallback is printed.

## Offline regression command

```
PYTHONPATH=tests:. uv run --with 'fastmcp<4' python -P -m unittest test_cycle test_pipeline
```

Tests use temporary builds and fake `npx` executables or injected subprocess results. They cover cached and token auth, exact pin, silent success, typed build/deploy/timeout auditing, single retry ownership, permanent/transient classification, shared budget, bounded output/deadlines, process-group cleanup, privacy, permissions, retention, symlink refusal and diagnostic I/O failure. No real deployment, broker call, credential inspection or control-state write is required.
