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
        from unittest.mock import patch
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.sendto', 'socket.socket.sendmsg',
                       'socket.getaddrinfo', 'socket.gethostbyname',
                       'socket.gethostbyname_ex', 'socket.gethostbyaddr',
                       'urllib.request.urlopen'):
            self.enterContext(patch(target, side_effect=AssertionError('synthetic network forbidden')))
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
            fixtures.review_row(DOSSIER_B, EVIDENCE_2,
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash=PROPOSAL_2),
        ])
        self.write(CANDIDATES, [
            fixtures.candidate_link(DOSSIER_B, resolution.event_id, second),
        ])
        index = state.load_index(self.root)
        attempt = state.authorize_current_attempt(
            index, dossier_hash=DOSSIER_B, proposal_hash=PROPOSAL_2,
            evidence_id=EVIDENCE_2)
        self.assertEqual(attempt.allowance_id, second)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B,
                                      current_attempt=attempt)
        self.assertEqual((result.outcome, result.reason),
                         ('eligible', 'current_attempt_authorized'))

    def test_forward_rebind_rejects_relocation_of_old_review(self):
        import opportunity_state as state
        resolution = self.build()
        self.approve(resolution)
        first = state.allowance_identifier(resolution.event_id, 0)
        second = state.allowance_identifier(resolution.event_id, 1)
        self.write(POLICY, [fixtures.policy_row(
            'reopen_grant', event_id=resolution.event_id, generation=1,
            prior_allowance_id=first, allowance_id=second)])
        before = storage.read_jsonl_stream_readonly(self.root / REVIEWS)
        self.write(CANDIDATES, [fixtures.candidate_link(DOSSIER_A, resolution.event_id, second)])
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root / REVIEWS), before)

    def test_backward_rebind_cannot_erase_current_generation_spending(self):
        import opportunity_state as state
        resolution = self.build()
        first = state.allowance_identifier(resolution.event_id, 0)
        second = state.allowance_identifier(resolution.event_id, 1)
        self.write(REVIEWS, [fixtures.review_row(DOSSIER_A, EVIDENCE_1, [{'decision': 'HOLD'}])])
        self.write(POLICY, [fixtures.policy_row(
            'reopen_grant', event_id=resolution.event_id, generation=1,
            prior_allowance_id=first, allowance_id=second)])
        link = fixtures.candidate_link(DOSSIER_B, resolution.event_id, second)
        self.write(CANDIDATES, [link, link])  # Exact replay is idempotent.
        self.assertEqual(state.event_decision(state.load_index(self.root), resolution).outcome, 'eligible')
        self.write(REVIEWS, [fixtures.review_row(DOSSIER_B, EVIDENCE_2, [{'decision': 'HOLD'}])])
        index = state.load_index(self.root)
        self.assertEqual(len(index.allowance_reviews[second]), 1)
        self.assertEqual(state.event_decision(index, resolution).outcome, 'skip')
        before = storage.read_jsonl_stream_readonly(self.root / REVIEWS)
        self.write(CANDIDATES, [fixtures.candidate_link(DOSSIER_B, resolution.event_id, first)])
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root / REVIEWS), before)

    def test_grant_opens_only_current_generation_and_new_hold_spends_it(self):
        import opportunity_state as state
        resolution = self.build()
        first = state.allowance_identifier(resolution.event_id, 0)
        second = state.allowance_identifier(resolution.event_id, 1)
        dissent = fixtures.review_row(DOSSIER_A, EVIDENCE_1, [{'decision': 'HOLD'}])
        self.write(REVIEWS, [dissent])
        stale = state.load_index(self.root)
        self.assertEqual(state.event_decision(stale, resolution).outcome, 'skip')
        self.write(POLICY, [fixtures.policy_row(
            'reopen_grant', event_id=resolution.event_id, generation=1,
            prior_allowance_id=first, allowance_id=second)])
        # A genuinely new canonical dossier, not a rewrite/rebind of old history.
        self.write(CANDIDATES, [fixtures.candidate_link(
            DOSSIER_B, resolution.event_id, second)])
        for dossier in (None, DOSSIER_B):
            with self.subTest(dossier=dossier):
                decision = state.event_decision(stale, resolution, dossier_hash=dossier)
                self.assertEqual((decision.outcome, decision.reason, decision.allowance_id),
                                 ('eligible', 'allowance_available', second))
        # Later markers/approval on the old generation cannot spend the new one.
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, 'old-approval',
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash=PROPOSAL_1),
            fixtures.review_row(DOSSIER_A, 'old-approval', [{'decision': 'execution_retryable'}]),
        ])
        self.assertEqual(state.event_decision(stale, resolution,
                                              dossier_hash=DOSSIER_B).outcome, 'eligible')
        old = state.event_decision(stale, resolution, dossier_hash=DOSSIER_A)
        self.assertEqual((old.outcome, old.reason), ('unknown', 'dossier_binding_missing'))
        current = state.load_index(self.root)
        self.assertEqual(current.dossier_allowances[DOSSIER_A], first)
        self.assertEqual(current.allowance_reviews[first][0], dissent)
        self.write(REVIEWS, [fixtures.review_row(
            DOSSIER_B, EVIDENCE_2, [{'decision': 'HOLD'}])])
        self.write(CANDIDATES, [fixtures.candidate_link(
            'c' * 64, resolution.event_id, second)])
        for dossier in (None, DOSSIER_B, 'c' * 64):
            with self.subTest(spent_dossier=dossier):
                decision = state.event_decision(current, resolution, dossier_hash=dossier)
                self.assertEqual((decision.outcome, decision.reason, decision.allowance_id),
                                 ('skip', 'unchanged_opportunity', second))

    def test_later_approval_markers_and_new_dossier_do_not_advance_generation(self):
        import opportunity_state as state
        resolution = self.build()
        first = state.allowance_identifier(resolution.event_id, 0)
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1, [{'decision': 'HOLD'}]),
            fixtures.review_row(DOSSIER_A, EVIDENCE_2,
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash=PROPOSAL_2),
            fixtures.review_row(DOSSIER_A, EVIDENCE_2, [{'decision': 'execution_retryable'}]),
        ])
        self.write(CANDIDATES, [fixtures.candidate_link(DOSSIER_B, resolution.event_id, first)])
        decision = state.event_decision(state.load_index(self.root), resolution,
                                        dossier_hash=DOSSIER_B)
        self.assertEqual((decision.outcome, decision.reason, decision.allowance_id),
                         ('skip', 'unchanged_opportunity', first))

    def test_new_generation_approval_is_an_exact_attempt_not_research_refill(self):
        import opportunity_state as state
        resolution = self.build()
        self.approve(resolution)
        index = state.load_index(self.root)
        prior_attempt = state.authorize_current_attempt(
            index, dossier_hash=DOSSIER_A, proposal_hash=PROPOSAL_1, evidence_id=EVIDENCE_1)
        second = state.allowance_identifier(resolution.event_id, 1)
        self.write(POLICY, [fixtures.policy_row(
            'reopen_grant', event_id=resolution.event_id, generation=1,
            prior_allowance_id=state.allowance_identifier(resolution.event_id, 0),
            allowance_id=second)])
        self.write(CANDIDATES, [fixtures.candidate_link(DOSSIER_B, resolution.event_id, second)])
        self.approve(resolution, dossier_hash=DOSSIER_B,
                     evidence_id=EVIDENCE_2, proposal_hash=PROPOSAL_2)
        current = state.load_index(self.root)
        rejected = state.event_decision(current, resolution, dossier_hash=DOSSIER_A,
                                        current_attempt=prior_attempt)
        self.assertEqual(rejected.reason, 'current_attempt_unauthorized')
        attempt = state.authorize_current_attempt(
            current, dossier_hash=DOSSIER_B, proposal_hash=PROPOSAL_2, evidence_id=EVIDENCE_2)
        own = state.event_decision(current, resolution, dossier_hash=DOSSIER_B,
                                   current_attempt=attempt)
        self.assertEqual((own.outcome, own.reason, own.allowance_id),
                         ('eligible', 'current_attempt_authorized', second))
        borrowed = state.event_decision(current, resolution, dossier_hash=DOSSIER_A,
                                        current_attempt=attempt)
        self.assertEqual(borrowed.reason, 'current_attempt_unauthorized')
        spent = state.event_decision(current, resolution, dossier_hash=DOSSIER_B)
        self.assertEqual((spent.outcome, spent.reason), ('skip', 'unchanged_opportunity'))

    def test_grant_cannot_skip_a_missing_generation(self):
        import opportunity_state as state
        resolution = self.build()
        self.write(POLICY, [fixtures.policy_row(
            'reopen_grant', event_id=resolution.event_id, generation=2,
            prior_allowance_id=state.allowance_identifier(resolution.event_id, 1),
            allowance_id=state.allowance_identifier(resolution.event_id, 2))])
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)

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
        from decimal import Decimal
        resolution = self.build()
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1, [{'decision': 'HOLD'}]),
        ])
        index = state.load_index(self.root)
        observation = ConditionObservation(
            event_id=resolution.event_id, metric='synthetic_metric',
            value=Decimal('1'),
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

    def test_condition_observation_value_is_decimal_typed(self):
        import datetime as dt
        from decimal import Decimal
        from opportunity_state import ConditionObservation
        observation = ConditionObservation(
            event_id='event', metric='m', value=Decimal('1.25'), units='u',
            source_kind='synthetic',
            observed_at=dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc),
            evidence_ref='private/opportunity_evidence/' + 'b' * 64 + '.json',
            seal=None)
        self.assertEqual(observation.value, Decimal('1.25'))
        # Non-numeric persisted values fail closed at validation, not later.
        for bad in (1, 1.25, '1.25', None):
            with self.subTest(value=bad):
                with self.assertRaises(ValueError):
                    ConditionObservation(
                        event_id='event', metric='m', value=bad, units='u',
                        source_kind='synthetic',
                        observed_at=dt.datetime(2026, 11, 4, tzinfo=dt.timezone.utc),
                        evidence_ref='private/opportunity_evidence/' + 'b' * 64 + '.json',
                        seal=None)

    def test_attempt_seal_covers_full_index_state(self):
        import tempfile
        import opportunity_state as state
        base_root = self.root
        additions = [
            fixtures.policy_row('document_alias', alias='synthetic-alias',
                                event_id=fixtures.synthetic_resolution().event_id),
            fixtures.policy_row('condition_approval', condition_id='cond-1',
                                event_id=fixtures.synthetic_resolution().event_id,
                                condition={'metric': 'synthetic_metric'}),
            fixtures.policy_row('identity_resolution',
                                unresolved={'dossier_hash': DOSSIER_B,
                                            'status': 'unknown', 'reason': 'no_history'}),
        ]
        for row in additions:
            with self.subTest(record=row['record_type']):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                self.root = Path(temporary.name)
                resolution = self.build()
                self.approve(resolution)
                index = state.load_index(self.root)
                attempt = state.authorize_current_attempt(
                    index, dossier_hash=DOSSIER_A, proposal_hash=PROPOSAL_1,
                    evidence_id=EVIDENCE_1)
                own = state.event_decision(index, resolution, dossier_hash=DOSSIER_A,
                                           current_attempt=attempt)
                self.assertEqual(own.outcome, 'eligible')
                # A policy record appended after authorization must invalidate
                # the previously issued attempt seal (exact index state).
                self.write(POLICY, [row])
                fresh = state.load_index(self.root)
                result = state.event_decision(fresh, resolution, dossier_hash=DOSSIER_A,
                                              current_attempt=attempt)
                self.assertEqual((result.outcome, result.reason),
                                 ('skip', 'current_attempt_unauthorized'))
        self.root = base_root

    def test_snapshot_watermark_coherence_and_no_writes(self):
        import opportunity_state as state
        resolution = self.build()
        index = state.load_index(self.root)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob('*') if path.is_file()}
        reloaded = state.event_decision(index, resolution, dossier_hash=DOSSIER_A)
        self.assertEqual((reloaded.outcome, reloaded.reason),
                         ('eligible', 'allowance_available'))
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)


    def _row_digest(self, row) -> str:
        import hashlib
        import json
        return hashlib.sha256(json.dumps(
            row, sort_keys=True, separators=(',', ':'),
            ensure_ascii=False).encode('utf-8')).hexdigest()

    def _gap_record_for(self, root, stream, sequence, *, kind, **overrides):
        snapshot = storage.read_stream_snapshot_readonly(
            root, ('private/reviews.jsonl', 'trade_journal.jsonl'))
        row = snapshot.rows[stream][sequence - 1]
        record = fixtures.missing_history_row(
            kind=kind,
            source={'stream': stream, 'sequence': sequence,
                    'row_sha256': self._row_digest(row)},
            observed_fields=sorted(row),
            **overrides)
        return record

    def test_gap_source_row_accepts_both_migration_streams(self):
        import tempfile
        import opportunity_state as state
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixtures.make_gap_root(Path(temporary.name), review_gaps=1,
                                      hint_rows=0, buy_gaps=1, sell_rows=0)
        snapshot = storage.read_stream_snapshot_readonly(
            root, ('private/reviews.jsonl', 'trade_journal.jsonl'))
        review = state._gap_source_row(
            {'stream': 'private/reviews.jsonl', 'sequence': 1,
             'row_sha256': self._row_digest(snapshot.rows['private/reviews.jsonl'][0])},
            snapshot.rows)
        self.assertEqual(review['evidence_id'], 'gap-review-0')
        trade = state._gap_source_row(
            {'stream': 'trade_journal.jsonl', 'sequence': 1,
             'row_sha256': self._row_digest(snapshot.rows['trade_journal.jsonl'][0])},
            snapshot.rows)
        self.assertEqual((trade['action'], trade['symbol']), ('BUY', 'ZZZSYNB0'))

    def test_gap_source_digest_mutation_fails_on_reviews(self):
        import opportunity_state as state
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'manifest_source_digest_mismatch'):
            state._gap_source_row(
                {'stream': 'private/reviews.jsonl', 'sequence': 1,
                 'row_sha256': 'e' * 64},
                {'private/reviews.jsonl': (fixtures.gap_review_row(
                    with_symbol=True, with_hint=False),)})

    def test_gap_source_digest_mutation_fails_on_trade_journal(self):
        import opportunity_state as state
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'manifest_source_digest_mismatch'):
            state._gap_source_row(
                {'stream': 'trade_journal.jsonl', 'sequence': 3,
                 'row_sha256': 'e' * 64},
                {'trade_journal.jsonl': (
                    fixtures.gap_trade_row(action='BUY'),) * 3})

    def test_gap_source_outside_migration_streams_fails(self):
        import opportunity_state as state
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'invalid_manifest_source_reference'):
            state._gap_source_row(
                {'stream': 'candidates.jsonl', 'sequence': 1,
                 'row_sha256': 'e' * 64}, {'candidates.jsonl': ({},)})

    def test_source_row_still_rejects_trade_journal(self):
        import opportunity_state as state
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'invalid_manifest_source_reference'):
            state._source_row(
                {'stream': 'trade_journal.jsonl', 'sequence': 1,
                 'row_sha256': 'e' * 64},
                {'trade_journal.jsonl': (fixtures.gap_trade_row(action='BUY'),)})

    def test_gap_record_observed_fields_mismatch_fails(self):
        import opportunity_state as state
        row = fixtures.gap_review_row(with_symbol=True, with_hint=False)
        record = fixtures.missing_history_row(
            source={'stream': 'private/reviews.jsonl', 'sequence': 1,
                    'row_sha256': self._row_digest(row)},
            observed_fields=['evidence_id'])
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'missing_history_observed_fields_mismatch'):
            state._validate_gap_record(record, {'private/reviews.jsonl': (row,)})

    def test_gap_record_unsubstantiated_symbol_fails(self):
        import opportunity_state as state
        row = fixtures.gap_review_row(with_symbol=True, with_hint=False)
        record = fixtures.missing_history_row(
            source={'stream': 'private/reviews.jsonl', 'sequence': 1,
                    'row_sha256': self._row_digest(row)},
            observed_fields=sorted(row),
            issuer_evidence={'symbol': 'ZZZNOTINROW'})
        with self.assertRaisesRegex(
                state.OpportunityStateError,
                'missing_history_symbol_evidence_unsubstantiated'):
            state._validate_gap_record(record, {'private/reviews.jsonl': (row,)})

    def test_gap_record_symbol_from_nested_row_bytes_is_accepted(self):
        import opportunity_state as state
        row = fixtures.gap_review_row(with_symbol=True, with_hint=False)
        record = fixtures.missing_history_row(
            source={'stream': 'private/reviews.jsonl', 'sequence': 1,
                    'row_sha256': self._row_digest(row)},
            observed_fields=sorted(row),
            issuer_evidence={'symbol': 'ZZZSYNA'})
        validated = state._validate_gap_record(
            record, {'private/reviews.jsonl': (row,)})
        self.assertEqual(validated['symbol_evidence'], 'ZZZSYNA')

    def test_hint_row_gap_cannot_carry_symbol_evidence(self):
        import opportunity_state as state
        row = fixtures.gap_review_row(with_symbol=False, with_hint=True)
        record = fixtures.missing_history_row(
            source={'stream': 'private/reviews.jsonl', 'sequence': 1,
                    'row_sha256': self._row_digest(row)},
            observed_fields=sorted(row),
            issuer_evidence={'symbol': 'ZZZSYNA'})
        with self.assertRaisesRegex(
                state.OpportunityStateError,
                'missing_history_symbol_evidence_unsubstantiated'):
            state._validate_gap_record(record, {'private/reviews.jsonl': (row,)})

    def test_gap_record_malformed_hint_fails(self):
        import opportunity_state as state
        row = fixtures.gap_review_row(with_symbol=False, with_hint=True)
        for hint in ({'legacy_proposal_hash': 'short'}, {'invented': 'x'}, 'f' * 64):
            record = fixtures.missing_history_row(
                source={'stream': 'private/reviews.jsonl', 'sequence': 1,
                        'row_sha256': self._row_digest(row)},
                observed_fields=sorted(row), hint=hint)
            with self.subTest(hint=hint):
                with self.assertRaisesRegex(state.OpportunityStateError,
                                            'invalid_missing_history_record'):
                    state._validate_gap_record(
                        record, {'private/reviews.jsonl': (row,)})

    def test_widened_snapshot_watermark_includes_trade_journal(self):
        import tempfile
        import opportunity_state as state
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixtures.make_gap_root(Path(temporary.name), review_gaps=0,
                                      hint_rows=0, buy_gaps=0, sell_rows=1,
                                      bound_rows=1)
        index = state.load_index(root)
        trade_digest = self._row_digest(storage.read_jsonl_stream_readonly(
            root / 'trade_journal.jsonl')[0])
        self.assertIn(('trade_journal.jsonl', 1, trade_digest),
                      list(index.snapshot.watermark))
        # The state digest folds the widened watermark: it differs from the
        # pre-widening INDEX_STREAMS-only read of the same root.
        narrow = state.read_stream_snapshot_readonly(root, state.INDEX_STREAMS)
        narrow_digest = state._build(narrow).state_digest
        self.assertNotEqual(index.state_digest, narrow_digest)

    def test_load_index_never_writes_trade_journal(self):
        import tempfile
        import opportunity_state as state
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixtures.make_gap_root(Path(temporary.name), review_gaps=0,
                                      hint_rows=0, buy_gaps=0, sell_rows=1,
                                      bound_rows=1)
        path = root / 'trade_journal.jsonl'
        before = (path.read_bytes(), path.stat().st_mtime_ns)
        state.load_index(root)
        self.assertEqual((path.read_bytes(), path.stat().st_mtime_ns), before)


    def _fresh_gap_root(self, **kwargs):
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        return fixtures.make_gap_root(Path(temporary.name), **kwargs)

    def _write_gap_record(self, root, stream, sequence, *, kind, **overrides):
        """Write one validated gap record into the canonical policy stream."""
        snapshot = storage.read_stream_snapshot_readonly(
            root, ('private/reviews.jsonl', 'trade_journal.jsonl'))
        row = snapshot.rows[stream][sequence - 1]
        storage.append_jsonl(root / POLICY, fixtures.missing_history_row(
            kind=kind,
            source={'stream': stream, 'sequence': sequence,
                    'row_sha256': self._row_digest(row)},
            observed_fields=sorted(row),
            **overrides))

    def test_exact_gap_record_builds_index_without_permissions(self):
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=1, hint_rows=0, buy_gaps=0,
                                    sell_rows=0)
        self._write_gap_record(root, 'private/reviews.jsonl', 1,
                               kind='legacy_review_unlinked',
                               issuer_evidence={'symbol': 'ZZZSYNR0'})
        index = state.load_index(root)
        self.assertEqual(len(index.missing_history_gaps), 1)
        gap = index.missing_history_gaps[0]
        self.assertEqual((gap['stream'], gap['sequence'], gap['kind'],
                          gap['symbol_evidence']),
                         ('private/reviews.jsonl', 1, 'legacy_review_unlinked',
                          'ZZZSYNR0'))
        # Tolerance never creates a dossier→allowance entry or permission.
        self.assertEqual(index.dossier_allowances, {})
        self.assertEqual(index.allowance_reviews, {})
        self.assertEqual(index.grants, {})
        # The hashless gap row carries no dossier, so it is absent from the
        # reviewed-dossier set; tolerance adds no unresolved dossier either.
        self.assertEqual(state.incomplete_history(index), frozenset())

    def test_gap_digest_mutation_fails_closed_on_reload(self):
        import opportunity_state as state
        for stream, kind in (('private/reviews.jsonl', 'legacy_review_unlinked'),
                             ('trade_journal.jsonl', 'filled_buy_unlinked')):
            with self.subTest(stream=stream):
                temporary = tempfile.TemporaryDirectory()
                self.addCleanup(temporary.cleanup)
                root = fixtures.make_gap_root(
                    Path(temporary.name), review_gaps=1, hint_rows=0,
                    buy_gaps=1, sell_rows=0)
                snapshot = storage.read_stream_snapshot_readonly(
                    root, ('private/reviews.jsonl', 'trade_journal.jsonl'))
                row = snapshot.rows[stream][1 - 1 if stream != 'trade_journal.jsonl' else 0]
                storage.append_jsonl(root / POLICY, fixtures.missing_history_row(
                    kind=kind,
                    source={'stream': stream, 'sequence': 1,
                            'row_sha256': '0' * 64},
                    observed_fields=sorted(row)))
                with self.assertRaisesRegex(state.OpportunityStateError,
                                            'manifest_source_digest_mismatch'):
                    state.load_index(root)

    def test_mixed_root_still_raises_for_unreferenced_row(self):
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=1, hint_rows=0, buy_gaps=1,
                                    sell_rows=0)
        self._write_gap_record(root, 'private/reviews.jsonl', 1,
                               kind='legacy_review_unlinked',
                               issuer_evidence={'symbol': 'ZZZSYNR0'})
        with self.assertRaises(state.HistoricalDossierHashMissing) as caught:
            state.load_index(root)
        sources = [source['stream'] for source in caught.exception.sources]
        self.assertEqual(sources, ['trade_journal.jsonl'])
        self.assertEqual([source['sequence'] for source in caught.exception.sources],
                         [1])

    def test_gap_record_referencing_dossier_row_fails(self):
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=0, hint_rows=0, buy_gaps=0,
                                    sell_rows=0, bound_rows=1)
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'missing_history_not_gap_row'):
            self._write_gap_record(root, 'private/reviews.jsonl', 1,
                                   kind='legacy_review_unlinked',
                                   issuer_evidence={'symbol': 'ZZZSYNA'})
            state.load_index(root)

    def test_gap_record_non_migration_stream_fails(self):
        import opportunity_state as state
        record = fixtures.missing_history_row(
            source={'stream': 'candidates.jsonl', 'sequence': 1,
                    'row_sha256': 'e' * 64},
            observed_fields=[])
        self.write(POLICY, [record])
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'invalid_manifest_source_reference'):
            state.load_index(self.root)

    def test_gap_record_unsubstantiated_symbol_fails_on_reload(self):
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=1, hint_rows=0, buy_gaps=0,
                                    sell_rows=0)
        with self.assertRaisesRegex(
                state.OpportunityStateError,
                'missing_history_symbol_evidence_unsubstantiated'):
            self._write_gap_record(root, 'private/reviews.jsonl', 1,
                                   kind='legacy_review_unlinked',
                                   issuer_evidence={'symbol': 'ZZZNOTINROW'})
            state.load_index(root)

    def test_sell_rows_never_raise_or_grant(self):
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=0, hint_rows=0, buy_gaps=0,
                                    sell_rows=2)
        index = state.load_index(root)
        self.assertEqual(index.missing_history_gaps, ())
        self.assertEqual(index.unknown_history_blocks if hasattr(
            index, 'unknown_history_blocks') else {}, {})

    def test_hint_row_gap_with_null_evidence_is_tolerated(self):
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=0, hint_rows=1, buy_gaps=0,
                                    sell_rows=0)
        self._write_gap_record(root, 'private/reviews.jsonl', 1,
                               kind='legacy_review_unlinked')
        index = state.load_index(root)
        self.assertEqual(len(index.missing_history_gaps), 1)
        self.assertIsNone(index.missing_history_gaps[0]['symbol_evidence'])

    def _active_gap_root(self, *, symbol='ACME', buy_gap=False, hint_row=False):
        """Activated synthetic root with one gap row naming exactly `symbol`."""
        import json
        import opportunity_state as state
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixtures.make_root(Path(temporary.name))
        if buy_gap:
            stream, kind = ('trade_journal.jsonl', 'filled_buy_unlinked')
            row = fixtures.gap_trade_row(action='BUY', symbol=symbol)
        else:
            stream, kind = ('private/reviews.jsonl', 'legacy_review_unlinked')
            row = fixtures.gap_review_row(with_symbol=not hint_row, with_hint=hint_row,
                                          symbol=symbol, evidence_id='gap-review-0')
        storage.append_jsonl(root / stream, row)
        storage.append_jsonl(root / POLICY, fixtures.missing_history_row(
            kind=kind,
            source={'stream': stream, 'sequence': 1,
                    'row_sha256': self._row_digest(row)},
            observed_fields=sorted(row),
            issuer_evidence=None if hint_row else {'symbol': symbol}))
        storage.append_jsonl(root / POLICY, fixtures.policy_row(
            'activation', policy_version=1, manifest_sha256='a' * 64))
        (root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': []}))
        self.root = root
        return root

    def test_symbol_gap_blocks_candidate(self):
        import opportunity_state as state
        self._active_gap_root(symbol='ACME')
        context = state.load_policy_context(self.root)
        result = state.candidate_policy(context, fixtures.synthetic_resolution(),
                                        symbol='ACME')
        self.assertEqual((result.outcome, result.reason, result.allowance_id),
                         ('unknown', 'unknown_history_unreconciled', None))

    def test_gap_without_symbol_evidence_does_not_block(self):
        import opportunity_state as state
        self._active_gap_root(hint_row=True)
        context = state.load_policy_context(self.root)
        result = state.candidate_policy(context, fixtures.synthetic_resolution(),
                                        symbol='ACME')
        self.assertNotEqual(result.reason, 'unknown_history_unreconciled')

    def test_symbol_variant_does_not_block(self):
        import opportunity_state as state
        self._active_gap_root(symbol='ACME')
        context = state.load_policy_context(self.root)
        result = state.candidate_policy(context, fixtures.synthetic_resolution(),
                                        symbol='ACME.F')
        self.assertNotEqual(result.reason, 'unknown_history_unreconciled')
        # A whitespace-variant candidate symbol never reaches the block check:
        # the verified identity comparison fails closed first (never grants).
        whitespace = state.candidate_policy(context, fixtures.synthetic_resolution(),
                                            symbol='  acme ')
        self.assertEqual(whitespace.reason, 'opportunity_identity_conflict')
        # Block keys are normalized (casefold + trim): a lowercase gap symbol
        # blocks the exact verified uppercase issuer symbol.
        self._active_gap_root(symbol='acme')
        lower_index = state.load_index(self.root)
        self.assertIn('acme', lower_index.unknown_history_blocks)
        blocked = state.candidate_policy(
            state.load_policy_context(self.root), fixtures.synthetic_resolution(),
            symbol='ACME')
        self.assertEqual(blocked.reason, 'unknown_history_unreconciled')

    def test_blocking_never_grants_or_spends_or_qualifies_retry(self):
        import opportunity_state as state
        self._active_gap_root(symbol='ACME')
        context = state.load_policy_context(self.root)
        before = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                  for path in self.root.rglob('*') if path.is_file()}
        result = state.candidate_policy(context, fixtures.synthetic_resolution(),
                                        symbol='ACME')
        self.assertEqual(result.outcome, 'unknown')
        self.assertIsNone(result.allowance_id)
        fresh = state.load_index(self.root)
        self.assertEqual(fresh.dossier_allowances, {})
        self.assertEqual(fresh.grants, {})
        self.assertEqual(len(fresh.missing_history_gaps), 1)
        after = {path: (path.read_bytes(), path.stat().st_mtime_ns)
                 for path in self.root.rglob('*') if path.is_file()}
        self.assertEqual(before, after)

    def _two_gap_symbol_root(self):
        """Activated root with two review gaps naming the same symbol."""
        import json
        import tempfile
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixtures.make_root(Path(temporary.name))
        for index in (1, 2):
            row = fixtures.gap_review_row(with_symbol=True, with_hint=False,
                                          symbol='ACME',
                                          evidence_id=f'gap-review-{index}')
            storage.append_jsonl(root / 'private/reviews.jsonl', row)
            storage.append_jsonl(root / POLICY, fixtures.missing_history_row(
                kind='legacy_review_unlinked',
                source={'stream': 'private/reviews.jsonl', 'sequence': index,
                        'row_sha256': self._row_digest(row)},
                observed_fields=sorted(row),
                issuer_evidence={'symbol': 'ACME'}))
        storage.append_jsonl(root / POLICY, fixtures.policy_row(
            'activation', policy_version=1, manifest_sha256='a' * 64))
        (root / 'private/broker_baseline.json').write_text(json.dumps(
            {'preexisting_symbols': []}))
        self.root = root
        return root

    def _write_clearance(self, root, sequence):
        row = storage.read_jsonl_stream_readonly(
            root / 'private/reviews.jsonl')[sequence - 1]
        storage.append_jsonl(root / POLICY, fixtures.missing_history_clearance_row(
            gap_source={'stream': 'private/reviews.jsonl', 'sequence': sequence,
                        'row_sha256': self._row_digest(row)}))

    def test_partial_clearance_keeps_symbol_blocked(self):
        import opportunity_state as state
        root = self._two_gap_symbol_root()
        self._write_clearance(root, 1)
        index = state.load_index(root)
        self.assertIn('acme', index.unknown_history_blocks)
        self.assertEqual(len(index.unknown_history_blocks['acme']), 1)
        blocked = state.candidate_policy(
            state.load_policy_context(root), fixtures.synthetic_resolution(),
            symbol='ACME')
        self.assertEqual(blocked.reason, 'unknown_history_unreconciled')

    def test_full_clearance_unblocks_symbol(self):
        import opportunity_state as state
        root = self._two_gap_symbol_root()
        self._write_clearance(root, 1)
        self._write_clearance(root, 2)
        index = state.load_index(root)
        self.assertEqual(index.unknown_history_blocks, {})
        # The underlying missing_history records are kept forever.
        self.assertEqual(len(index.missing_history_gaps), 2)

    def test_clearance_unknown_or_mismatched_gap_fails_closed(self):
        import opportunity_state as state
        root = self._two_gap_symbol_root()
        # A clearance for a row with no missing_history record fails.
        trade = fixtures.gap_trade_row(action='BUY', symbol='ACME')
        storage.append_jsonl(root / 'trade_journal.jsonl', trade)
        storage.append_jsonl(root / POLICY, fixtures.missing_history_clearance_row(
            gap_source={'stream': 'trade_journal.jsonl', 'sequence': 1,
                        'row_sha256': self._row_digest(trade)}))
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'missing_history_clearance_unknown_gap'):
            state.load_index(root)
        # A mutated gap digest fails the exact-source check.
        root = self._two_gap_symbol_root()
        storage.append_jsonl(root / POLICY, fixtures.missing_history_clearance_row(
            gap_source={'stream': 'private/reviews.jsonl', 'sequence': 1,
                        'row_sha256': '0' * 64}))
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'manifest_source_digest_mismatch'):
            state.load_index(root)

    def test_clearance_bad_reason_fails_closed(self):
        import opportunity_state as state
        rows = (fixtures.missing_history_clearance_row(
            clearance_reason='invented_reason'),)
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            state._policy_state(rows, {}, {}, {}, {}, set(), {}, {}, {})

    def test_combined_gap_and_binding_manifest_yields_empty_incomplete_history(self):
        """78-shaped gap set + 124-shaped binding set, zero invented scopes."""
        import hashlib
        import json
        import opportunity_admin as admin
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=67, hint_rows=5, buy_gaps=6,
                                    sell_rows=0)
        reviews = storage.read_jsonl_stream_readonly(root / REVIEWS)
        trades = storage.read_jsonl_stream_readonly(root / 'trade_journal.jsonl')
        records = []
        for sequence, row in enumerate(reviews[:67], 1):
            records.append(fixtures.missing_history_row(
                kind='legacy_review_unlinked',
                source={'stream': REVIEWS, 'sequence': sequence,
                        'row_sha256': self._row_digest(row)},
                observed_fields=sorted(row),
                issuer_evidence={'symbol': f'ZZZSYNR{sequence - 1}'}))
        for offset, row in enumerate(reviews[67:]):
            sequence = 67 + offset + 1
            records.append(fixtures.missing_history_row(
                kind='legacy_review_unlinked',
                source={'stream': REVIEWS, 'sequence': sequence,
                        'row_sha256': self._row_digest(row)},
                observed_fields=sorted(row), hint={'legacy_proposal_hash': 'f' * 64}))
        for sequence, row in enumerate(trades, 1):
            records.append(fixtures.missing_history_row(
                kind='filled_buy_unlinked',
                source={'stream': 'trade_journal.jsonl', 'sequence': sequence,
                        'row_sha256': self._row_digest(row)},
                observed_fields=sorted(row),
                issuer_evidence={'symbol': f'ZZZSYNB{sequence - 1}'}))
        # 124 known hashes bound generation-zero via reviewed candidate sources.
        dossiers = [hashlib.sha256(f'synthetic-dossier-{index}'.encode()).hexdigest()
                    for index in range(124)]
        candidate_rows = [{'dossier_hash': dossier} for dossier in dossiers]
        self.write_root(root, CANDIDATES, candidate_rows)
        for index, dossier in enumerate(dossiers):
            import opportunity_identity as identity
            cik = f'0002{index:06d}'
            payload = json.loads(json.dumps(
                fixtures.synthetic_resolution_payload(period='2026-Q1'))
                .replace('1999999', cik[3:]))
            payload['event_id'] = identity._event_id(cik, '2026-Q1')
            records.append(fixtures.policy_row(
                'identity_resolution', resolution=payload,
                source={'stream': CANDIDATES, 'sequence': index + 1,
                        'row_sha256': self._row_digest(candidate_rows[index])}))
        manifest = {'manifest_version': 1, 'records': records}
        self.assertEqual(len(records), 78 + 124)
        report = admin.validate_manifest(root, manifest)
        self.assertTrue(report['valid'], report['errors'][:3])
        digest = admin.canonical_manifest_digest(manifest)
        admin.import_manifest(root, manifest, approved_manifest_sha256=digest)
        index = state.load_index(root)
        self.assertEqual(state.incomplete_history(index), frozenset())
        self.assertEqual(len(index.missing_history_gaps), 78)
        self.assertEqual(len(index.dossier_allowances), 124)

    def write_root(self, root, name, rows):
        for row in rows:
            storage.append_jsonl(root / name, row)

    def test_v0_floor_inert_with_gap_records(self):
        import opportunity_state as state
        root = self._fresh_gap_root(review_gaps=1, hint_rows=0, buy_gaps=1,
                                    sell_rows=0)
        review = storage.read_jsonl_stream_readonly(root / REVIEWS)[0]
        trade = storage.read_jsonl_stream_readonly(root / 'trade_journal.jsonl')[0]
        self.write_root(root, POLICY, [
            fixtures.missing_history_row(
                kind='legacy_review_unlinked',
                source={'stream': REVIEWS, 'sequence': 1,
                        'row_sha256': self._row_digest(review)},
                observed_fields=sorted(review),
                issuer_evidence={'symbol': 'ZZZSYNR0'}),
            fixtures.missing_history_row(
                kind='filled_buy_unlinked',
                source={'stream': 'trade_journal.jsonl', 'sequence': 1,
                        'row_sha256': self._row_digest(trade)},
                observed_fields=sorted(trade),
                issuer_evidence={'symbol': 'ZZZSYNB0'}),
        ])
        index = state.load_index(root)
        self.assertEqual(index.activated_version, 0)
        self.assertEqual(len(index.missing_history_gaps), 2)
        self.assertEqual(len(index.unknown_history_blocks), 2)
        # The v0 compatibility floor is unchanged: activation absent → eligible.
        result = state.require_current_allowance(root, {'dossier_hash': 'c' * 64})
        self.assertEqual((result.outcome, result.reason),
                         ('eligible', 'legacy_policy_floor'))

    def test_pre_migration_reader_fails_typed_on_missing_history_stream(self):
        import opportunity_state as state
        legacy_types = frozenset({
            'activation', 'identity_resolution', 'document_alias',
            'reopen_grant', 'condition_approval'})

        def legacy_style_policy_state(rows):
            for row in rows:
                if (row.get('record_type') not in legacy_types
                        or row.get('schema_version') != 1
                        or not isinstance(row.get('timestamp'), str)):
                    raise state.OpportunityStateError(
                        'opportunity_policy_state_unavailable')
        migrated_rows = (
            fixtures.policy_row('activation', policy_version=1,
                                manifest_sha256='a' * 64),
            fixtures.missing_history_row(),
        )
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            legacy_style_policy_state(migrated_rows)
        # Control: the same legacy reader accepts the pre-migration stream.
        legacy_style_policy_state(migrated_rows[:1])

    def test_missing_history_bad_reason_fails_closed(self):
        import opportunity_state as state
        rows = (fixtures.missing_history_row(reason='invented_reason'),)
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            state._policy_state(rows, {}, {}, {}, {}, set(), {}, {}, {})

    def test_missing_history_bad_kind_fails_closed(self):
        import opportunity_state as state
        rows = (fixtures.missing_history_row(kind='invented_kind'),)
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            state._policy_state(rows, {}, {}, {}, {}, set(), {}, {}, {})

    def test_missing_history_missing_key_fails_closed(self):
        import opportunity_state as state
        row = fixtures.missing_history_row()
        del row['reason']
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            state._policy_state((row,), {}, {}, {}, {}, set(), {}, {}, {})

    def test_missing_history_bad_schema_version_fails_closed(self):
        import opportunity_state as state
        row = fixtures.missing_history_row()
        row['schema_version'] = 2
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            state._policy_state((row,), {}, {}, {}, {}, set(), {}, {}, {})

    def test_missing_history_bad_timestamp_fails_closed(self):
        import opportunity_state as state
        row = fixtures.missing_history_row()
        row['timestamp'] = 'not-a-timestamp'
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            state._policy_state((row,), {}, {}, {}, {}, set(), {}, {}, {})

    def test_missing_history_wellformed_is_accepted_without_permission(self):
        import opportunity_state as state
        resolutions, aliases, grants, conditions = {}, {}, {}, {}
        unresolved, allowance_events, scopes = set(), {}, {}
        version = state._policy_state(
            (fixtures.missing_history_row(),), resolutions, aliases, grants,
            conditions, unresolved, allowance_events, scopes, {})
        self.assertEqual(version, 0)
        self.assertEqual((resolutions, aliases, grants, conditions, unresolved,
                          allowance_events, scopes), ({}, {}, {}, {}, set(), {}, {}))

    def test_hashless_buy_trade_row_is_not_yet_scanned(self):
        import tempfile
        import opportunity_state as state
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        root = fixtures.make_gap_root(Path(temporary.name), review_gaps=0,
                                      hint_rows=0, buy_gaps=1, sell_rows=0)
        with self.assertRaisesRegex(state.HistoricalDossierHashMissing,
                                    'opportunity_policy_state_unavailable'):
            state.load_index(root)  # today only REVIEWS_STREAM raises; BUY row unscanned


if __name__ == '__main__':
    unittest.main()
