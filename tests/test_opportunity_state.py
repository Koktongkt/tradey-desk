"""Synthetic state/allowance policy tests; no operational roots or live effects."""
import tempfile
import unittest
from pathlib import Path

import opportunity_fixtures as fixtures
import sqlite_ledger as storage

POLICY = 'private/opportunity_policy.jsonl'
REVIEWS = 'private/reviews.jsonl'
CANDIDATES = 'candidates.jsonl'
DOSSIER_A = 'a' * 64
DOSSIER_B = 'b' * 64
PROPOSAL_1 = 'p' * 64
PROPOSAL_2 = 'q' * 64
EVIDENCE_1 = 'evidence-1'
EVIDENCE_2 = 'evidence-2'


class OpportunityStateTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)

    def write(self, name, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        for row in rows:
            storage.append_jsonl(path, row)

    def build(self, *, period='2026-Q3'):
        """Activated history with one bound dossier and no completed reviews."""
        import opportunity_state as state
        resolution = fixtures.synthetic_resolution(period=period)
        self.write(POLICY, [
            fixtures.policy_row('activation', policy_version=1, manifest_sha256='a' * 64),
            fixtures.policy_row('identity_resolution',
                                resolution=fixtures.synthetic_resolution_payload(period=period)),
        ])
        self.write(CANDIDATES, [
            fixtures.candidate_link(DOSSIER_A, resolution.event_id,
                                    state.allowance_identifier(resolution.event_id, 0)),
        ])
        return resolution

    def approve(self, resolution, *, dossier_hash=DOSSIER_A, evidence_id=EVIDENCE_1,
                proposal_hash=PROPOSAL_1):
        import opportunity_state as state
        self.write(REVIEWS, [
            fixtures.review_row(dossier_hash, evidence_id,
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash=proposal_hash),
        ])
        return state.allowance_identifier(resolution.event_id, 0)

    def test_new_dossier_cannot_erase_same_event_hold(self):
        import opportunity_state as state
        resolution = self.build()
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                [{'decision': 'HOLD'}, {'decision': 'HOLD'}]),
        ])
        index = state.load_index(self.root)
        result = state.event_decision(index, resolution,
                                      dossier_hash=DOSSIER_B)
        self.assertEqual((result.outcome, result.reason), ('skip', 'unchanged_opportunity'))

    def test_unbound_dossier_missing_binding_cannot_be_eligible(self):
        import opportunity_state as state
        resolution = self.build()
        index = state.load_index(self.root)
        result = state.event_decision(index, resolution, dossier_hash='c' * 64)
        self.assertEqual((result.outcome, result.reason),
                         ('unknown', 'dossier_binding_missing'))

    def test_current_attempt_authorizes_only_its_own_exact_proposal(self):
        import opportunity_state as state
        resolution = self.build()
        allowance = self.approve(resolution)
        index = state.load_index(self.root)
        attempt = state.authorize_current_attempt(
            index, dossier_hash=DOSSIER_A, proposal_hash=PROPOSAL_1,
            evidence_id=EVIDENCE_1)
        self.assertEqual(attempt.allowance_id, allowance)
        own = state.event_decision(index, resolution, dossier_hash=DOSSIER_A,
                                   current_attempt=attempt)
        self.assertEqual((own.outcome, own.reason), ('eligible', 'current_attempt_authorized'))
        # The same approval cannot be borrowed for another dossier or proposal.
        import dataclasses
        borrowed = state.event_decision(index, resolution, dossier_hash=DOSSIER_B,
                                        current_attempt=attempt)
        self.assertEqual((borrowed.outcome, borrowed.reason),
                         ('skip', 'current_attempt_unauthorized'))
        forged = dataclasses.replace(attempt, proposal_hash=PROPOSAL_2)
        for dossier in (DOSSIER_B, DOSSIER_A):
            with self.subTest(dossier=dossier):
                result = state.event_decision(index, resolution,
                                              dossier_hash=dossier,
                                              current_attempt=forged)
                self.assertEqual((result.outcome, result.reason),
                                 ('skip', 'current_attempt_unauthorized'))
        with self.assertRaises(state.OpportunityStateError):
            state.authorize_current_attempt(
                index, dossier_hash=DOSSIER_A, proposal_hash=PROPOSAL_2,
                evidence_id=EVIDENCE_1)
        with self.assertRaises(state.OpportunityStateError):
            state.authorize_current_attempt(
                index, dossier_hash=DOSSIER_A, proposal_hash=PROPOSAL_1,
                evidence_id=EVIDENCE_2)

    def test_empty_and_reconciliation_only_reviews_do_not_spend(self):
        import opportunity_state as state
        resolution = self.build()
        self.write(CANDIDATES, [
            fixtures.candidate_link(DOSSIER_B, resolution.event_id,
                                    state.allowance_identifier(resolution.event_id, 0)),
        ])
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1, []),
            fixtures.review_row(DOSSIER_A, EVIDENCE_2,
                                [{'decision': 'reconciliation_blocked'}]),
        ])
        index = state.load_index(self.root)
        with self.assertRaises(state.OpportunityStateError):
            state.authorize_current_attempt(
                index, dossier_hash=DOSSIER_A, proposal_hash=PROPOSAL_1,
                evidence_id=EVIDENCE_1)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B)
        self.assertEqual((result.outcome, result.reason),
                         ('eligible', 'allowance_available'))

    def test_unknown_and_conflict_identity_cannot_be_eligible(self):
        import opportunity_state as state
        from opportunity_identity import EventResolution
        self.build()
        index = state.load_index(self.root)
        for status, reason in (('unknown', 'opportunity_identity_unknown'),
                               ('conflict', 'opportunity_identity_conflict')):
            with self.subTest(status=status):
                resolution = EventResolution(status, None, None, None, None, (), (), 'x')
                result = state.event_decision(index, resolution)
                self.assertEqual((result.outcome, result.reason), ('unknown', reason))

    def test_missing_event_binding_cannot_be_eligible(self):
        import opportunity_state as state
        self.build()
        index = state.load_index(self.root)
        result = state.event_decision(index, fixtures.synthetic_resolution(period='2026-Q1'))
        self.assertEqual((result.outcome, result.reason), ('unknown', 'event_binding_missing'))

    def test_unactivated_policy_stream_is_not_permission(self):
        import opportunity_state as state
        resolution = fixtures.synthetic_resolution()
        index = state.load_index(self.root)
        result = state.event_decision(index, resolution)
        self.assertEqual((result.outcome, result.reason),
                         ('unknown', 'policy_not_activated'))

    def test_corrupt_and_lagging_state_are_typed_failures(self):
        import json
        import opportunity_state as state
        self.build()
        # Lagging projection: an external legacy append ahead of SQLite history.
        with (self.root / POLICY).open('a', encoding='utf-8') as stream:
            stream.write(json.dumps(fixtures.policy_row(
                'activation', policy_version=2, manifest_sha256='a' * 64)) + '\n')
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)
        # Corrupt canonical projection: a typed failure, not an empty registry.
        (self.root / POLICY).write_text('{"record_type": "activation"\n', encoding='utf-8')
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)

    def test_unresolved_historical_dossier_is_not_eligible(self):
        import opportunity_state as state
        resolution = self.build()
        self.write(POLICY, [
            fixtures.policy_row('identity_resolution',
                                unresolved={'dossier_hash': DOSSIER_B,
                                            'status': 'unknown', 'reason': 'no_history'}),
        ])
        index = state.load_index(self.root)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B)
        self.assertEqual((result.outcome, result.reason),
                         ('unknown', 'historical_binding_missing'))

    def test_crash_after_review_append_still_spends_event(self):
        import opportunity_state as state
        resolution = self.build()
        index = state.load_index(self.root)
        # Simulated crash window: the review is durably appended, but the policy
        # index was never rebuilt. The decision must still see the spending row.
        self.approve(resolution)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B)
        self.assertEqual((result.outcome, result.reason), ('skip', 'unchanged_opportunity'))

    def test_explicit_grant_supplies_next_generation_allowance(self):
        import opportunity_state as state
        resolution = self.build()
        first = state.allowance_identifier(resolution.event_id, 0)
        second = state.allowance_identifier(resolution.event_id, 1)
        self.write(POLICY, [
            fixtures.policy_row('reopen_grant', event_id=resolution.event_id,
                                prior_allowance_id=first, allowance_id=second,
                                generation=1),
        ])
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash=PROPOSAL_1),
            fixtures.review_row(DOSSIER_A, EVIDENCE_2,
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash=PROPOSAL_2),
        ])
        self.write(CANDIDATES, [
            fixtures.candidate_link(DOSSIER_A, resolution.event_id, second),
        ])
        index = state.load_index(self.root)
        attempt = state.authorize_current_attempt(
            index, dossier_hash=DOSSIER_A, proposal_hash=PROPOSAL_2,
            evidence_id=EVIDENCE_2)
        self.assertEqual(attempt.allowance_id, second)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_A,
                                      current_attempt=attempt)
        self.assertEqual((result.outcome, result.reason),
                         ('eligible', 'current_attempt_authorized'))

    def test_broken_chain_grant_is_a_typed_failure(self):
        import opportunity_state as state
        resolution = self.build()
        self.write(POLICY, [
            fixtures.policy_row('reopen_grant', event_id=resolution.event_id,
                                prior_allowance_id='oa1:' + '0' * 64,
                                allowance_id=state.allowance_identifier(
                                    resolution.event_id, 1),
                                generation=1),
        ])
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)

    def test_unsealed_reopening_claim_never_authorizes(self):
        import opportunity_state as state
        from opportunity_state import ConditionObservation, ReopeningClaim
        import datetime as dt
        resolution = self.build()
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1, [{'decision': 'HOLD'}]),
        ])
        index = state.load_index(self.root)
        observation = ConditionObservation(
            event_id=resolution.event_id, metric='synthetic_metric', value=1,
            units='units', source_kind='synthetic',
            observed_at=dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc),
            evidence_ref='private/opportunity_evidence/' + 'b' * 64 + '.json',
            seal=None)
        claim = ReopeningClaim(condition_id='cond-1',
                               prior_allowance_id=state.allowance_identifier(
                                   resolution.event_id, 0),
                               observation=observation, seal=None)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B,
                                      reopening_claim=claim)
        self.assertEqual(result.outcome, 'skip')

    def test_candidate_retry_supplied_rows_use_exact_unchanged_proof(self):
        import candidate_retry
        self.build()
        # Exact retry proof: approval pair, retry marker, then a rejected
        # retryable order outcome for the same evidence.
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash=PROPOSAL_1),
            fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                [{'decision': 'execution_retryable'}]),
        ])
        self.write('order_ledger.jsonl', [
            {'timestamp': '2026-11-04T12:00:00Z', 'evidence_id': EVIDENCE_1,
             'status': 'proposed'},
            {'timestamp': '2026-11-04T12:00:01Z', 'evidence_id': EVIDENCE_1,
             'status': 'rejected', 'reason': ['stale_quote']},
        ])
        reviews = storage.read_jsonl_stream_readonly(self.root / REVIEWS)
        ledger_rows = storage.read_jsonl_stream_readonly(
            self.root / 'order_ledger.jsonl')
        path = self.root / 'order_ledger.jsonl'
        supplied = candidate_retry.pre_submission_retryable(
            DOSSIER_A, reviews, path, ledger_rows=ledger_rows)
        reader = candidate_retry.pre_submission_retryable(DOSSIER_A, reviews, path)
        self.assertTrue(reader)
        self.assertEqual(supplied, reader, 'supplied rows must follow the exact proof')
        # Without the immediate pre-submission rejection the proof fails on
        # supplied rows exactly as it does through the ordinary reader.
        self.assertFalse(candidate_retry.pre_submission_retryable(
            DOSSIER_A, reviews, path, ledger_rows=[
                {'timestamp': '2026-11-04T12:00:00Z', 'evidence_id': EVIDENCE_1,
                 'status': 'proposed'}]))

    def test_snapshot_watermark_coherence_and_no_writes(self):
        import opportunity_state as state
        resolution = self.build()
        index = state.load_index(self.root)
        before = {name: path.stat().st_mtime_ns for name, path in (
            (POLICY, self.root / POLICY), (CANDIDATES, self.root / CANDIDATES))}
        reloaded = state.event_decision(index, resolution, dossier_hash=DOSSIER_A)
        self.assertEqual((reloaded.outcome, reloaded.reason),
                         ('eligible', 'allowance_available'))
        after = {name: path.stat().st_mtime_ns for name, path in (
            (POLICY, self.root / POLICY), (CANDIDATES, self.root / CANDIDATES))}
        self.assertEqual(before, after)


if __name__ == '__main__':
    unittest.main()
