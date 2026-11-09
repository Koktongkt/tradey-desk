"""Synthetic prospective cutover; no provider or broker traffic."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

from offline_test_guard import install
install()
import opportunity_activation as activation
import opportunity_fixtures as f
import opportunity_identity as identity
import opportunity_state as state
import sqlite_ledger as storage


class CutoverTests(unittest.TestCase):
    def setUp(self):
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        f.make_root(self.root)
        (self.root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols': []}))

    def api(self):
        import opportunity_cutover
        return opportunity_cutover

    def activate(self):
        api = self.api()
        manifest = api.prepare_manifest(self.root)
        result = api.activate_prospective(self.root, manifest,
            approved_manifest_sha256=api.manifest_digest(manifest))
        return manifest, result

    def append_candidate(self, dossier='a'*64, period='2026-Q3'):
        resolution = f.synthetic_resolution(period=period)
        storage.append_jsonl(self.root/state.POLICY_STREAM, f.policy_row(
            'identity_resolution', resolution=identity.candidate_identity(resolution)))
        row = f.candidate_link(dossier, resolution.event_id, state.allowance_identifier(resolution.event_id, 0))
        row['opportunity_identity'] = identity.candidate_identity(resolution)
        row['symbol'] = 'ACME'
        row['opportunity_baseline_id'] = self.api().active_baseline(
            storage.read_stream_snapshot_readonly(self.root, self.api().BASELINE_STREAMS))['baseline_id']
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM, row)
        return resolution, row

    def test_cutover_module_exists(self):
        self.assertIsNotNone(importlib.util.find_spec('opportunity_cutover'),
                             'explicit prospective cutover API not implemented')

    def test_legacy_gaps_are_excluded_but_preserved(self):
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,
                            f.gap_review_row(with_symbol=True, with_hint=False))
        storage.append_jsonl(self.root/state.TRADE_JOURNAL_STREAM, f.gap_trade_row(action='BUY'))
        before = (self.root/state.REVIEWS_STREAM).read_bytes()
        manifest, result = self.activate()
        self.assertEqual(result['policy_version'], 2)
        self.assertEqual(activation.activation_version(self.root), 2)
        index = state.load_index(self.root)
        self.assertEqual(state.incomplete_history(index), frozenset())
        self.assertEqual(index.unknown_history_blocks, {})
        self.assertEqual((self.root/state.REVIEWS_STREAM).read_bytes(), before)
        self.assertEqual(index.prospective_baseline['baseline_id'], manifest['baseline']['baseline_id'])

    def test_post_cutover_hold_spends_event_across_dossiers(self):
        self.activate()
        resolution, first = self.append_candidate()
        self.assertEqual(state.require_current_allowance(self.root, first).outcome, 'eligible')
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,
                            f.review_row('a'*64, 'fresh-review', [{'decision':'HOLD'}]))
        _, second = self.append_candidate('b'*64)
        self.assertEqual(state.require_current_allowance(self.root, second).reason, 'unchanged_opportunity')
        _, new_event = self.append_candidate('c'*64, '2026-Q4')
        self.assertEqual(state.require_current_allowance(self.root, new_event).outcome, 'eligible')

    def test_post_cutover_unlinked_review_blocks(self):
        self.activate()
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,
                            f.gap_review_row(with_symbol=True, with_hint=False))
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)

    def test_post_cutover_hash_but_no_candidate_binding_blocks(self):
        self.activate()
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,
                            f.review_row('a'*64, 'unbound', [{'decision':'HOLD'}]))
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)

    def test_post_cutover_candidate_needs_baseline_id(self):
        self.activate()
        resolution = f.synthetic_resolution()
        storage.append_jsonl(self.root/state.POLICY_STREAM, f.policy_row(
            'identity_resolution', resolution=identity.candidate_identity(resolution)))
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM, f.candidate_link(
            'a'*64, resolution.event_id, state.allowance_identifier(resolution.event_id, 0)))
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)

    def test_legacy_candidate_is_not_entry_authority(self):
        resolution = f.synthetic_resolution()
        storage.append_jsonl(self.root/state.POLICY_STREAM, f.policy_row(
            'identity_resolution', resolution=identity.candidate_identity(resolution)))
        row = f.candidate_link('a'*64, resolution.event_id, state.allowance_identifier(resolution.event_id, 0))
        row['opportunity_identity'] = identity.candidate_identity(resolution)
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM, row)
        self.activate()
        self.assertNotEqual(state.require_current_allowance(self.root, row).outcome, 'eligible')

    def test_old_reader_refuses_v2(self):
        self.activate()
        with self.assertRaises(activation.ActivationStateError):
            activation.require_supported_activation(self.root, supported=1)

    def test_idempotent_but_second_reset_forbidden(self):
        manifest, _ = self.activate()
        api = self.api()
        before = (self.root/state.POLICY_STREAM).read_bytes()
        result = api.activate_prospective(self.root, manifest, approved_manifest_sha256=api.manifest_digest(manifest))
        self.assertFalse(result['appended_activation'])
        self.assertEqual((self.root/state.POLICY_STREAM).read_bytes(), before)
        with self.assertRaises(api.CutoverError):
            api.prepare_manifest(self.root)

    def test_concurrent_append_at_final_writer_refuses_activation(self):
        from unittest.mock import patch
        api = self.api()
        manifest = api.prepare_manifest(self.root)
        original = storage.append_jsonl
        def race(path, row, **kwargs):
            original(self.root/'order_ledger.jsonl', {'status':'concurrent'})
            return original(path, row, **kwargs)
        with patch.object(storage, 'append_jsonl', side_effect=race):
            with self.assertRaises((api.CutoverError, storage.LedgerError)):
                api.activate_prospective(self.root, manifest,
                    approved_manifest_sha256=api.manifest_digest(manifest))
        self.assertEqual(activation.activation_version(self.root), 0)

    def test_stale_manifest_has_no_partial_write(self):
        api = self.api()
        manifest = api.prepare_manifest(self.root)
        storage.append_jsonl(self.root/'order_ledger.jsonl', {'status':'synthetic-changed'})
        with self.assertRaises(api.CutoverError):
            api.activate_prospective(self.root, manifest, approved_manifest_sha256=api.manifest_digest(manifest))
        self.assertEqual(activation.activation_version(self.root), 0)

    def test_wrong_digest_and_root_refused(self):
        api = self.api()
        manifest = api.prepare_manifest(self.root)
        with self.assertRaises(api.CutoverError):
            api.activate_prospective(self.root, manifest, approved_manifest_sha256='f'*64)
        changed = copy.deepcopy(manifest)
        changed['baseline']['root'] = '/not-this-root'
        with self.assertRaises(api.CutoverError):
            api.activate_prospective(self.root, changed, approved_manifest_sha256=api.manifest_digest(changed))
        self.assertEqual(activation.activation_version(self.root), 0)

    def test_entry_rejects_wrong_baseline_tag(self):
        self.activate()
        _, row = self.append_candidate()
        row['opportunity_baseline_id'] = 'f'*64
        self.assertNotEqual(state.require_current_allowance(self.root, row).outcome, 'eligible')

    def test_radar_binds_trusted_baseline_before_hash(self):
        from unittest.mock import patch
        import alpha_radar as radar
        self.activate()
        pages = f.earnings_pages()
        resolution = identity.resolve_event('ACME', pages, known_resolutions=())
        context = state.load_policy_context(self.root)
        token = radar._policy_acquisition.set((self.root.resolve(), resolution, pages, None))
        try:
            with patch.object(radar, 'ROOT', self.root):
                result = radar._bind_policy_candidate({'symbol':'ACME'}, context)
                self.assertEqual(result.get('opportunity_baseline_id'),
                                 context.index.prospective_baseline['baseline_id'])
                radar._final_policy_check(result)
        finally:
            radar._policy_acquisition.reset(token)

    def test_radar_strips_model_baseline_claim(self):
        import alpha_radar as radar
        self.assertNotIn('opportunity_baseline_id', radar._strip_policy_metadata(
            {'symbol':'ACME', 'opportunity_baseline_id':'f'*64}))

    def test_radar_rejects_stale_worker_without_policy_authority(self):
        from unittest.mock import patch
        import alpha_radar as radar
        self.activate()
        with patch.object(radar, 'ROOT', self.root):
            with self.assertRaises(radar.CandidateRejection):
                radar._final_policy_check({'symbol':'ACME'})

    def test_legacy_candidate_not_reused_in_either_cache_helper(self):
        import alpha_radar as radar
        import datetime as dt
        from unittest.mock import patch
        old = {'symbol':'ACME', 'dossier_hash':'e'*64,
               'sources_verified_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM, old)
        self.activate()
        with patch.object(radar, 'ROOT', self.root), patch.object(radar, 'candidate_preflight', return_value=[]), patch.object(radar, 'qualified', return_value=True):
            self.assertIsNone(radar.fresh_verified_candidate(self.root/state.CANDIDATES_STREAM))
            self.assertIsNone(radar.reusable_fresh_candidate(self.root/state.CANDIDATES_STREAM,
                                                           self.root/state.REVIEWS_STREAM))

    def test_prefix_tampering_is_rejected_even_with_valid_descriptor_id(self):
        from dataclasses import replace
        api = self.api()
        storage.append_jsonl(self.root/'order_ledger.jsonl', {'status':'old'})
        self.activate()
        snapshot = storage.read_stream_snapshot_readonly(self.root, api.BASELINE_STREAMS)
        rows = dict(snapshot.rows)
        rows['order_ledger.jsonl'] = ({'status':'changed'},)
        with self.assertRaises(api.CutoverError):
            api.active_baseline(replace(snapshot, rows=rows))

    def test_post_cutover_disagreement_cannot_be_erased_by_marker(self):
        self.activate()
        _, first = self.append_candidate()
        storage.append_jsonl(self.root/state.REVIEWS_STREAM, f.review_row(
            'a'*64, 'disagreement', [{'decision':'APPROVE'}, {'decision':'HOLD'}]))
        storage.append_jsonl(self.root/state.REVIEWS_STREAM, f.review_row(
            'a'*64, 'marker', [{'decision':'reconciliation_blocked'}]))
        _, second = self.append_candidate('b'*64)
        self.assertEqual(state.require_current_allowance(self.root, second).reason, 'unchanged_opportunity')

    def test_legacy_admin_cannot_create_descriptorless_v2(self):
        import opportunity_admin as admin
        manifest = {'manifest_version':1, 'records':[], 'activation':{'policy_version':2}}
        before = activation.activation_version(self.root)
        with self.assertRaises(admin.OpportunityAdminError):
            admin.activate(self.root, manifest, approved_manifest_sha256=admin.canonical_manifest_digest(manifest))
        self.assertEqual(activation.activation_version(self.root), before)

    def test_manual_only_baseline_refuses_automatic_condition_records(self):
        self.activate()
        resolution, _ = self.append_candidate()
        storage.append_jsonl(self.root/state.POLICY_STREAM, f.policy_row(
            'condition_approval', condition_id='not-enabled', event_id=resolution.event_id,
            condition={'metric':'completed_close_usd'}))
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)

    def test_no_automatic_conditions(self):
        self.activate()
        self.assertEqual(state.load_index(self.root).conditions, {})

    def test_legacy_dissent_ignored_for_new_dossier_same_event(self):
        resolution = f.synthetic_resolution()
        storage.append_jsonl(self.root/state.POLICY_STREAM, f.policy_row(
            'identity_resolution', resolution=identity.candidate_identity(resolution)))
        storage.append_jsonl(self.root/state.CANDIDATES_STREAM, f.candidate_link(
            'd'*64, resolution.event_id, state.allowance_identifier(resolution.event_id, 0)))
        storage.append_jsonl(self.root/state.REVIEWS_STREAM,
                            f.review_row('d'*64, 'legacy', [{'decision':'HOLD'}]))
        self.activate()
        _, fresh = self.append_candidate()
        self.assertEqual(state.require_current_allowance(self.root, fresh).outcome, 'eligible')


from test_opportunity_execution import ExecutionCase, _dossier


class ProspectiveExecutionTests(ExecutionCase):
    """Real entry/review/intent orchestration, synthetic transport only."""
    active = False

    def setUp(self):
        super().setUp()
        import opportunity_cutover as cut
        manifest = cut.prepare_manifest(self.root)
        cut.activate_prospective(self.root, manifest,
                                 approved_manifest_sha256=cut.manifest_digest(manifest))
        storage.append_jsonl(self.root/state.POLICY_STREAM, f.policy_row(
            'identity_resolution', resolution=f.synthetic_resolution_payload()))
        self.candidate['opportunity_baseline_id'] = manifest['baseline']['baseline_id']
        self.candidate['dossier_hash'] = _dossier(self.candidate)
        self.dossier = self.candidate['dossier_hash']
        self.write_candidate()

    def test_v2_current_approval_can_reach_exact_intent(self):
        code, out = self.run_locked()
        self.assertEqual(code, 0, out)
        self.assertEqual(len(self.reviewer_calls), 1)
        self.assertEqual(len(self.intents()), 1)
        self.assertIn('place', self.broker_operations)

    def test_v2_held_position_blocks_before_paid_review(self):
        code, out = self.run_locked(snapshot=self.snapshot(positions=[self.held_row()]))
        self.assertEqual(code, 2, out)
        self.assertEqual(self.reviewer_calls, [])
        self.assertNotIn('place', self.broker_operations)

    def test_v2_hold_blocks_the_next_regenerated_dossier(self):
        self.spend()
        self.write_candidate(thesis='Different generated wording, same event')
        code, out = self.run_locked()
        self.assertEqual(code, 2, out)
        self.assertIn('unchanged_opportunity', out)
        self.assertEqual(self.reviewer_calls, [])
        self.assertNotIn('place', self.broker_operations)


if __name__ == '__main__':
    unittest.main()
