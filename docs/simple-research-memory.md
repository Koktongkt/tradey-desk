# Exact-document research memory

Policy version 3 replaces event/allowance admission with `exact_document_research_dedup`. It does not authorize trading from research results. All paper-only settings, exact-dossier review protection, held/pending exclusion, dual approval, risk/earnings checks, durable intent and lifecycle controls remain independent.

## Work identity and limits

A document key hashes verified issuer, representation contract, exact complete content digest, rule version and stage. Synthesis keys hash the sorted set of all admitted document keys. Changed complete bytes, another admitted source, another issuer or representation, and changed rules cannot cross-hit. No semantic transaction/event matching is attempted; cosmetic changes may cause misses. Issuer attribution currently requires an unambiguous complete SEC cover with matching trading symbol and CIK/filing locator; leads without that mapping still run uncached through normal quality gates.

Only durable successful terminal work is completed: validated no-setup/rejection, processed document or qualified dossier. Captures alone and failed attempts do not count. Complete source references and result digests must verify before reuse. Missing/corrupt cache runs uncached within the original deadline; mandatory history failure still blocks authority. Cache projection damage is not a whole-ledger authority dependency; structural database damage still blocks.

Completed work expires no later than 24 hours after original completion; stricter evidence and candidate freshness limits always win. Hits do not renew timestamps. Qualified-dossier reuse retains the original immutable dossier, requires the current transition, and remains bounded by the existing verified-fallback/candidate TTL and strict completed-review history. Old candidates cannot be rehashed into v3.

An exact issuer/URL/transient-category failure cools down that resource for 20 minutes. Alternate URLs remain eligible. Only failures with deterministically established ownership are stored; unavailable issuer attribution means uncached fetch, not a symbol ban. No publisher blacklist, added discovery call or restarted research deadline is authorized.

## Private diagnostics and public outcomes

Private reason tokens are `research_memory_hit`, `research_memory_miss`, `research_memory_unusable`, and `research_memory_cooldown`. Bounded outcomes distinguish `duplicate_bundle_skipped`, `completed_dossier_reused`, and `new_dossier_qualified`; count these separately. Reuse is not fresh qualification. Public decision/no-setup/failure envelopes stay unchanged and contain no capture bodies, paths, private hashes, reviews or broker identifiers. Offline functional replay is evidence of avoided work for its pinned sequence, not market coverage, yield, profitability or latency guarantees.

## Transition and release

Use the accepted interpreter with `research_memory_transition.py`:

```
python -B research_memory_transition.py prepare --root ROOT --source-revision FULL_COMMIT --rule-version RULE
python -B research_memory_transition.py validate --root ROOT --manifest MANIFEST
python -B research_memory_transition.py apply --root ROOT --manifest MANIFEST --approved-manifest-sha256 EXACT_DIGEST --apply
python -B research_memory_transition.py status --root ROOT
```

Prepare/validate/status do not activate policy. The root-bound manifest includes predecessor identity, every registered stream prefix, config and broker-baseline hashes, source and rules. A separate exact-digest operator approval is required before apply. Drain affected writers first; changes invalidate preparation and require a fresh proposal. Append one transition under entry/storage locks, then read back exact SQLite/JSONL activation and unchanged historical prefixes. Exact replay is idempotent; a divergent reset is refused. Preserve all prior policy, review, candidate, intent, order and fill rows.

Before cutover, run canonical full and raw offline suites with pinned fixtures, explicit no-network/model/broker controls and persisted operational isolation inventories. Rehearse real retained history separately and require independent source acceptance. No live trading or paid-research canary is needed. Promote accepted source without changing enabled/broker_mode, cadence, Hermes config or gateway. Preserve and restore exact affected schedule state. Observe ordinary scheduled execution separately from deployment success.

## Compatible rollback

The pre-feature `f67e4e1` runtime (same runtime tree as the accepted acquisition-research release) supports policy versions through 2, reads v3 only to refuse entry, and keeps reconciliation/protection before entry-version refusal. The release workflow executes its actual pinned source in a subprocess against a v3 transition and both entry-only and filled protective histories. Retain that source pin, fixture manifest and results with release evidence. Rollback restores only release-owned source; never restore a database or remove activation. Keep new entry blocked if compatibility is unproven; keep compatible protection/reconciliation available. Full and raw production isolation, source readback, activation, remote publication, schedule restoration and first successful normal scheduled run are distinct claims.
