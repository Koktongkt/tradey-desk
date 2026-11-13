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

    def test_malformed_matching_outputs_fail_closed_for_every_present_shape(self):
        api=self.api()
        for i,output in enumerate(({'decision':None},{'decision':''},{'decision':False},{}, {'action':'UNKNOWN'})):
            with self.subTest(output=output):
                dossier=f'{i:064x}';self.row([output],dossier_hash=dossier)
                with self.assertRaises(api.ReviewHistoryError):api.dossier_status(self.root,dossier)

    def test_two_reviewer_attempt_preserves_actual_null_placeholders(self):
        api=self.api()
        for values in ([None,None],[None,{'decision':'HOLD'}],[{'decision':'APPROVE'},None],
                       [None,{'action':'BUY'}],[{'action':'HOLD'},None]):
            with self.subTest(values=values):
                row={'dossier_hash':HASH,'reviews':values}
                matching=api.validated_reviews([row],HASH)
                self.assertIs(matching[0],row)
                self.assertIs(matching[0]['reviews'],values)
                self.assertEqual(matching[0]['reviews'],values)

    def test_nulls_do_not_relax_malformed_containers_or_outputs(self):
        api=self.api()
        for values in (None,{},(None,None),[None],[None,None,None],
                       [None,False],[0,None],['APPROVE',None],[None,[]],
                       [None,{'decision':None}],[None,{'decision':''}],
                       [None,{}],[None,{'action':'UNKNOWN'}]):
            with self.subTest(values=values),self.assertRaises(api.ReviewHistoryError):
                api.validated_reviews([{'dossier_hash':HASH,'reviews':values}],HASH)

    def test_unavailable_pair_is_unreviewed_without_rewriting_history(self):
        self.row([None,None])
        before=storage.read_jsonl_stream_readonly(self.root/'private/reviews.jsonl')
        self.assertEqual(self.status(),'unreviewed')
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root/'private/reviews.jsonl'),before)

    def test_partial_completed_outputs_spend_even_with_later_markers(self):
        for i,output in enumerate(({'decision':'HOLD'},{'decision':'DISAGREE'},
                                   {'decision':'APPROVE'},{'action':'BUY'},{'action':'HOLD'})):
            for j,values in enumerate(([None,output],[output,None])):
                dossier=f'{i*2+j:064x}'
                with self.subTest(values=values):
                    self.row(values,dossier_hash=dossier)
                    self.assertEqual(self.api().dossier_status(self.root,dossier),'completed')
                    self.row([None,None],dossier_hash=dossier)
                    for marker in ('reconciliation_blocked','execution_retryable'):
                        self.row([{'decision':marker}],dossier_hash=dossier)
                    self.assertEqual(self.api().dossier_status(self.root,dossier),'completed')

    def test_incomplete_pair_cannot_erase_prior_dissent_with_proven_retry(self):
        for i,output in enumerate(({'decision':'HOLD'},{'decision':'DISAGREE'},{'action':'HOLD'})):
            dossier=f'{i:064x}'
            with self.subTest(output=output):
                self.row([output],dossier_hash=dossier)
                self.row([None,None],dossier_hash=dossier)
                self.row([{'decision':'APPROVE'},{'decision':'APPROVE'}],dossier_hash=dossier)
                self.row([{'decision':'execution_retryable'}],dossier_hash=dossier)
                storage.append_jsonl(self.root/'order_ledger.jsonl',{
                    'evidence_id':'e1','status':'rejected','reason':['stale_quote']})
                self.assertEqual(self.api().dossier_status(self.root,dossier),'completed')

    def test_incomplete_attempt_does_not_hide_submission_intent(self):
        self.row([None,None])
        storage.append_jsonl(self.root/'private/order_intents.jsonl',{
            'client_order_id':'synthetic-lost-ack','evidence_id':'e1','dossier_hash':HASH})
        self.assertEqual(self.status(),'completed')

    def test_invalid_dossier_hash_is_not_not_reviewed(self):
        api=self.api()
        for bad in [None,'dossier-a','',False]:
            with self.subTest(bad=bad),self.assertRaises(api.ReviewHistoryError):api.dossier_status(self.root,bad)


if __name__=='__main__':unittest.main()
