"""Exact v3 attempt proof plus real entry/reconciliation pipeline regressions."""
import copy
import hashlib
import importlib.util
import json
import unittest
from unittest.mock import patch
from offline_test_guard import install
install()
from test_opportunity_execution import ExecutionCase,NOW,_dossier
import autotrader
import sqlite_ledger as storage
import research_mode
import research_memory_transition as transition


class AuthorityTests(ExecutionCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('entry_authority'),'allowance-independent exact authority missing')
        import entry_authority
        return entry_authority

    def setUp(self):
        super().setUp()
        api=self.api()
        m=transition.prepare_manifest(self.root,source_revision='f'*40,rule_version='r1')
        transition.apply(self.root,m,approved_manifest_sha256=transition.manifest_digest(m))
        raw={k:v for k,v in self.candidate.items() if k not in {'dossier_hash','event_id','allowance_id','opportunity_identity'}}
        bound=api.bind_candidate(self.root,raw,context=research_mode.context(self.root))
        bound['dossier_hash']=_dossier(bound)
        api.validate_intake(self.root,bound)
        storage.append_jsonl(self.root/'candidates.jsonl',bound)
        self.candidate=bound
        self.proposal,errors=autotrader.build_canonical_proposal(bound,self.snapshot(),self.cfg,0)
        self.assertEqual(errors,[])

    def approve(self,evidence='e1',decision='APPROVE'):
        scores={k:5 for k in autotrader.RUBRIC_WEIGHTS[self.proposal['assigned_rubric']]}
        reviews=[dict(decision=decision,proposal_hash=self.proposal['proposal_hash'],fatal_flags=[],
                      reason_codes=[],component_scores=scores) for _ in range(2)]
        row=dict(dossier_hash=self.candidate['dossier_hash'],evidence_id=evidence,
                 proposal_hash=self.proposal['proposal_hash'],reviews=reviews,
                 research_transition_id=self.candidate['research_transition_id'])
        storage.append_jsonl(self.root/'private/reviews.jsonl',row)
        return row

    def test_persisted_exact_dual_approval_authorizes_only_exact_attempt(self):
        api=self.api();row=self.approve()
        proof=api.authorize_attempt(self.root,candidate=self.candidate,proposal=self.proposal,evidence_id='e1',review_ref=row)
        api.validate_attempt(self.root,candidate=self.candidate,proposal=self.proposal,evidence_id='e1',proof=proof)
        for changed in [dict(evidence_id='other'),dict(proposal={**self.proposal,'quantity':999}),
                        dict(candidate={**self.candidate,'symbol':'OTHER'}),dict(proof={})]:
            with self.subTest(changed=changed),self.assertRaises(RuntimeError):
                api.validate_attempt(self.root,**{**dict(candidate=self.candidate,proposal=self.proposal,evidence_id='e1',proof=proof),**changed})
        self.approve(evidence='late',decision='HOLD')
        with self.assertRaises(RuntimeError):api.validate_attempt(self.root,candidate=self.candidate,proposal=self.proposal,evidence_id='e1',proof=proof)

    def test_missing_approval_and_held_or_pending_truth_do_not_bypass_entry(self):
        api=self.api()
        with self.assertRaises(RuntimeError):api.authorize_attempt(self.root,candidate=self.candidate,proposal=self.proposal,evidence_id='e1',review_ref={})
        # Existing real predicate must stay active, including dust.
        held=self.held_row();held['qty']='0.001'
        errors=autotrader.buy_eligibility_errors(self.candidate['symbol'],self.snapshot(positions=[held]),root=self.root,now=NOW)
        self.assertIn('position_already_held',errors)

    def test_plain_dictionary_and_injected_transition_cannot_claim_intake(self):
        api=self.api()
        with self.assertRaises(RuntimeError):api.validate_intake(self.root,dict(self.candidate))
        with self.assertRaises(RuntimeError):api.bind_candidate(self.root,dict(self.candidate),context=research_mode.context(self.root))

    def test_stale_transition_and_mutated_candidate_are_not_durable_authority(self):
        api=self.api()
        with self.assertRaises(RuntimeError):api.validate_candidate(self.root,{**self.candidate,'research_transition_id':'rt3:'+'0'*64})
        forged={**self.candidate,'thesis':'changed'};forged['dossier_hash']=_dossier(forged)
        with self.assertRaises(RuntimeError):api.validate_candidate(self.root,forged)

    def test_v3_dust_and_missing_observation_stop_before_paid_review(self):
        held=self.held_row();held['qty']='0.001'
        code,output=self.run_locked(snapshot=self.snapshot(positions=[held]))
        self.assertNotEqual(code,0,output)
        self.assertEqual(self.reviewer_calls,[])
        self.assertNotIn('place',self.broker_operations)
        code,output=self.run_locked(snapshot=self.snapshot(observation={}))
        self.assertNotEqual(code,0,output)
        self.assertEqual(self.reviewer_calls,[])
        self.assertFalse((self.root/'private/order_intents.jsonl').exists())

    def test_v3_completed_hold_skips_before_paid_review(self):
        self.approve(decision='HOLD')
        code,output=self.run_locked()
        self.assertIn('already_reviewed',output)
        self.assertEqual(self.reviewer_calls,[])
        self.assertNotIn('place',self.broker_operations)

    def test_v3_low_confidence_reviews_cannot_mint_attempt(self):
        api=self.api();row=self.approve()
        # Preserve the original row; this completed low-confidence result is
        # a distinct exact review/evidence pair, never replacement approval.
        row['evidence_id']='low';row['reviews']=[{**r,'component_scores':{k:0 for k in r['component_scores']}} for r in row['reviews']]
        storage.append_jsonl(self.root/'private/reviews.jsonl',row)
        with self.assertRaises(RuntimeError):
            api.authorize_attempt(self.root,candidate=self.candidate,proposal=self.proposal,evidence_id='low',review_ref=row)

    def test_v3_real_entry_path_remains_operational_after_allowances_retired(self):
        code,output=self.run_locked()
        self.assertEqual(code,0,output)
        self.assertIn('place',self.broker_operations)
        self.assertEqual(self.broker_operations.count('place'),1)

    def test_fill_during_review_prevents_v3_submission(self):
        fresh=self.snapshot(positions=[self.held_row()])
        code,output=self.run_locked(fresh=fresh)
        self.assertNotEqual(code,0,output)
        self.assertNotIn('place',self.broker_operations)
        self.assertFalse((self.root/'private/order_intents.jsonl').exists())


if __name__=='__main__':unittest.main()
