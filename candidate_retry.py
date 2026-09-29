"""Fail-closed eligibility for retrying an approved dossier blocked before submission."""
from pathlib import Path
from durable_jsonl import read_jsonl

# Only reversible broker/market-condition failures may reuse an approved dossier.
RETRYABLE_EXECUTION_REASONS = frozenset({
    "liquidity_failed", "spread_too_wide", "unknown_spread",
    "consolidated_volume_unavailable", "quote_feed_unavailable",
    "limit_price_too_far_from_quote", "stale_quote", "quote_timestamp_unknown",
    "unknown_cash", "insufficient_cash", "unknown_buying_power",
    "insufficient_buying_power",
})


def pre_submission_retryable(dossier_hash: str, reviews: list[dict], ledger_path: Path) -> bool:
    """Require an explicit retry marker, dual approval and a rejected order ledger.

    Any submission or uncertain broker state for this dossier makes reuse unsafe.
    Missing or malformed ledgers cannot authorize a retry.
    """
    if not isinstance(dossier_hash, str) or not dossier_hash:
        return False
    matching = [r for r in reviews if isinstance(r, dict) and r.get("dossier_hash") == dossier_hash]
    if len(matching) < 2:
        return False
    # A completed dissent spends this exact dossier permanently, even if a
    # later reconciliation marker accidentally permits another review.
    for row in matching:
        decisions = row.get("reviews")
        if isinstance(decisions, list) and any(
            isinstance(review, dict) and (
                review.get("decision") not in
                {None, "APPROVE", "reconciliation_blocked", "execution_retryable"}
                or bool(review.get("fatal_flags"))
            ) for review in decisions
        ):
            return False
    marker, approval = matching[-1], matching[-2]
    evidence_id = marker.get("evidence_id")
    if (not isinstance(evidence_id, str) or not evidence_id
            or approval.get("evidence_id") != evidence_id
            or marker.get("reviews") != [{"decision": "execution_retryable"}]):
        return False
    decisions = approval.get("reviews")
    if (not isinstance(decisions, list) or len(decisions) != 2
            or any(not isinstance(r, dict) or r.get("decision") != "APPROVE" for r in decisions)):
        return False
    ids = {r.get("evidence_id") for r in matching if isinstance(r.get("evidence_id"), str)}
    try:
        ledger = read_jsonl(ledger_path, strict=True)
    except Exception:
        return False
    linked = [r for r in ledger if isinstance(r, dict) and r.get("evidence_id") in ids]
    if not linked or any(r.get("status") not in {"proposed", "rejected"} for r in linked):
        return False
    # Every completed review in the history must have its own immediate,
    # proven pre-submission rejection. A reconciliation marker cannot erase it.
    for index, row in enumerate(matching):
        decisions = row.get("reviews")
        if decisions == [{"decision": "execution_retryable"}] or decisions == [{"decision": "reconciliation_blocked"}]:
            continue
        if not isinstance(decisions, list) or not any(isinstance(r, dict) and r.get("decision") for r in decisions):
            continue
        if (len(decisions) != 2 or any(not isinstance(r, dict) or r.get("decision") != "APPROVE"
                                         or bool(r.get("fatal_flags")) for r in decisions)
                or index + 1 >= len(matching)):
            return False
        next_row = matching[index + 1]
        review_id = row.get("evidence_id")
        if (not isinstance(review_id, str) or not review_id
                or next_row.get("evidence_id") != review_id
                or next_row.get("reviews") != [{"decision": "execution_retryable"}]):
            return False
        history = [r for r in linked if r.get("evidence_id") == review_id]
        if (not history or history[-1].get("status") != "rejected"
                or not isinstance(history[-1].get("reason"), list)
                or not history[-1]["reason"]
                or not all(isinstance(reason, str) and reason in RETRYABLE_EXECUTION_REASONS
                           for reason in history[-1]["reason"])):
            return False
    last = [r for r in linked if r.get("evidence_id") == evidence_id]
    if not last or last[-1].get("status") != "rejected":
        return False
    reasons = last[-1].get("reason")
    return (isinstance(reasons, list) and bool(reasons)
            and all(isinstance(reason, str) and reason in RETRYABLE_EXECUTION_REASONS
                    for reason in reasons))
