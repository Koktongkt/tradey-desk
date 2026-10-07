import copy
from decimal import Decimal as D
import unittest

from watchdog.types import OperationalSnapshot, BrokerSnapshot


def snapshots():
    op = OperationalSnapshot({
        'candidates.jsonl': [dict(candidate_id='idea-a', dossier_hash='da', symbol='ABC'),
                             dict(candidate_id='idea-b', dossier_hash='db', symbol='ABC')],
        'private/reviews.jsonl': [dict(dossier_hash='da', proposal_hash='pa', evidence_id='ea',
                                      reviews=[dict(decision='APPROVE')])],
        'private/order_intents.jsonl': [dict(client_order_id='parent', plan=dict(proposal_hash='pa',
            symbol='ABC', action='BUY', planned_exit_at='2026-10-09T20:00:00Z', stop=9, target=12))],
    }, frozenset(), '2026-10-07T15:00:00Z', True, [])
    order = dict(id='broker-parent', client_order_id='parent', symbol='ABC', side='buy',
                 filled_qty=D('2'), filled_avg_price=D('10'), status='filled', legs=[])
    broker = BrokerSnapshot({}, [dict(symbol='ABC', qty=D('2'))], [order], [], [],
                            op.captured_at, True, dict(orders='complete', references='complete', activities='complete'))
    return op, broker


class LineageTests(unittest.TestCase):
    def test_two_ideas_same_symbol_are_not_both_traded(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        before = copy.deepcopy((op, broker))
        result = build_lineage(op, broker)
        self.assertEqual([p['candidate_id'] for p in result.positions], ['idea-a'])
        self.assertEqual({r['candidate_id']: r['status'] for r in result.decisions},
                         {'idea-a': 'filled', 'idea-b': 'researched'})
        self.assertEqual(result.positions[0]['entry_quantity'], D('2'))
        self.assertEqual((op, broker), before)

    def test_invalid_intent_client_ids_do_not_contaminate_valid_attribution(self):
        from watchdog.lineage import build_lineage
        for value in ('missing', None, '', 7, False, [], {}):
            for invalid_first in (False, True):
                with self.subTest(value=value, invalid_first=invalid_first):
                    op, broker = snapshots()
                    baseline = build_lineage(op, broker)
                    invalid = copy.deepcopy(op.streams['private/order_intents.jsonl'][0])
                    if value == 'missing':
                        del invalid['client_order_id']
                    else:
                        invalid['client_order_id'] = value
                    op.streams['private/order_intents.jsonl'].insert(0 if invalid_first else 1, invalid)
                    before = copy.deepcopy((op, broker))
                    result = build_lineage(op, broker)
                    self.assertEqual(result.positions, baseline.positions)
                    self.assertEqual(result.decisions, baseline.decisions)
                    self.assertEqual(result.decisions[0]['client_order_ids'], ['parent'])
                    self.assertEqual(result.coverage['status'], 'unknown')
                    self.assertIn('intent_lineage_unknown', result.reasons)
                    self.assertEqual((op, broker), before)

    def test_malformed_intent_identity_fields_remain_unknown_without_graph_edges(self):
        from watchdog.lineage import build_lineage
        for field in ('proposal_hash', 'plan_proposal_hash', 'candidate_id', 'dossier_hash',
                      'evidence_id', 'parent_client_order_id', 'plan'):
            for value in (None, '', 7, False, [], {'bad': 'value'}):
                with self.subTest(field=field, value=value):
                    op, broker = snapshots()
                    baseline = build_lineage(op, broker)
                    invalid = copy.deepcopy(op.streams['private/order_intents.jsonl'][0])
                    if field == 'plan_proposal_hash':
                        invalid['plan']['proposal_hash'] = value
                    else:
                        invalid[field] = value
                    op.streams['private/order_intents.jsonl'].insert(0, invalid)
                    before = copy.deepcopy((op, broker))
                    result = build_lineage(op, broker)
                    self.assertEqual(result.positions, baseline.positions)
                    self.assertEqual(result.decisions, baseline.decisions)
                    self.assertEqual(result.coverage['status'], 'unknown')
                    self.assertIn('intent_lineage_unknown', result.reasons)
                    self.assertEqual((op, broker), before)

    def test_incomplete_intent_alone_cannot_fabricate_order_identity(self):
        from watchdog.lineage import build_lineage
        for missing in ('client_order_id', 'proposal_hash', 'plan'):
            with self.subTest(missing=missing):
                op, broker = snapshots()
                intent = op.streams['private/order_intents.jsonl'][0]
                if missing == 'proposal_hash':
                    del intent['plan']['proposal_hash']
                else:
                    del intent[missing]
                result = build_lineage(op, broker)
                self.assertEqual(result.positions, [])
                self.assertEqual(result.decisions[0]['client_order_ids'], [])
                self.assertEqual(result.coverage['status'], 'unknown')
                self.assertIn('intent_lineage_unknown', result.reasons)

    def test_valid_envelope_proposal_without_plan_proposal_remains_attributable(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        intent = op.streams['private/order_intents.jsonl'][0]
        intent['proposal_hash'] = intent['plan'].pop('proposal_hash')
        result = build_lineage(op, broker)
        self.assertEqual(result.coverage['status'], 'complete')
        self.assertEqual(result.positions[0]['proposal_hash'], 'pa')
        self.assertEqual(result.positions[0]['candidate_id'], 'idea-a')

    def test_candidate_execution_tokens_cannot_complete_missing_chain(self):
        from watchdog.lineage import build_lineage
        for missing in ('review', 'plan_proposal'):
            for field, value in (('proposal_hash', 'pa'), ('client_order_id', 'parent'), ('evidence_id', 'ea')):
                with self.subTest(missing=missing, field=field):
                    op, broker = snapshots()
                    op.streams['candidates.jsonl'][0][field] = value
                    if missing == 'review':
                        op.streams['private/reviews.jsonl'] = []
                    else:
                        del op.streams['private/order_intents.jsonl'][0]['plan']['proposal_hash']
                    result = build_lineage(op, broker)
                    self.assertEqual(result.positions, [])
                    self.assertEqual(result.coverage['status'], 'unknown')
                    self.assertIn('intent_lineage_unknown', result.reasons)

    def test_intent_identity_without_authoritative_proposal_chain_is_unknown(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/reviews.jsonl'] = []
        op.streams['private/order_intents.jsonl'][0].update(candidate_id='idea-a', dossier_hash='da')
        result = build_lineage(op, broker)
        self.assertEqual(result.positions, [])
        self.assertIn('intent_lineage_unknown', result.reasons)

    def test_client_ledger_identity_cannot_replace_missing_intent_proposal(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        del op.streams['private/order_intents.jsonl'][0]['plan']['proposal_hash']
        op.streams['order_ledger.jsonl'] = [dict(candidate_id='idea-a', dossier_hash='da',
            proposal_hash='pa', client_order_id='parent', status='proposed')]
        result = build_lineage(op, broker)
        self.assertEqual(result.positions, [])
        self.assertIn('intent_lineage_unknown', result.reasons)

    def test_unreviewed_intent_proposal_cannot_join_via_ledger_client(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['order_ledger.jsonl'] = [dict(candidate_id='idea-a', dossier_hash='da',
            proposal_hash='pa', client_order_id='parent', status='proposed')]
        op.streams['private/order_intents.jsonl'][0]['plan']['proposal_hash'] = 'not-recorded'
        result = build_lineage(op, broker)
        self.assertEqual(result.positions, [])
        self.assertIn('intent_lineage_unknown', result.reasons)

    def test_conflicting_candidate_links_are_unknown(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/order_intents.jsonl'][0]['candidate_id'] = 'idea-b'
        result = build_lineage(op, broker)
        self.assertEqual(result.positions, [])
        self.assertEqual(result.coverage['ambiguous_order_refs'], 1)
        self.assertIn('lineage_contradictory', result.reasons)

    def test_incomplete_input_cannot_be_upgraded(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.complete = False
        result = build_lineage(op, broker)
        self.assertEqual(result.coverage['status'], 'unknown')
        self.assertEqual(result.positions[0]['ownership'], 'unknown')

    def test_explicit_evidence_id_links_rejection(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/order_intents.jsonl'] = []
        op.streams['order_ledger.jsonl'] = [dict(evidence_id='ea', status='rejected', reason='model_disagreement')]
        result = build_lineage(op, broker)
        self.assertEqual(result.decisions[0]['status'], 'rejected')
        self.assertEqual(result.decisions[0]['proposal_hashes'], ['pa'])

    def test_parent_legs_reduce_only_linked_quantity_not_legacy_holdings(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        broker.positions[0]['qty'] = D('11')
        broker.orders[0]['legs'] = [dict(id='exit-id', client_order_id='exit', symbol='ABC', side='sell',
                                      filled_qty=D('1'), filled_avg_price=D('12'), status='partially_filled', legs=[])]
        result = build_lineage(op, broker)
        p = result.positions[0]
        self.assertEqual(p['remaining_quantity'], D('1'))
        self.assertEqual(p['exit_quantity'], D('1'))
        self.assertEqual(p['exit_notional'], D('12'))
        self.assertEqual(p['ownership'], 'discrepancy')
        self.assertEqual(p['broker_symbol_quantity'], D('11'))
        self.assertEqual(p['protective_client_order_ids'], ['exit'])

    def test_repeated_intents_and_journal_observations_do_not_duplicate_fills(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/order_intents.jsonl'] *= 2
        op.streams['trade_journal.jsonl'] = [dict(client_order_id='parent', broker_order_id='broker-parent',
                                                cumulative_filled_quantity='2', quantity=2)] * 2
        result = build_lineage(op, broker)
        self.assertEqual(len(result.positions), 1)
        self.assertEqual(result.positions[0]['entry_quantity'], D('2'))
        self.assertEqual(result.coverage['duplicate_fill_observations'], 1)

    def test_cumulative_delta_needs_previous_trusted_identity_and_notional(self):
        from watchdog.lineage import cumulative_fill_delta
        current = dict(broker_order_id='o', cumulative_quantity=D('3'), cumulative_notional=D('32'))
        self.assertEqual(cumulative_fill_delta(current, None)['status'], 'unknown')
        previous = dict(broker_order_id='o', cumulative_quantity=D('2'), cumulative_notional=D('20'), trusted=True)
        delta = cumulative_fill_delta(current, previous)
        self.assertEqual((delta['quantity'], delta['notional']), (D('1'), D('12')))
        self.assertEqual(cumulative_fill_delta(current, {**current, 'trusted': True})['quantity'], D('0'))
        for previous in ({**previous, 'trusted': False}, {**previous, 'broker_order_id': 'other'},
                         {**previous, 'cumulative_quantity': D('4')},
                         {**current, 'trusted': True, 'cumulative_notional': D('31')}):
            self.assertEqual(cumulative_fill_delta(current, previous)['status'], 'unknown')

    def test_registered_replacement_exit_and_activity_exact_identity(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/protection_orders.jsonl'] = [dict(parent_client_order_id='parent', protection_client_order_id='replacement')]
        broker.orders.append(dict(id='replacement-id', client_order_id='replacement', symbol='ABC', side='sell',
                                  filled_qty=D('1'), filled_avg_price=D('12'), status='partially_filled', legs=[]))
        broker.activities = [dict(id='activity-id', activity_type='FILL', order_id='replacement-id', symbol='ABC',
                                  side='sell', qty=D('1'), price=D('12'), transaction_time=op.captured_at)]
        op.streams['trade_journal.jsonl'] = [dict(broker_order_id='replacement-id', quantity=1)]
        result = build_lineage(op, broker)
        self.assertEqual(result.positions[0]['remaining_quantity'], D('1'))
        self.assertEqual(result.positions[0]['fills'][0]['activity_id'], 'activity-id')
        self.assertEqual(result.coverage['unattributed_journal_rows'], 0)
        self.assertEqual(result.positions[0]['planned_exit_at'], op.streams['private/order_intents.jsonl'][0]['plan']['planned_exit_at'])
        self.assertEqual(result.positions[0]['fill_observations'][0]['broker_order_id'], 'broker-parent')

    def test_missing_referenced_parent_cannot_be_complete(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        broker.orders = []
        result = build_lineage(op, broker)
        self.assertEqual(result.coverage['status'], 'unknown')
        self.assertIn('referenced_order_missing', result.reasons)

    def test_journal_every_supplied_identity_must_corroborate_exact_order(self):
        from watchdog.lineage import build_lineage
        conflicts = [('candidate_id', 'idea-b'), ('dossier_hash', 'db'), ('proposal_hash', 'other-proposal'),
                     ('evidence_id', 'other-evidence'), ('broker_order_id', 'missing-broker'),
                     ('broker_order_id', 'exit-id'), ('client_order_id', 'exit'),
                     ('exit_client_order_id', 'exit'), ('parent_client_order_id', 'exit')]
        for field, value in conflicts:
            with self.subTest(field=field, value=value):
                op, broker = snapshots()
                broker.orders[0]['legs'] = [dict(id='exit-id', client_order_id='exit', symbol='ABC', side='sell',
                    filled_qty=D('0'), filled_avg_price=D('0'), status='new', legs=[])]
                row = dict(broker_order_id='broker-parent', client_order_id='parent',
                           parent_client_order_id='parent', candidate_id='idea-a', dossier_hash='da', proposal_hash='pa')
                row[field] = value
                op.streams['trade_journal.jsonl'] = [row]
                before = copy.deepcopy((op, broker))
                result = build_lineage(op, broker)
                self.assertEqual(result.coverage['unattributed_journal_rows'], 1)
                self.assertEqual(result.coverage['status'], 'unknown')
                self.assertIn('journal_lineage_unknown', result.reasons)
                self.assertEqual(result.positions[0]['entry_quantity'], D('2'))
                self.assertEqual(result.positions[0]['entry_notional'], D('20'))
                self.assertEqual((op, broker), before)

    def test_journal_evidence_must_belong_to_entry_proposal_not_just_candidate(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/reviews.jsonl'].append(dict(dossier_hash='da', proposal_hash='other-proposal', evidence_id='other-evidence'))
        op.streams['trade_journal.jsonl'] = [dict(broker_order_id='broker-parent', evidence_id='other-evidence')]
        result = build_lineage(op, broker)
        self.assertEqual(result.coverage['unattributed_journal_rows'], 1)
        self.assertEqual(result.coverage['status'], 'unknown')
        self.assertEqual(result.positions[0]['entry_notional'], D('20'))

    def test_journal_exit_identifiers_corroborate_parent_without_being_same_order(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        broker.orders[0]['legs'] = [dict(id='exit-id', client_order_id='exit', symbol='ABC', side='sell',
            filled_qty=D('1'), filled_avg_price=D('12'), status='filled', legs=[])]
        broker.positions[0]['qty'] = D('1')
        op.streams['trade_journal.jsonl'] = [dict(broker_order_id='exit-id', client_order_id='exit',
            exit_client_order_id='exit', parent_client_order_id='parent', candidate_id='idea-a',
            dossier_hash='da', proposal_hash='pa', evidence_id='ea')]
        result = build_lineage(op, broker)
        self.assertEqual(result.coverage['status'], 'complete')
        self.assertEqual(result.coverage['unattributed_journal_rows'], 0)
        self.assertEqual(result.positions[0]['exit_notional'], D('12'))

    def test_same_cumulative_quantity_with_different_notional_is_conflict(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['trade_journal.jsonl'] = [dict(client_order_id='parent', broker_order_id='broker-parent',
            cumulative_filled_quantity='2', cumulative_filled_notional=value) for value in ('20', '21')]
        result = build_lineage(op, broker)
        self.assertIn('fill_observation_conflict', result.reasons)
        self.assertEqual(result.coverage['status'], 'unknown')

    def test_over_exit_is_discrepancy_not_negative_owned_lot(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        broker.orders[0]['legs'] = [dict(id='exit-id', client_order_id='exit', symbol='ABC', side='sell',
                                      filled_qty=D('3'), filled_avg_price=D('12'), legs=[])]
        result = build_lineage(op, broker)
        self.assertIsNone(result.positions[0]['remaining_quantity'])
        self.assertIn('managed_exit_exceeds_entry', result.reasons)

    def test_dossier_only_legacy_candidate_can_link_without_invented_candidate_id(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        del op.streams['candidates.jsonl'][0]['candidate_id']
        result = build_lineage(op, broker)
        self.assertEqual(result.positions[0]['dossier_hash'], 'da')
        self.assertIsNone(result.positions[0]['candidate_id'])
        self.assertEqual(result.decisions[0]['status'], 'filled')

    def test_coverage_domains_unknown_override_summary_complete(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        broker.coverage['references'] = 'unknown'
        result = build_lineage(op, broker)
        self.assertEqual(result.positions[0]['ownership'], 'unknown')
        self.assertFalse(result.positions[0]['fill_observations'][0]['trusted'])

    def test_contradictory_intent_envelopes_cannot_be_rescued_by_union(self):
        from watchdog.lineage import build_lineage
        for field, value in (('proposal_hash', 'other-proposal'), ('parent_client_order_id', 'other-parent')):
            with self.subTest(field=field):
                op, broker = snapshots()
                # Both proposals legitimately belong to this candidate, but
                # not to the same envelope/plan pair.
                op.streams['private/reviews.jsonl'].append(dict(dossier_hash='da', proposal_hash='other-proposal'))
                op.streams['private/order_intents.jsonl'][0][field] = value
                result = build_lineage(op, broker)
                self.assertEqual(result.positions, [])
                self.assertEqual(result.coverage['ambiguous_order_refs'], 1)
                self.assertEqual(result.decisions[0]['coverage'], 'unknown')
                self.assertIn('lineage_contradictory', result.reasons)

    def test_separate_valid_proposals_for_same_candidate_remain_owned(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/reviews.jsonl'].append(dict(dossier_hash='da', proposal_hash='other-proposal'))
        intent = copy.deepcopy(op.streams['private/order_intents.jsonl'][0])
        intent.update(client_order_id='second', parent_client_order_id='second', proposal_hash='other-proposal')
        intent['plan']['proposal_hash'] = 'other-proposal'
        op.streams['private/order_intents.jsonl'].append(intent)
        broker.orders.append(dict(broker.orders[0], id='broker-second', client_order_id='second'))
        broker.positions[0]['qty'] = D('4')
        result = build_lineage(op, broker)
        self.assertEqual(len(result.positions), 2)
        self.assertEqual(result.coverage['status'], 'complete')
        self.assertEqual({p['proposal_hash'] for p in result.positions}, {'pa', 'other-proposal'})

    def test_conflicting_intent_plans_do_not_choose_first(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        intent = copy.deepcopy(op.streams['private/order_intents.jsonl'][0])
        intent['plan']['stop'] = 8
        op.streams['private/order_intents.jsonl'].append(intent)
        result = build_lineage(op, broker)
        self.assertEqual(result.positions, [])
        self.assertIn('intent_plan_conflict', result.reasons)

    def test_unidentified_candidate_is_visible_unknown_decision(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['candidates.jsonl'].append(dict(symbol='ABC'))
        result = build_lineage(op, broker)
        self.assertEqual(len(result.decisions), 3)
        self.assertEqual(result.decisions[-1]['coverage'], 'unknown')
        self.assertIsNone(result.decisions[-1]['candidate_id'])
        self.assertIn('candidate_identity_unknown', result.reasons)
        self.assertEqual(set(result.decisions[-1]), set(result.decisions[0]))

    def test_activity_order_identity_does_not_override_side_or_symbol_conflict(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        broker.activities = [dict(id='activity', activity_type='FILL', order_id='broker-parent',
                                  symbol='WRONG', side='buy', qty=D('2'), price=D('10'), transaction_time=op.captured_at)]
        result = build_lineage(op, broker)
        self.assertEqual(result.positions[0]['fills'], [])
        self.assertIn('activity_order_mismatch', result.reasons)

    def test_untrusted_current_or_reversed_observation_clock_has_unknown_delta(self):
        from watchdog.lineage import cumulative_fill_delta
        current = dict(broker_order_id='o', cumulative_quantity='3', cumulative_notional='32',
                       captured_at='2026-10-07T15:00:00Z', trusted=True)
        previous = dict(broker_order_id='o', cumulative_quantity='2', cumulative_notional='20',
                        captured_at='2026-10-07T16:00:00Z', trusted=True)
        self.assertEqual(cumulative_fill_delta(current, previous)['status'], 'unknown')
        previous['captured_at'] = '2026-10-07T14:00:00Z'
        current['trusted'] = False
        self.assertEqual(cumulative_fill_delta(current, previous)['status'], 'unknown')

    def test_review_only_decision_keeps_reviewer_outcome_separate(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/order_intents.jsonl'] = []
        op.streams['private/reviews.jsonl'][0]['reviews'] = [dict(decision='HOLD')]
        result = build_lineage(op, broker)
        self.assertEqual(result.decisions[0]['status'], 'reviewer_rejected')
        self.assertEqual(result.decisions[0]['review_decisions'], ['HOLD'])
        self.assertEqual(result.decisions[0]['evidence_ids'], ['ea'])

    def test_planned_prices_are_decimal_in_memory(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        p = build_lineage(op, broker).positions[0]
        self.assertIsInstance(p['stop'], D)
        self.assertIsInstance(p['target'], D)

    def test_authoritative_unfilled_order_is_not_a_research_only_outcome(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        broker.orders[0].update(filled_qty=D('0'), status='accepted')
        result = build_lineage(op, broker)
        self.assertEqual(result.positions, [])
        self.assertEqual(result.decisions[0]['status'], 'submitted_unfilled')
        self.assertEqual(result.decisions[0]['broker_statuses'], ['accepted'])

    def test_legacy_buy_without_identity_is_unattributed(self):
        from watchdog.lineage import build_lineage
        op, broker = snapshots()
        op.streams['private/order_intents.jsonl'] = []
        op.streams['trade_journal.jsonl'] = [dict(symbol='ABC', action='BUY', quantity=2, status='filled')]
        result = build_lineage(op, broker)
        self.assertEqual(result.positions, [])
        self.assertEqual(result.coverage['unattributed_journal_rows'], 1)
        self.assertIn('journal_lineage_unknown', result.reasons)


if __name__ == '__main__':
    unittest.main()
