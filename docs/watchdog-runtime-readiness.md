# Watchdog runtime readiness — bounded monitoring release

## Scope and authorization

Monitoring only: no order placement, cancellation, liquidation, journal repair,
kill-switch edits, or changed trading gates. The user explicitly approved an
isolated read-only independent reviewer and activation with visible, fail-closed
earnings coverage gaps. This is not a promise of complete thesis research or
lifetime total-return performance.

## Concrete runtime

- Paper-only broker collector with exact submitted-reference obligations and
  90-second process-group deadline/cleanup; requested activity interval is 90
  days, not verified strategy inception history.
- Separate 30-second Massive benchmark reader. Price-return-only remains the
  appropriate label until distributions/reinvestment capability is verified.
- Source executable uses only reviewed public HTTPS origins and machine fields:
  SEC submissions acceptance times/accessions; issuer RSS publication times/GUIDs.
  Reviewed profiles: BA, AMRX, XHR, ZIM; SEC-only probe profile MSFT. Other symbols
  return `source_profile_missing`, never a fabricated successful inspection.
- SEC receipts explicitly describe **filing metadata**, not financial contents.
  Issuer receipts describe RSS announcement text; large bodies are explicitly
  headline-only and marked content-incomplete; such receipts cannot classify
  successfully or advance cutoffs. Facts up to 4,000 characters stay complete.
  Original HTTP article links stay literal metadata and are never
  fetched or silently upgraded; evidence binds to the HTTPS feed and event GUID.
- Earnings machine date-only inspection produces `earnings_event_time_unknown`.
  Previous earnings reports are not inferred from next-report dates. This lane
  does NOT claim complete earnings coverage, invent report timestamps, or relax
  blackout controls. Source reasons persist through the monitoring report.
- Source and classifier workers run Python isolated mode in fresh scratch HOME,
  cwd and environment; no credentials, broker, memory or host-config imports.
- Ephemeral provider-only process resolves existing Codex OAuth, serves a private
  0700-directory/0600 Unix socket, and makes one direct stateless Responses call
  with `tools=[]`, `tool_choice=none`, `store=false`; no agent loop/tool dispatcher.
  Evidence cannot select model, provider, endpoint, credentials or instructions.
  This is reviewed process isolation, **not a general filesystem sandbox**.
- Gateway startup happens only for calendar-eligible daily runs. Failure remains
  a typed thesis gap without destroying broker/portfolio monitoring. Cleanup
  kills its entire process group. Source URL/model deadlines remain 15/20s.
- Cron launcher accepts only mechanical/daily and actual clock, with 120/900s
  hard signal deadlines that unwind cleanup; no clock/root/output overrides.
  Dedicated persistent venv: `/opt/data/venvs/tradey-watchdog`, fastmcp 3.4.8.
  Managed Hermes provider SDK remains in `/opt/hermes/.venv`; no runtime upgrade.
- `--cron` sends sanitized exceptions/daily summary via script-only scheduler
  stdout. There is no forged delivery receipt: outbox remains pending, with
  possible duplicate delivery disclosed. Empty stdout remains silent.

## Live probe evidence

At 2026-10-08T08:45Z, a real clean-environment source probe inspected SEC for five
symbols and issuer feeds for BA/AMRX/XHR/ZIM. It disclosed date-only earnings gaps
for all five and absent MSFT issuer profile. A real SEC BA accession receipt was
retrieved and classified using an explicitly **synthetic probe-only** baseline:
valid schema, `review_required`/`unclear`, low confidence, not a false breaker.
The provider gateway terminated and socket directory was cleaned afterward.

Evidence: ignored `test_artifacts/watchdog/activation/source-provider-proof.json`.
Probe receipts/model outputs are real; synthetic baseline is never a production
position or operational ledger entry. Earlier broker/benchmark smoke evidence
remains historical and is not relabeled as an unattended monitoring run.

## Release gate evidence

Final independent review: **PASS**, secret-free v4 snapshot, all 15 candidate
hashes unchanged before/after testing and matched to the live release tree.
Canonical full and raw discovery each passed **823 tests**, zero failures,
errors or skips, with the operational-isolation guard passing. Parent tier
results: fast 466; scenario 239. All six original adversarial regressions pass;
additional permanent guards cover reason-free unprotected positions, unknown
accounting history, and expired versus exact-boundary holding horizons.
The first reviews correctly blocked false all-clear, clipped facts, second-slot
actual seconds, missing replacement references, duplicate JSON, and horizon
status mismatch; fixes were RED-tested and independently re-reviewed.

Independent evidence: snapshot `test_artifacts/independent-v4-verdict.json`.
Live source/provider proof and confined broker/runtime smoke passed with
unchanged operational digests, empty conditions/outbox/source/baseline tables,
and no publication or delivery. Production activation is a separate scheduler
write, to be read back rather than inferred from create/trigger acknowledgments.
Actual post-close execution and relay delivery remain unobserved until real
eligible fires; no synthetic production clock is used.

Targeted thesis/workflow tests: 98 passing before release-tier validation.
Fast/scenario/full, raw discovery parity, operational-isolation guard, confined
runtime probes and independent review must pass on the frozen code before push
and registration. Scheduler/report/delivery evidence must be read back rather
than inferred from a create/trigger acknowledgment. Full unattended post-close
coverage can only be observed at a real eligible session; no synthetic clock is
permitted in the scheduled production launcher.
