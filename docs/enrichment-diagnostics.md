# Private enrichment diagnostics

Diagnostics only: no budgeting, request ordering, source policy, earnings-history
lookup, qualification, trading gate, or provider-routing change. No new provider
requests or credential caching. This is not evidence that a historical-prices
endpoint exists or that any live endpoint/authentication has been verified.

The existing `alpha_radar.enable_timing()` context enables the additional trace
for `synthesize_candidate` enrichment. Normal/default execution creates no trace,
reads no diagnostic clock, and invokes no diagnostic persistence callback. The
existing coarse `private/research_timings.jsonl` remains unchanged. The new plain
JSONL is **only** `ROOT/private/enrichment_diagnostics.jsonl`; it is not a durable
ledger, SQLite stream, candidate field, dashboard input, or public metadata.

Each row contains opaque 32-hex `run_id` (the existing correlation when present),
a unique 32-hex `attempt_id`, strict `[A-Z]{1,6}` symbol (otherwise `INVALID`),
`stage=enrichment`, fixed `provider`, `operation`, and `outcome` enums, Unix
`started_at`/`ended_at`, monotonic `duration_seconds`, and read-only
`remaining_before`/`remaining_after` seconds (`null` without an active deadline
or if unavailable). Numeric values are finite and bounded. Optional fields are
safe integer error `http_status` (100–599), fixed `cache_reason`, and terminal
`dropped_records`. No raw errors, URLs, query strings, headers, credentials,
paths, content, prompts, or account/order identifiers are serialized.

Operations cover `trusted_date`, `sec_history`, synchronized stock/SPY `prices`,
StockAnalysis/Nasdaq resolution, and real `config`, HTTP `open`, `body`, `json`,
and SEC `cache` seams. Providers are `local`, `trusted`, `sec`, `massive`,
`stockanalysis`, `nasdaq`. Configuration includes the existing config subprocess
and its JSON/credential validation; transport JSON parsing is a separate seam.
Normal date results are `confirmed` / `no_date` (including no symbol match);
history is `fetched` / `empty`. These describe loader results, not new admission
criteria. Cache `hit`/`miss` reasons are `cachehit`, `absent`, `expired`, `invalid`,
`unreadable`. The cache observation completes **before** a miss invokes the
history loader, including hit returns; existing TTL and pre-fetch `checked_at`
semantics are retained.

Errors are `config_error`, `open_error`, `body_error`, `parse_error`, or `error`;
I/O timeouts are `timeout`. A `ResearchDeadlineExceeded` is `deadline` only when
the read-only clock observation shows exhaustion; otherwise it is `cancelled`
(e.g. an unbounded/non-byte reader). Other BaseException cancellation is also
`cancelled`. These are diagnostic observations, **not** provider-cause claims;
existing exception identity, handlers, and mapped radar failures are unchanged.
An ordinary swallowed source failure can coexist with a completed parent phase.

At most 120 detail records plus one record for each of the three phases and
one terminal attempt record are emitted per attempt (124 maximum); each line
is capped at 2048 bytes. Detail truncation reserves phase/terminal outcomes;
`dropped_records` counts detail records suppressed by this cap. Sink failures
can still lose any/all rows. The trace is best-effort, non-durable, append-only;
no fsync, retry, background work, or rotation policy is introduced. Instrumentation
adds synchronous local overhead inside the **unchanged** active allowance.

New private directories use mode 0700, trace files mode 0600. Existing unrelated
directories are not chmodded. Final root/private/file symlinks are refused;
nonregular or multiply linked trace files are refused. The configured project
root and its ancestors remain trusted. Logging failures (including hostile
exception attributes) cannot replace a result or original exception. ContextVar
state resets after nested attempts and cancellation; independent concurrent
contexts do not share attempt identities.

Offline coverage lives in `tests/test_enrichment_diagnostics.py` (fast tier),
including real synthesis→trusted-date→SEC-cache/history→stock/SPY orchestration
with synthetic external I/O, enabled/disabled request-order/call-count parity,
typed body/config/open/parse failures, mapped-failure identity, cache reasons,
privacy, bounded truncation, file modes/link refusal, and context isolation.
No live provider, broker, model, or deployment acceptance is implied.
