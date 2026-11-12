"""Strict exact-dossier completed-review protection, independent of events."""
from pathlib import Path
import re
import sqlite_ledger as storage
from candidate_retry import pre_submission_retryable


class ReviewHistoryError(RuntimeError):pass


def dossier_status(root:Path,dossier_hash:str)->str:
    if not isinstance(dossier_hash,str) or re.fullmatch(r'[0-9a-f]{64}',dossier_hash) is None:
        raise ReviewHistoryError('review_dossier_hash_invalid')
    root=Path(root)
    try:
        snap=storage.read_stream_snapshot_readonly(root,('private/reviews.jsonl','order_ledger.jsonl'))
        reviews=list(snap.rows['private/reviews.jsonl']);orders=list(snap.rows['order_ledger.jsonl'])
        matching=[];completed=False;legacy=False;orphan=False
        for row in reviews:
            if row.get('dossier_hash')!=dossier_hash:continue
            values=row.get('reviews')
            if not isinstance(values,list) or any(not isinstance(r,dict) for r in values):
                raise ReviewHistoryError('review_history_invalid')
            for value in values:
                decision=value.get('decision')
                if decision is not None and (not isinstance(decision,str) or not decision):
                    raise ReviewHistoryError('review_history_invalid')
                old='decision' not in value and value.get('action') in ('BUY','HOLD')
                legacy=legacy or old
                completed=completed or old or bool(decision and decision not in {'reconciliation_blocked','execution_retryable'})
            orphan=orphan or values==[{'decision':'execution_retryable'}]
            matching.append(row)
        ids={r.get('evidence_id') for r in matching if isinstance(r.get('evidence_id'),str)}
        for row in orders:
            if row.get('evidence_id') in ids or row.get('dossier_hash')==dossier_hash:
                if not isinstance(row.get('status'),str) or not row['status']:
                    raise ReviewHistoryError('review_order_history_invalid')
        if not legacy and pre_submission_retryable(dossier_hash,reviews,root/'order_ledger.jsonl',ledger_rows=orders):
            return 'retryable'
        return 'completed' if completed or orphan else 'unreviewed'
    except ReviewHistoryError:raise
    except Exception as error:
        raise ReviewHistoryError('review_history_unavailable') from error
