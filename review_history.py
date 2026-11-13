"""Strict exact-dossier completed-review protection, independent of events."""
from pathlib import Path
import re
import sqlite_ledger as storage
from candidate_retry import pre_submission_retryable


class ReviewHistoryError(RuntimeError):pass


def validated_reviews(rows,dossier_hash):
    """Validate every relevant output before selecting current/prior attempts."""
    matching=[]
    for row in rows:
        if row.get('dossier_hash')!=dossier_hash:continue
        values=row.get('reviews')
        if (not isinstance(values,list)
                or (any(r is None for r in values) and len(values)!=2)
                or any(r is not None and not isinstance(r,dict) for r in values)):
            raise ReviewHistoryError('review_history_invalid')
        for value in values:
            # Reviewer-unavailable attempts retain both slots, including None.
            # Never filter them: current authority still requires dual approval.
            if value is None:continue
            if 'decision' in value:
                decision=value['decision']
                if not isinstance(decision,str) or not decision.strip() or decision!=decision.strip():
                    raise ReviewHistoryError('review_history_invalid')
            elif value.get('action') not in ('BUY','HOLD'):
                raise ReviewHistoryError('review_history_invalid')
        matching.append(row)
    return matching


def dossier_status(root:Path,dossier_hash:str)->str:
    if not isinstance(dossier_hash,str) or re.fullmatch(r'[0-9a-f]{64}',dossier_hash) is None:
        raise ReviewHistoryError('review_dossier_hash_invalid')
    root=Path(root)
    try:
        snap=storage.read_stream_snapshot_readonly(root,('private/reviews.jsonl','order_ledger.jsonl','private/order_intents.jsonl'))
        reviews=list(snap.rows['private/reviews.jsonl']);orders=list(snap.rows['order_ledger.jsonl'])
        matching=validated_reviews(reviews,dossier_hash);completed=False;legacy=False;orphan=False
        for row in matching:
            values=row['reviews']
            for value in values:
                # Only the missing slot is incomplete; any completed output
                # (including a lone APPROVE) conservatively spends the dossier.
                if value is None:continue
                decision=value.get('decision')
                old='decision' not in value and value.get('action') in ('BUY','HOLD')
                legacy=legacy or old
                completed=completed or old or bool(decision and decision not in {'reconciliation_blocked','execution_retryable'})
            orphan=orphan or values==[{'decision':'execution_retryable'}]
        ids={r.get('evidence_id') for r in matching if isinstance(r.get('evidence_id'),str)}
        for row in orders:
            if row.get('evidence_id') in ids or row.get('dossier_hash')==dossier_hash:
                if not isinstance(row.get('status'),str) or not row['status']:
                    raise ReviewHistoryError('review_order_history_invalid')
        if any(r.get('evidence_id') in ids or r.get('dossier_hash')==dossier_hash
                for r in snap.rows['private/order_intents.jsonl']):return 'completed'
        if not legacy and pre_submission_retryable(dossier_hash,reviews,root/'order_ledger.jsonl',ledger_rows=orders):
            return 'retryable'
        return 'completed' if completed or orphan else 'unreviewed'
    except ReviewHistoryError:raise
    except Exception as error:
        raise ReviewHistoryError('review_history_unavailable') from error
