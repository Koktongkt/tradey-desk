"""Strict exact-dossier memory including legacy outputs, never event matching."""
import importlib.util
import tempfile
from pathlib import Path
import unittest
from offline_test_guard import install
install()
import sqlite_ledger as storage

HASH='a'*64


class ReviewHistoryTests(unittest.TestCase):
    def setUp(self):self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('review_history'),'strict review-history reader missing')
        import review_history
        return review_history
    def row(self,reviews,**extra):
        row=dict(dossier_hash=HASH,evidence_id='e1',reviews=reviews);row.update(extra)
        storage.append_jsonl(self.root/'private/reviews.jsonl',row)
    def status(self):return self.api().dossier_status(self.root,HASH)
    def test_modern_and_legacy_completions_survive_markers(self):
        for review in [{'decision':'HOLD'},{'decision':'DISAGREE'},{'action':'BUY'},{'action':'HOLD'}]:
            with self.subTest(review=review):
                self.row([review]);self.row([{'decision':'execution_retryable'}])
                self.assertEqual(self.status(),'completed')
    def test_empty_and_hashless_history_do_not_ban_a_symbol(self):
        storage.append_jsonl(self.root/'private/reviews.jsonl',{'symbol':'ABC','reviews':[{'action':'HOLD'}]})
        self.row([]);self.assertEqual(self.status(),'unreviewed')
        self.row([{'decision':'HOLD'}]);self.assertEqual(self.status(),'completed')
    def test_exact_approved_pre_submission_rejection_is_retryable(self):
        self.row([{'decision':'APPROVE'},{'decision':'APPROVE'}]);self.row([{'decision':'execution_retryable'}])
        storage.append_jsonl(self.root/'order_ledger.jsonl',{'evidence_id':'e1','status':'rejected','reason':['stale_quote']})
        self.assertEqual(self.status(),'retryable')
        storage.append_jsonl(self.root/'order_ledger.jsonl',{'evidence_id':'e1','status':'submission_started'})
        self.assertEqual(self.status(),'completed')
    def test_lost_ack_intent_blocks_pre_submission_retry_without_ledger_status(self):
        self.row([{'decision':'APPROVE'},{'decision':'APPROVE'}]);self.row([{'decision':'execution_retryable'}])
        storage.append_jsonl(self.root/'order_ledger.jsonl',{'evidence_id':'e1','status':'rejected','reason':['stale_quote']})
        self.assertEqual(self.status(),'retryable')
        storage.append_jsonl(self.root/'private/order_intents.jsonl',{'client_order_id':'lost-ack','evidence_id':'e1','dossier_hash':HASH})
        self.assertEqual(self.status(),'completed')

    def test_earlier_legacy_completion_cannot_be_erased_by_approval_retry(self):
        self.row([{'action':'HOLD'}]);self.row([{'decision':'APPROVE'},{'decision':'APPROVE'}])
        self.row([{'decision':'execution_retryable'}])
        storage.append_jsonl(self.root/'order_ledger.jsonl',{'evidence_id':'e1','status':'rejected','reason':['stale_quote']})
        self.assertEqual(self.status(),'completed')
    def test_missing_proof_or_orphan_retry_marker_is_completed(self):
        self.row([{'decision':'APPROVE'},{'decision':'APPROVE'}]);self.row([{'decision':'execution_retryable'}])
        self.assertEqual(self.status(),'completed')
    def test_malformed_matching_review_and_corrupt_storage_fail_closed(self):
        api=self.api();self.row('not-review-list')
        with self.assertRaises(api.ReviewHistoryError):self.status()
        (self.root/'private/reviews.jsonl').write_text('broken-json\n')
        with self.assertRaises(api.ReviewHistoryError):self.status()
    def test_v3_autotrader_adapter_refuses_corrupt_review_history(self):
        import json
        import opportunity_fixtures as f
        import research_memory_transition as transition
        f.make_root(self.root)
        (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':[]}))
        m=transition.prepare_manifest(self.root,source_revision='f'*40,rule_version='r1')
        transition.apply(self.root,m,approved_manifest_sha256=transition.manifest_digest(m))
        self.row('not-review-list')
        import autotrader
        with self.assertRaises(Exception):
            autotrader.dossier_already_reviewed({'dossier_hash':HASH},self.root/'private/reviews.jsonl')

    def test_invalid_dossier_hash_is_not_not_reviewed(self):
        api=self.api()
        for bad in [None,'dossier-a','',False]:
            with self.subTest(bad=bad),self.assertRaises(api.ReviewHistoryError):api.dossier_status(self.root,bad)


if __name__=='__main__':unittest.main()
