# Prospective opportunity-policy cutover (paper only)

Policy v2 starts event-level review memory at one explicit, approved ledger boundary. It does not reconstruct legacy review associations and does not claim that legacy decisions never happened. One previously rejected event can receive a fresh assessment after cutover; a completed prospective HOLD/disagreement then spends its event allowance across regenerated dossiers.

## Unchanged obligations

The baseline never filters operational order, position, protection, fill, reservation, daily-submission or performance readers. Existing held shares and unresolved entry obligations still block a new BUY. Original rows remain append-only. Paper mode, enabled state, schedules, models, risk/source/earnings gates and broker execution authority are unchanged. Initial reopening is manual/evidence-backed only; automatic conditions are not admitted in prospective mode.

## Boundary and compatibility

One atomic `activation` row with `policy_version=2` contains `prospective_baseline`. It binds the exact root and canonical per-stream prefix counts/digests for all `sqlite_ledger.DEFAULT_STREAMS`; its deterministic baseline ID is included in every newly admitted candidate before dossier hashing. Old cached candidates and workers without that trusted binding cannot enter the new review path. Hashless/unbound post-boundary reviews fail closed rather than disappearing as legacy history.

Full retained opportunity history is structurally/source-reference validated before deriving the prospective view. Old unresolved/gap records remain intact but do not become legacy-only research bans under this explicit mode. Storage damage, prefix mismatch, unsupported versions and malformed prospective links remain blockers.

Apply compares the exact approved watermark again inside the canonical ledger writer lock before creating/appending policy projection bytes. The complete baseline and activation land in one append, so there is no preparation interval with partial authority. Repeating the exact same manifest is idempotent; a second baseline/reset is forbidden. The old v1 admin activation API cannot create descriptorless v2.

## Administration

Use the verified existing Python/dependency environment. Commands below do not request network/model/broker work:

```
python opportunity_cutover.py prepare --root /absolute/desk/root
python opportunity_cutover.py validate --root /absolute/desk/root --manifest /private/manifest.json
python opportunity_cutover.py status --root /absolute/desk/root
python opportunity_cutover.py activate --root /absolute/desk/root --manifest /private/manifest.json --approved-manifest-sha256 <exact-canonical-digest> --apply
```

Prepare prints a proposal; it does not write a manifest or authorize apply. Save proposal bytes privately. Use `opportunity_cutover.manifest_digest` for the canonical digest, not a pretty-printed file hash. Validate must report `valid=true`; after activation use status plus `opportunity_state.load_index` and exact SQLite/JSONL readback to verify effective enforcement. Validate compares against an unactivated root; an already active root is checked with status/load-index and the idempotent API contract, not by preparing a reset.

## Controlled rollout

1. Complete focused, fast/scenario, full and raw offline gates; retain actual exits/counts, fixture provenance and isolation receipts.
2. Rehearse on an authenticated disposable real-history copy with its own root-bound manifest, including compatible rollback and lifecycle checks. Copy success does not authorize the production digest.
3. Freeze independently reviewed source and retain its rollback ref. Pause affected production writers, preserve exact prior job settings and drain in-flight workers.
4. Obtain current paper broker positions/orders read-only; preserve existing operational authority/ownership and protection. Ambiguity remains blocked rather than being reset.
5. Generate and approve the exact production manifest/digest. Promote only reviewed source, preserve configuration, and pass production full/raw isolation gates before applying.
6. Apply the exact approved payload, read back policy version/baseline and unchanged history prefixes, then resume exactly the jobs paused for rollout and verify settings.

A compatible rollback reader must reject policy v2 for new entry while protection/reconciliation continues. Never delete activation or restore a historical database to make permissive code run. An activation/readback receipt is not a successful scheduled scan, trade, fill or performance claim.
