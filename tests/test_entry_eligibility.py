"""Strict broker position observations and shared BUY eligibility; fail closed.

All fixtures are explicitly synthetic: fictional symbols, coherent snapshot
dictionaries built through the same strict observation contract the trusted
bridge emits. No operational issuer, account or trade history appears here.
"""
import copy
import datetime as dt
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import entry_eligibility
import managed_reconciliation
import pending_policy
import opportunity_fixtures as fixtures

NOW = dt.datetime(2026, 11, 4, 12, 0, 0, tzinfo=dt.timezone.utc)
DOSSIER_A = 'a' * 64
EVIDENCE_1 = 'evidence-1'
PROPOSAL_1 = 'p' * 64


def canonical_digest(row):
    return hashlib.sha256(json.dumps(
        row, sort_keys=True, separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def position_row(symbol='MSFT', qty='2', side='long', **extra):
    row = {'asset_id': 'synthetic-' + symbol.lower(), 'symbol': symbol, 'side': side,
           'qty': qty, 'avg_entry_price': '10', 'current_price': '11',
           'market_value': '22', 'cost_basis': '20', 'unrealized_pl': '2',
           'unrealized_plpc': '0.10', 'unrealized_intraday_pl': '0.2',
           'change_today': '0.01'}
    row.update(extra)
    return row


def pending_parent(ref='one', symbol='AAPL', status='new', filled_qty='0'):
    plan = dict(action='BUY', symbol=symbol, quantity=2, order_type='limit',
                limit_price=100, stop=95, target=110, horizon='3 sessions',
                confidence=.9, thesis='saved', risk_reward=2)
    child = dict(symbol=symbol, side='sell', position_intent='sell_to_close',
                 order_class='bracket', time_in_force='gtc', qty='2',
                 filled_qty='0', status='held')
    parent = dict(client_order_id=ref, symbol=symbol, side='buy',
                  position_intent='buy_to_open', order_class='bracket',
                  time_in_force='gtc', type='limit', qty='2',
                  filled_qty=filled_qty, limit_price='100', status=status,
                  legs=[dict(child, client_order_id=ref + '-target', type='limit', limit_price='110'),
                        dict(child, client_order_id=ref + '-stop', type='stop', stop_price='95')])
    return {'client_order_id': ref, 'plan': plan}, parent


class EntryFixtureBase(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        (self.root / 'private').mkdir()
        (self.root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': []}))
        self.now = NOW

    def snapshot(self, positions=(), open_orders=(), *, started_seconds_ago=1.0,
                 finished_seconds_ago=0.5, duration=0.5, version=1, **overrides):
        started = self.now - dt.timedelta(seconds=started_seconds_ago)
        finished = self.now - dt.timedelta(seconds=finished_seconds_ago)
        observation = entry_eligibility.entry_observation(
            started_at=started, finished_at=finished,
            duration_seconds=duration, positions=list(positions),
            open_orders=list(open_orders))
        if version != 1:
            observation = dict(observation, version=version)
        snapshot = {
            'captured_at': self.now.isoformat().replace('+00:00', 'Z'),
            'cash': 10000.0, 'buying_power': 10000.0,
            'cash_semantics': 'gross', 'buying_power_semantics': 'available_net',
            'positions': copy.deepcopy(list(positions)),
            'open_orders': copy.deepcopy(list(open_orders)),
            'quote': {'bid': 99.98, 'ask': 100.0,
                      'timestamp': self.now.isoformat().replace('+00:00', 'Z')},
            'entry_observation': observation,
        }
        snapshot.update(overrides)
        return snapshot

    def proof(self, snapshot):
        intents, parents = [], []
        # Baseline records the preexisting managed holdings so the shared
        # reconciliation in pending qualification stays coherent.
        held = sorted({str(row.get('symbol') or '').upper()
                       for row in snapshot['positions'] if isinstance(row, dict)})
        (self.root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': held}))

        def add(ref='one', symbol='AAPL', status='new', filled_qty='0'):
            intent, parent = pending_parent(ref, symbol, status, filled_qty)
            intents.append(intent)
            parents.append(parent)

        def write():
            for name, rows in (('private/order_intents.jsonl', intents),
                               ('order_ledger.jsonl',
                                [{'client_order_id': i['client_order_id'], 'status': 'new'}
                                 for i in intents])):
                (self.root / name).write_text(
                    ''.join(json.dumps(r) + '\n' for r in rows))

        def broker(op, payload):
            self.assertEqual(op, 'reconcile_many')
            return {'orders': copy.deepcopy(
                [p for p in parents
                 if p['client_order_id'] in payload['client_order_ids']])}

        add()
        write()
        snapshot['open_orders'] = copy.deepcopy(parents)
        snapshot['entry_observation'] = entry_eligibility.entry_observation(
            started_at=self.now - dt.timedelta(seconds=1),
            finished_at=self.now - dt.timedelta(seconds=0.5),
            duration_seconds=0.5, positions=list(snapshot['positions']),
            open_orders=list(parents))
        return pending_policy.qualify(self.root, snapshot, broker)


class EvaluateBuyTests(EntryFixtureBase):
    """Shared evaluator contract for Task 6 wrappers and direct proposals."""

    def setUp(self):
        super().setUp()
        self.valid_snapshot_with_held_shares = self.snapshot(
            positions=[position_row('ACME', '16')])
        self.snapshot_bound_pending_proof = self.proof(self.valid_snapshot_with_held_shares)

    def test_positive_shares_block_even_when_market_value_is_zero(self):
        result = entry_eligibility.evaluate_buy(
            "ACME", self.valid_snapshot_with_held_shares,
            pending_proof=self.snapshot_bound_pending_proof, now=self.now)
        self.assertEqual((result.outcome, result.reason), ("held", "position_already_held"))

    def test_held_fractions_dust_and_below_cap_holdings_block(self):
        for label, row in (
                ('fractional_dust', position_row('ACME', '0.75')),
                ('zero_market_value', position_row('ACME', '5', market_value='0')),
                ('missing_market_value', position_row('ACME', '5', market_value=None)),
                ('below_cap_small_holding', position_row('ACME', '1', market_value='40')),
        ):
            with self.subTest(case=label):
                snapshot = self.snapshot(positions=[row])
                result = entry_eligibility.evaluate_buy(
                    'ACME', snapshot, pending_proof=self.proof(snapshot), now=self.now)
                self.assertEqual((result.outcome, result.reason),
                                 ('held', 'position_already_held'))

    def test_properly_empty_complete_flat_snapshot_is_eligible(self):
        snapshot = self.snapshot()
        result = entry_eligibility.evaluate_buy(
            'ACME', snapshot, pending_proof=self.proof(snapshot), now=self.now)
        self.assertEqual((result.outcome, result.reason), ('eligible', 'flat_complete'))

    def test_positive_numeric_strings_and_other_symbol_rows_keep_old_semantics(self):
        snapshot = self.snapshot(positions=[
            position_row('MSFT', '3'), position_row('NVDA', '1.5')])
        proof = self.proof(snapshot)
        result = entry_eligibility.evaluate_buy(
            'ACME', snapshot, pending_proof=proof, now=self.now)
        self.assertEqual((result.outcome, result.reason), ('eligible', 'flat_complete'))

    def test_other_symbol_pending_capacity_and_protective_children_retain_semantics(self):
        snapshot = self.snapshot()
        proof = self.proof(snapshot)
        self.assertEqual(proof.pending[0][1], 'AAPL')
        result = entry_eligibility.evaluate_buy(
            'MSFT', snapshot, pending_proof=proof, now=self.now)
        self.assertEqual((result.outcome, result.reason), ('eligible', 'flat_complete'))

    def test_same_symbol_pending_partial_and_submission_unknown_block(self):
        for label, status, filled in (
                ('pending_new', 'new', '0'),
                ('partial_fill', 'partially_filled', '1'),
                ('submission_unknown', 'submission_unknown', '0'),
        ):
            with self.subTest(case=label):
                snapshot = self.snapshot()
                intents, parents = [], []
                intent, parent = pending_parent('one', 'ACME', status, filled)
                intents.append(intent)
                parents.append(parent)
                (self.root / 'private/order_intents.jsonl').write_text(
                    ''.join(json.dumps(r) + '\n' for r in intents))
                (self.root / 'order_ledger.jsonl').write_text(
                    json.dumps({'client_order_id': 'one', 'status': status}) + '\n')
                snapshot['open_orders'] = copy.deepcopy(parents)
                snapshot['entry_observation'] = entry_eligibility.entry_observation(
                    started_at=self.now - dt.timedelta(seconds=1),
                    finished_at=self.now - dt.timedelta(seconds=0.5),
                    duration_seconds=0.5, positions=list(snapshot['positions']),
                    open_orders=list(parents))

                def broker(op, payload):
                    self.assertEqual(op, 'reconcile_many')
                    return {'orders': copy.deepcopy(parents)}

                if status == 'new':
                    proof = pending_policy.qualify(self.root, snapshot, broker)
                    result = entry_eligibility.evaluate_buy(
                        'ACME', snapshot, pending_proof=proof, now=self.now)
                    self.assertEqual((result.outcome, result.reason),
                                     ('pending', 'same_symbol_pending_entry'))
                else:
                    # A partially filled or submission-unknown entry obligation
                    # cannot be qualified at all; without a valid proof no
                    # entry is authorized.
                    with self.assertRaises(managed_reconciliation.ReconciliationBlocked):
                        pending_policy.qualify(self.root, snapshot, broker)
                    result = entry_eligibility.evaluate_buy(
                        'ACME', snapshot, pending_proof=None, now=self.now)
                    self.assertEqual((result.outcome, result.reason),
                                     ('pending', 'pending_qualification_required'))

    def test_missing_or_mismatched_proof_never_authorizes_entry(self):
        snapshot = self.snapshot()
        for label, proof in (('missing', None), ('mismatched', self.proof(self.snapshot()))):
            with self.subTest(case=label):
                result = entry_eligibility.evaluate_buy(
                    'ACME', snapshot, pending_proof=proof, now=self.now)
                self.assertEqual((result.outcome, result.reason),
                                 ('pending', 'pending_qualification_required'))

    def test_stale_proof_over_old_positions_does_not_pretend_refresh(self):
        old = self.snapshot()
        proof = self.proof(old)
        refreshed = self.snapshot(positions=[position_row('BRKV', '4')])
        result = entry_eligibility.evaluate_buy(
            'ACME', refreshed, pending_proof=proof, now=self.now)
        self.assertEqual((result.outcome, result.reason),
                         ('pending', 'pending_qualification_required'))
        # Repeat qualification over the same unchanged old portfolio yields the
        # identical bound proof; it never claims the refreshed portfolio state.
        again = self.proof(old)
        self.assertEqual(again.snapshot_hash, proof.snapshot_hash)
        self.assertNotEqual(proof.snapshot_hash, pending_policy.digest(refreshed))


class EvaluateBuyFailClosedTests(EntryFixtureBase):
    def flat(self, **overrides):
        snapshot = self.snapshot(**overrides)
        proof = None if overrides.get('break_proof', False) else self.proof(snapshot)
        return snapshot, proof

    def assert_unknown(self, snapshot, proof=None):
        result = entry_eligibility.evaluate_buy(
            'ACME', snapshot, pending_proof=proof, now=self.now)
        self.assertEqual(result.outcome, 'unknown', result)
        return result.reason

    def test_missing_or_malformed_observation_fails_closed_with_fresh_quote(self):
        snapshot, _ = self.flat()
        variants = (
                ('version', dict(snapshot['entry_observation'], version=2)),
                ('not_dict', []),
                ('dropped_positions', {k: v for k, v in
                                       snapshot['entry_observation'].items()
                                       if k != 'positions'}),
                ('incomplete_flags', dict(snapshot['entry_observation'],
                                          positions_complete=False)),
        )
        del snapshot['entry_observation']
        self.assertEqual(self.assert_unknown(snapshot), 'entry_evidence_unverified')
        for label, observation in variants:
            with self.subTest(case=label):
                broken = dict(snapshot, entry_observation=observation)
                self.assertEqual(self.assert_unknown(broken), 'entry_evidence_unverified')

    def test_non_envelope_error_and_dict_positions_cannot_become_flat(self):
        snapshot, proof = self.flat()
        for label, positions in (
                ('error_dict', {'error': 'upstream failure'}),
                ('wrapped_dict', {'data': []}),
                ('string', 'nope'),
                ('none', None),
        ):
            with self.subTest(case=label):
                broken = copy.deepcopy(snapshot)
                broken['positions'] = positions
                broken['entry_observation'] = dict(
                    broken['entry_observation'], positions=positions)
                self.assertEqual(self.assert_unknown(broken, proof),
                                 'entry_evidence_unverified')

    def test_row_level_malformation_fails_closed(self):
        snapshot, proof = self.flat()
        bad_rows = (
            ('bool_qty', position_row('MSFT', True)),
            ('null_qty', position_row('MSFT', None)),
            ('empty_qty', position_row('MSFT', '')),
            ('nan_qty', position_row('MSFT', float('nan'))),
            ('inf_qty', position_row('MSFT', float('inf'))),
            ('negative_qty', position_row('MSFT', '-1')),
            ('zero_qty', position_row('MSFT', '0')),
            ('short_side', position_row('MSFT', '2', side='short')),
            ('missing_side', {k: v for k, v in position_row('MSFT', '2').items()
                              if k != 'side'}),
            ('bad_symbol', position_row('../ACME', '2')),
            ('empty_symbol', position_row('', '2')),
        )
        for label, row in bad_rows:
            with self.subTest(row=label):
                broken = copy.deepcopy(snapshot)
                broken['positions'] = [row]
                broken['entry_observation'] = dict(
                    broken['entry_observation'], positions=[row])
                self.assertEqual(self.assert_unknown(broken, proof), 'positions_unverified')
        with self.subTest(row='duplicates'):
            broken = copy.deepcopy(snapshot)
            row = position_row('MSFT', '2')
            broken['positions'] = [row, dict(row)]
            broken['entry_observation'] = dict(
                broken['entry_observation'], positions=[row, dict(row)])
            self.assertEqual(self.assert_unknown(broken, proof), 'positions_unverified')

    def test_observation_digest_disagreement_with_snapshot_positions_fails_closed(self):
        snapshot, proof = self.flat()
        broken = copy.deepcopy(snapshot)
        broken['positions'] = [position_row('HIDE', '9')]
        self.assertEqual(self.assert_unknown(broken, proof), 'positions_unverified')

    def test_time_boundaries_fail_closed_even_with_fresh_quote(self):
        snapshot, proof = self.flat()
        base = snapshot['entry_observation']
        cases = (
            ('age_121', dict(base, started_at=(self.now - dt.timedelta(seconds=121))
                             .isoformat().replace('+00:00', 'Z')), 'entry_evidence_stale'),
            ('future', dict(base, started_at=(self.now + dt.timedelta(seconds=5))
                            .isoformat().replace('+00:00', 'Z'),
                            finished_at=(self.now + dt.timedelta(seconds=10))
                            .isoformat().replace('+00:00', 'Z')), 'entry_evidence_future'),
            ('naive_start', dict(base, started_at='2026-11-04T11:59:59'), 'entry_evidence_invalid'),
            ('naive_finish', dict(base, finished_at='2026-11-04T11:59:59.5'),
             'entry_evidence_invalid'),
            ('missing_start', {k: v for k, v in base.items() if k != 'started_at'},
             'entry_evidence_invalid'),
            ('missing_finish', {k: v for k, v in base.items() if k != 'finished_at'},
             'entry_evidence_invalid'),
            ('missing_duration', {k: v for k, v in base.items() if k != 'duration_seconds'},
             'entry_evidence_invalid'),
            ('duration_121', dict(base, duration_seconds=121.0), 'entry_evidence_overlong'),
            ('negative_duration', dict(base, duration_seconds=-1.0), 'entry_evidence_invalid'),
            ('bool_duration', dict(base, duration_seconds=True), 'entry_evidence_invalid'),
            ('nan_duration', dict(base, duration_seconds=float('nan')), 'entry_evidence_invalid'),
            ('wall_window_overlong', dict(base,
                                          started_at=(self.now - dt.timedelta(seconds=180))
                                          .isoformat().replace('+00:00', 'Z'),
                                          finished_at=self.now.isoformat()
                                          .replace('+00:00', 'Z'),
                                          duration_seconds=120.0), 'entry_evidence_stale'),
            ('finish_before_start', dict(
                base,
                started_at='2026-11-04T11:59:59Z',
                finished_at='2026-11-04T11:59:58Z'), 'entry_evidence_invalid'),
        )
        for label, observation, reason in cases:
            with self.subTest(case=label):
                broken = dict(snapshot, entry_observation=observation)
                self.assertEqual(self.assert_unknown(broken, proof), reason)

    def test_exactly_120_second_age_and_read_duration_pass(self):
        snapshot = self.snapshot(started_seconds_ago=120.0, finished_seconds_ago=0.0,
                                 duration=120.0)
        result = entry_eligibility.evaluate_buy(
            'ACME', snapshot, pending_proof=self.proof(snapshot), now=self.now)
        self.assertEqual((result.outcome, result.reason), ('eligible', 'flat_complete'))

    def test_invalid_evaluated_symbol_fails_closed(self):
        snapshot, proof = self.flat()
        for symbol in ('', 'TOOLONGSYMBOL', None, 7):
            with self.subTest(symbol=symbol):
                result = entry_eligibility.evaluate_buy(
                    symbol, snapshot, pending_proof=proof, now=self.now)
                self.assertEqual((result.outcome, result.reason),
                                 ('unknown', 'entry_symbol_invalid'))


class LocalEntryExclusionsTests(EntryFixtureBase):
    POLICY = 'private/opportunity_policy.jsonl'
    REVIEWS = 'private/reviews.jsonl'
    CANDIDATES = 'candidates.jsonl'

    def write(self, name, rows):
        import sqlite_ledger as storage
        for row in rows:
            storage.append_jsonl(self.root / name, row)

    def build(self, *, spent=True):
        import opportunity_state as state
        resolution = fixtures.synthetic_resolution()
        self.write(self.POLICY, [
            fixtures.policy_row('activation', policy_version=1,
                                manifest_sha256='a' * 64),
            fixtures.policy_row('identity_resolution',
                                resolution=fixtures.synthetic_resolution_payload()),
        ])
        self.write(self.CANDIDATES, [
            fixtures.candidate_link(DOSSIER_A, resolution.event_id,
                                    state.allowance_identifier(resolution.event_id, 0)),
        ])
        if spent:
            self.write(self.REVIEWS, [
                fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                    [{'decision': 'HOLD'}, {'decision': 'HOLD'}]),
            ])
        return state.load_index(self.root), resolution

    def test_durable_lineage_and_baseline_symbols_are_excluded(self):
        import opportunity_state as state
        index, _ = self.build()
        (self.root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': ['PREX', 'prey']}))
        self.assertEqual(state.local_entry_exclusions(index), frozenset({'ACME', 'PREX', 'PREY'}))

    def test_unspent_lineage_is_not_an_exclusion(self):
        import opportunity_state as state
        index, _ = self.build(spent=False)
        self.assertEqual(state.local_entry_exclusions(index), frozenset())

    def test_missing_or_malformed_baseline_fails_closed(self):
        import opportunity_state as state
        index, _ = self.build()
        (self.root / 'private/broker_baseline.json').unlink()
        with self.assertRaises(state.OpportunityStateError):
            state.local_entry_exclusions(index)
        (self.root / 'private/broker_baseline.json').write_text('{"preexisting_symbols": "x"}')
        with self.assertRaises(state.OpportunityStateError):
            state.local_entry_exclusions(index)
        with self.assertRaises(state.OpportunityStateError):
            state.local_entry_exclusions(object())


if __name__ == '__main__':
    unittest.main()
