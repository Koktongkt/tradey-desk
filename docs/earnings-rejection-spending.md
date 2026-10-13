# Durable spending after authoritative earnings rejection

An execution-time `near_term_earnings` rejection spends research even when it
happens before independent review. This does **not** change the two-session
buffer, session-count convention, holding/rubric rules, paper mode, reviewers,
order/expiry limits, exposure limits, or reconciliation obligations.

## Evidence and identity

The existing private operational `order_ledger.jsonl` / transactional SQLite
store records genuine `status=rejected` evidence at `precheck`,
`final_validation`, or `broker_review`.

- Precheck evidence contains timestamp, rejection reason, stage, symbol,
  candidate ID (when available), dossier hash, and `earnings_setup_key`.
  It does not invent a reviewer result, proposed order, client-order ID,
  quantity, submission, or fill.
- Later stages enrich their existing real rejection row with stage and setup
  identity; their existing proposed-plan lineage and all rejection reasons are
  retained. No additional order is fabricated.
- The exact dossier hash is spent permanently, even if other fields change.
- The stable setup key binds **symbol + exchange-local earnings date + planned
  exit date**. Aware timestamps use New York dates; date-only values retain
  their stated dates. Equivalent timezone spellings, same-session time tweaks,
  and adding a precise report time to the same date cannot revive a setup.
  Missing/invalid/naive timestamps leave exact-hash matching available.
- Research/source-verification timestamps, candidate IDs, market prices, news
  wording, and thesis wording cannot revive the same earnings/exit setup.
  A genuinely different symbol, earnings date, or exit session is not
  ticker-blacklisted and must pass all existing checks again.

This evidence is not a daily submission, does not consume submission quota,
and never enters `trade_journal.jsonl`. Public projections keep the existing
allowlist; dossier/setup identities and private metadata are not published.
Unknown earnings or a transient quote-only failure does not spend earnings
identity. Existing completed-HOLD and narrow dual-approved market/cash/quote
retry semantics remain separate; a retry marker cannot undo earnings spending.

## Selection and failure handling

Autotrader reconciles pending/managed obligations first. After research
freshness verification, it checks earnings spending **before** the ordinary
review/retry guard and candidate broker snapshot. A spent candidate produces
`DECISION skipped near_term_earnings`, without another snapshot, review, or
placement for that candidate.

Radar filters spent candidates before safe-retry reuse. Live prepared intake
also checks spending before qualification/source verification, allowing the
existing source-first alternative loop to continue without publishing a
freshness-only replacement of the same blocked setup. Direct intake callers
must supply their actual `ledger_path`; CLI/default live-research paths do so.

Spending reads use strict, read-only SQLite/projection verification. They do
not import unsynchronized JSONL into SQLite. Missing state is normal for a
fresh install; unreadable/malformed state, recovery requirements, projection
mismatch, or unidentifiable earnings rejection evidence fails closed as
`SYSTEM_FAILURE earnings_spending_state`. A lost spending write is
`SYSTEM_FAILURE earnings_spending_persistence`, never a successful normal
rejection or a mislabeled broker failure. Both reasons are scheduler-allowlisted.

Legacy pre-lineage BUY/limit order rejections that carry a client-order ID,
evidence ID, symbol and aware recorded timestamp, but no dossier/stage/setup
fields, remain unchanged audit history. They cannot be attributed to a dossier
or used to blacklist a ticker. No historical identities are invented or rows
rewritten. New spending markers always carry stage and dossier fields; missing
or malformed modern identity still fails closed. This feature applies durable
spending to newly recorded, attributable rejections, not a guessed backfill.

Fixture and live dry runs use only
`test_artifacts/dry_run_order_ledger.jsonl` for spending evidence and selection;
they do not poison live candidate selection. Radar fixture intake also uses
that artifact ledger. Test roots are temporary and operational test fixtures
use transactional appends rather than replacing synchronized projections.

## Deterministic verification

The existing scenario modules contain the regressions, so no new manifest
module is needed:

```sh
PYTHONPATH=tests:. uv run --with 'fastmcp<4' python -P -m unittest \
  test_blocker_diagnostics.EarningsSpendingTests \
  test_candidate_alternatives.CandidateAlternativesTests.test_earnings_spent_intake_moves_to_source_first_alternative -v
uv run --with 'fastmcp<4' python tests/run_tests.py full
```

Coverage includes actual precheck persistence followed by a candidate-free
second execution cycle, radar reuse/intake, timezone-equivalent freshness
refresh, changed-setup revalidation, unrelated older dossiers, retry priority,
unknown earnings/quote-only failures, final/fresh-broker rejection, malformed
and unreadable state, failed writes at every gate, read-only storage verification,
pending reconciliation priority, dry-run isolation, scheduler classifications,
and public metadata isolation. Transport/model boundaries are replaced with
fixtures in these regressions; no live broker smoke is required for this local
persistence/selection change.
