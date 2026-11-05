"""Synthetic administrative resolution/reopening/activation boundary tests.

No operational roots, live effects, real issuers or Task4 entry evaluation.
"""
import datetime as dt
import hashlib
import json
import os
import tempfile
import unittest
from decimal import Decimal
from pathlib import Path

import opportunity_fixtures as fixtures
import sqlite_ledger as storage

POLICY = 'private/opportunity_policy.jsonl'
REVIEWS = 'private/reviews.jsonl'
CANDIDATES = 'candidates.jsonl'
CLAIMS = 'private/opportunity_reopening_claims.jsonl'
DOSSIER_A = 'a' * 64
DOSSIER_B = 'b' * 64
EVIDENCE_1 = 'evidence-1'
NOW = dt.datetime(2026, 11, 4, 13, 0, 0, tzinfo=dt.timezone.utc)
FAR_FUTURE = '2030-01-01T00:00:00+00:00'
CAPTURE_REF = fixtures.synthetic_capture_ref()


def canonical_bytes(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'),
                      allow_nan=False, ensure_ascii=False).encode('utf-8')


def digest_of(value):
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


class OpportunityAdminTests(unittest.TestCase):
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
        self.now = NOW

    def write(self, name, rows):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        for row in rows:
            storage.append_jsonl(path, row)

    def snapshot_bytes(self):
        return {path: (path.read_bytes(), path.stat().st_mtime_ns)
                for path in self.root.rglob('*') if path.is_file()}

    def build_history(self, *, decision='HOLD'):
        """Activated history with one bound dossier and one spending review."""
        import opportunity_state as state
        resolution = fixtures.synthetic_resolution()
        self.write(POLICY, [
            fixtures.policy_row('activation', policy_version=1, manifest_sha256='a' * 64),
            fixtures.policy_row('identity_resolution',
                                resolution=fixtures.synthetic_resolution_payload()),
        ])
        self.write(CANDIDATES, [
            fixtures.candidate_link(DOSSIER_A, resolution.event_id,
                                    state.allowance_identifier(resolution.event_id, 0)),
        ])
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1, [{'decision': decision}]),
        ])
        return resolution

    def condition_record(self, resolution, **overrides):
        import opportunity_state as state
        record = {
            'metric': 'completed_close_usd', 'operator': '>=', 'threshold': '50',
            'units': 'USD', 'source_kind': 'massive_consolidated_completed_daily',
            'expires_at': FAR_FUTURE, 'observation_max_age_seconds': 86400,
            'baseline_ref': 'baseline-1',
            'allowance_id': state.allowance_identifier(resolution.event_id, 0),
        }
        record.update(overrides)
        return record

    def manifest(self, resolution, **overrides):
        fields = {
            'manifest_version': 1,
            'records': [
                {'record_type': 'document_alias', 'schema_version': 1,
                 'timestamp': '2026-11-04T12:00:00+00:00',
                 'alias': 'alias-a', 'event_id': resolution.event_id},
                {'record_type': 'condition_approval', 'schema_version': 1,
                 'timestamp': '2026-11-04T12:00:00+00:00', 'condition_id': 'cond-1',
                 'event_id': resolution.event_id,
                 'condition': self.condition_record(resolution)},
            ],
        }
        fields.update(overrides)
        return fields

    def approved_condition(self, resolution):
        import opportunity_admin as admin
        return admin.Condition(
            'cond-1', resolution.event_id,
            self.condition_record(resolution)['allowance_id'],
            'completed_close_usd', '>=', '50', 'USD',
            'massive_consolidated_completed_daily', FAR_FUTURE, 86400, 'baseline-1')

    def adapter_result(self, *, value='52.5', **overrides):
        result = {'metric': 'completed_close_usd', 'value': value, 'units': 'USD',
                  'source': 'massive_consolidated_completed_daily',
                  'market_prices_at': '2026-11-04T12:00:00+00:00'}
        result.update(overrides)
        return result

    def observation(self, resolution, **kwargs):
        import opportunity_admin as admin
        result = self.adapter_result(**kwargs)
        return admin.observe_completed_close(
            result, event_id=resolution.event_id, evidence_ref=CAPTURE_REF)

    def sealed_claim(self, resolution):
        import opportunity_admin as admin
        import opportunity_state as state
        self.build_history()
        self.write(POLICY, [
            fixtures.policy_row('condition_approval', condition_id='cond-1',
                                event_id=resolution.event_id,
                                condition=self.condition_record(resolution)),
        ])
        observation = self.observation(resolution)
        index = state.load_index(self.root)
        return admin.make_reopening_claim(index, resolution, observation, now=self.now)

    def scoped_history(self):
        resolution = self.build_history()
        source = fixtures.review_row(DOSSIER_B, 'unresolved-review', [{'decision': 'HOLD'}])
        self.write(REVIEWS, [source])
        unresolved = {'dossier_hash': DOSSIER_B, 'status': 'unknown', 'reason': 'missing original'}
        self.write(POLICY, [fixtures.policy_row('identity_resolution', unresolved=unresolved)])
        record = fixtures.policy_row('identity_resolution', unresolved={
            **unresolved, 'issuer_scope': {'binding_event_id': resolution.event_id,
                                         'issuer_cik': resolution.issuer.cik}},
            source={'stream': REVIEWS, 'sequence': 2, 'row_sha256': digest_of(source)})
        return resolution, {'manifest_version': 1, 'records': [record]}

    def other_issuer_payload(self):
        payload = fixtures.synthetic_resolution_payload(period='2026-Q2', cik='0001888888')
        # Change the fictional SEC locator too; a CIK alone is not evidence.
        return json.loads(json.dumps(payload).replace('1999999', '1888888'))

    def test_legacy_hash_only_candidate_is_auditable_without_permission(self):
        import opportunity_admin as admin
        import opportunity_state as state
        self.write(CANDIDATES, [{'candidate_id': 'synthetic-legacy',
                                 'dossier_hash': DOSSIER_A, 'sources': []}])
        self.write(REVIEWS, [fixtures.review_row(
            DOSSIER_A, EVIDENCE_1, [{'decision': 'HOLD'}])])
        before = self.snapshot_bytes()
        report = admin.audit_history(self.root)
        self.assertEqual(report['incomplete_history_cases'], [DOSSIER_A])
        self.assertEqual(state.load_index(self.root).dossier_allowances, {})
        self.assertEqual(self.snapshot_bytes(), before)
        for partial in ({'event_id': 'synthetic-event'},
                        {'allowance_id': 'synthetic-allowance'}):
            with self.subTest(partial=partial):
                self.write(CANDIDATES, [{'dossier_hash': DOSSIER_A, **partial}])
                with self.assertRaises(state.OpportunityStateError):
                    state.load_index(self.root)

    def test_manifest_source_binds_legacy_review_and_spends_without_rewriting(self):
        import opportunity_admin as admin
        import opportunity_state as state
        review = fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                     [{'action': 'HOLD', 'symbol': 'SYNTH'}])
        self.write(CANDIDATES, [{'dossier_hash': DOSSIER_A}])
        self.write(REVIEWS, [review])
        resolution = fixtures.synthetic_resolution()
        record = fixtures.policy_row(
            'identity_resolution', resolution=fixtures.synthetic_resolution_payload(),
            source={'stream': REVIEWS, 'sequence': 1, 'row_sha256': digest_of(review)})
        manifest = {'manifest_version': 1, 'records': [record],
                    'activation': {'policy_version': 1}}
        before = self.snapshot_bytes()
        report = admin.validate_manifest(self.root, manifest)
        self.assertTrue(report['valid'], report['errors'])
        self.assertEqual(self.snapshot_bytes(), before)
        # A projected bootstrap exercises index semantics without approval/apply.
        from dataclasses import replace
        snapshot = state.load_index(self.root).snapshot
        projected = state._build(replace(snapshot, rows={
            **snapshot.rows, POLICY: tuple(report['records'])}))
        allowance = state.allowance_identifier(resolution.event_id, 0)
        self.assertEqual(projected.dossier_allowances[DOSSIER_A], allowance)
        self.assertEqual(projected.allowance_reviews[allowance], (review,))
        self.assertTrue(state._spends(projected.allowance_reviews[allowance][0]))
        self.assertFalse(state.incomplete_history(projected))
        next_allowance = state.allowance_identifier(resolution.event_id, 1)
        grant = fixtures.policy_row('reopen_grant', event_id=resolution.event_id,
                                    generation=1, prior_allowance_id=allowance,
                                    allowance_id=next_allowance)
        reopened = state._build(replace(snapshot, rows={
            **snapshot.rows, POLICY: (record, grant)}))
        self.assertEqual(state._current_allowance(reopened, resolution.event_id),
                         next_allowance)
        self.assertEqual(reopened.dossier_allowances[DOSSIER_A], allowance)
        self.assertEqual(reopened.allowance_reviews[allowance], (review,))
        self.assertNotIn(next_allowance, reopened.allowance_reviews)
        other = fixtures.policy_row(
            'identity_resolution', resolution=fixtures.synthetic_resolution_payload(period='2026-Q2'),
            source=record['source'])
        with self.assertRaises(state.OpportunityStateError):
            state._build(replace(snapshot, rows={**snapshot.rows, POLICY: (record, other)}))
        changed = json.loads(json.dumps(record))
        changed['source']['row_sha256'] = '0' * 64
        with self.assertRaises(state.OpportunityStateError):
            state._build(replace(snapshot, rows={**snapshot.rows, POLICY: (changed,)}))

    def test_hashless_legacy_review_audit_reports_sources_but_index_stays_closed(self):
        import opportunity_admin as admin
        import opportunity_state as state
        legacy = {'evidence_id': 'synthetic-old-review',
                  'timestamp': '2026-01-01T00:00:00Z',
                  'reviews': [{'action': 'BUY', 'symbol': 'SYNTH'}]}
        self.write(REVIEWS, [legacy, fixtures.review_row(
            DOSSIER_A, EVIDENCE_1, [{'decision': 'REJECT'}])])
        self.write(CANDIDATES, [{'dossier_hash': DOSSIER_A}])
        before = self.snapshot_bytes()
        report = admin.audit_history(self.root)
        self.assertEqual(report['status'], 'blocked')
        self.assertEqual(report['blockers'], ['historical_dossier_hash_missing'])
        self.assertEqual(report['history_row_counts'][REVIEWS], 2)
        self.assertEqual(report['missing_dossier_sources'], [
            {'stream': REVIEWS, 'sequence': 1, 'row_sha256': digest_of(legacy)}])
        self.assertEqual(self.snapshot_bytes(), before)
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(self.root)
        self.assertFalse(admin.validate_manifest(self.root, {
            'manifest_version': 1, 'records': [],
            'activation': {'policy_version': 1}})['valid'])
        # A known legacy gap never hides other malformed policy state.
        self.write(CANDIDATES, [{'dossier_hash': DOSSIER_A, 'event_id': 'partial'}])
        with self.assertRaises(admin.OpportunityAdminError):
            admin.audit_history(self.root)

    def test_legacy_action_reviews_spend_without_becoming_approval(self):
        import opportunity_state as state
        for action in ('HOLD', 'BUY'):
            review = fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                         [{'action': action, 'symbol': 'SYNTH'}])
            self.assertTrue(state._spends(review))
            # A proposed BUY is not normalized dual-review approval or retry.
            self.assertTrue(state._completed_dissent(review))
            self.assertFalse(state._dual_approval_row(review))
        for output in ({}, {'action': 'UNKNOWN'},
                       {'action': 'BUY', 'decision': 'execution_retryable'},
                       {'action': 'HOLD', 'decision': 'reconciliation_blocked'}):
            self.assertFalse(state._spends(fixtures.review_row(
                DOSSIER_A, EVIDENCE_1, [output])))

    def test_reviewed_scope_import_replay_unrelated_and_same_issuer(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution, manifest = self.scoped_history()
        (self.root / 'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
        before = self.snapshot_bytes()
        report = admin.validate_manifest(self.root, manifest)
        self.assertTrue(report['valid'], report)
        audit = admin.audit_history(self.root)
        self.assertEqual(audit['unscoped_unresolved_cases'], [DOSSIER_B])
        self.assertEqual(self.snapshot_bytes(), before)
        for digest in (None, '0' * 64):
            with self.assertRaises(admin.OpportunityAdminError):
                admin.import_manifest(self.root, manifest, approved_manifest_sha256=digest)
        self.assertEqual(self.snapshot_bytes(), before)
        digest = admin.canonical_manifest_digest(manifest)
        self.assertEqual(admin.import_manifest(self.root, manifest, approved_manifest_sha256=digest)['appended'], 1)
        index = state.load_index(self.root)
        scope = manifest['records'][0]['unresolved']['issuer_scope']
        self.assertEqual(index.unresolved_issuer_scopes[DOSSIER_B], scope)
        after = self.snapshot_bytes()
        self.assertEqual(admin.import_manifest(self.root, manifest, approved_manifest_sha256=digest)['appended'], 0)
        self.assertEqual(admin.audit_history(self.root)['unresolved_issuer_scopes'][DOSSIER_B], scope)
        self.assertEqual(self.snapshot_bytes(), after)
        context = state.load_policy_context(self.root)
        from opportunity_identity import _load_binding
        other = _load_binding(self.other_issuer_payload())
        same = fixtures.synthetic_resolution(period='2026-Q2')
        self.assertEqual(state.candidate_policy(context, other, symbol=fixtures.SYMBOL).outcome, 'eligible')
        self.assertEqual(state.candidate_policy(context, same, symbol=fixtures.SYMBOL).outcome, 'unknown')
        self.assertIn(DOSSIER_B, state.load_index(self.root).unresolved_dossiers)
        self.assertEqual(state.event_decision(index, resolution, dossier_hash=DOSSIER_B).outcome, 'unknown')

    def test_unscoped_history_is_typed_unavailable_and_activation_insufficient(self):
        import opportunity_admin as admin
        import opportunity_state as state
        _, manifest = self.scoped_history()
        (self.root / 'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
        context = state.load_policy_context(self.root)
        with self.assertRaisesRegex(state.OpportunityStateError, 'opportunity_policy_state_unavailable'):
            state.candidate_policy(context, fixtures.synthetic_resolution(period='2026-Q2'), symbol=fixtures.SYMBOL)
        empty = {'manifest_version': 1, 'records': [], 'activation': {'policy_version': 1}}
        before = self.snapshot_bytes()
        self.assertFalse(admin.validate_manifest(self.root, empty)['valid'])
        with self.assertRaises(admin.OpportunityAdminError):
            admin.activate(self.root, empty, approved_manifest_sha256=admin.canonical_manifest_digest(empty))
        self.assertEqual(self.snapshot_bytes(), before)
        manifest['activation'] = {'policy_version': 1}
        self.assertTrue(admin.validate_manifest(self.root, manifest)['valid'])

    def test_scopes_reject_bad_binding_cik_source_and_model_metadata(self):
        import copy
        import dataclasses
        import opportunity_admin as admin
        import opportunity_state as state
        _, manifest = self.scoped_history()
        mutations = [
            lambda r: r['unresolved']['issuer_scope'].update(issuer_cik='0001888888'),
            lambda r: r['unresolved']['issuer_scope'].update(binding_event_id='oe1:' + '0' * 64),
            lambda r: r['unresolved']['issuer_scope'].update(extra=True),
            lambda r: r['unresolved'].update(issuer_scope=None),
            lambda r: r['unresolved'].update(dossier_hash='c' * 64),
            lambda r: r['source'].update(row_sha256='0' * 64),
            lambda r: r['source'].update(sequence=True),
            lambda r: r['source'].update(extra='model'),
            lambda r: r.pop('source'),
            lambda r: r.update(resolution=fixtures.synthetic_resolution_payload()),
        ]
        # A valid digest of a different dossier's source is still not association.
        first = storage.read_jsonl_stream_readonly(self.root / REVIEWS)[0]
        mutations.append(lambda r: r.update(source={'stream': REVIEWS, 'sequence': 1, 'row_sha256': digest_of(first)}))
        before = self.snapshot_bytes()
        index = state.load_index(self.root)
        for mutation in mutations:
            bad = copy.deepcopy(manifest)
            mutation(bad['records'][0])
            with self.subTest(record=bad):
                self.assertFalse(admin.validate_manifest(self.root, bad)['valid'])
                with self.assertRaises(admin.OpportunityAdminError):
                    admin.import_manifest(self.root, bad, approved_manifest_sha256=admin.canonical_manifest_digest(bad))
                rows = dict(index.snapshot.rows)
                rows[POLICY] += tuple(bad['records'])
                with self.assertRaises(state.OpportunityStateError):
                    state._build(dataclasses.replace(index.snapshot, rows=rows))
        self.assertEqual(self.snapshot_bytes(), before)

    def test_scope_conflict_erasure_and_seal_tamper_fail_closed(self):
        import copy
        import dataclasses
        import opportunity_admin as admin
        import opportunity_state as state
        _, manifest = self.scoped_history()
        other = self.other_issuer_payload()
        self.write(POLICY, [fixtures.policy_row('identity_resolution', resolution=other)])
        admin.import_manifest(self.root, manifest, approved_manifest_sha256=admin.canonical_manifest_digest(manifest))
        index = state.load_index(self.root)
        for mutation in ('erase', 'repoint'):
            bad = copy.deepcopy(manifest)
            unresolved = bad['records'][0]['unresolved']
            if mutation == 'erase':
                unresolved.pop('issuer_scope')
            else:
                unresolved['issuer_scope'] = {'binding_event_id': other['event_id'], 'issuer_cik': other['issuer']['cik']}
            before = self.snapshot_bytes()
            self.assertFalse(admin.validate_manifest(self.root, bad)['valid'])
            self.assertEqual(self.snapshot_bytes(), before)
            rows = dict(index.snapshot.rows)
            rows[POLICY] += tuple(bad['records'])
            with self.assertRaises(state.OpportunityStateError):
                state._build(dataclasses.replace(index.snapshot, rows=rows))
        # Seal explicitly includes scope even with an identical supplied watermark.
        rows = dict(index.snapshot.rows)
        alternate = copy.deepcopy(manifest['records'][0])
        alternate['unresolved']['issuer_scope'] = {'binding_event_id': other['event_id'], 'issuer_cik': other['issuer']['cik']}
        rows[POLICY] = rows[POLICY][:-1] + (alternate,)
        changed = state._build(dataclasses.replace(index.snapshot, rows=rows))
        self.assertNotEqual(index.state_digest, changed.state_digest)

    def test_scope_cannot_contradict_existing_canonical_dossier_issuer(self):
        import opportunity_admin as admin
        import opportunity_state as state
        from opportunity_identity import _load_binding
        _, manifest = self.scoped_history()
        other = self.other_issuer_payload()
        self.write(POLICY, [fixtures.policy_row('identity_resolution', resolution=other)])
        resolution = _load_binding(other)
        self.write(CANDIDATES, [fixtures.candidate_link(
            DOSSIER_B, resolution.event_id, state.allowance_identifier(resolution.event_id, 0))])
        before = self.snapshot_bytes()
        self.assertFalse(admin.validate_manifest(self.root, manifest)['valid'])
        with self.assertRaises(admin.OpportunityAdminError):
            admin.import_manifest(self.root, manifest, approved_manifest_sha256=admin.canonical_manifest_digest(manifest))
        self.assertEqual(self.snapshot_bytes(), before)

    def test_model_only_scope_and_unrepresented_review_never_supply_coverage(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        (self.root / 'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
        self.write(REVIEWS, [fixtures.review_row(DOSSIER_B, 'missing-history', [{'decision': 'HOLD'}])])
        # Model-shaped scope has no canonical identity-resolution authority.
        self.write(CANDIDATES, [{'symbol': 'ACME', 'issuer_scope': {
            'binding_event_id': resolution.event_id, 'issuer_cik': resolution.issuer.cik}}])
        before = self.snapshot_bytes()
        audit = admin.audit_history(self.root)
        self.assertEqual(audit['incomplete_history_cases'], [DOSSIER_B])
        manifest = {'manifest_version': 1, 'records': [], 'activation': {'policy_version': 1}}
        self.assertFalse(admin.validate_manifest(self.root, manifest)['valid'])
        with self.assertRaises(state.OpportunityStateError):
            state.candidate_policy(state.load_policy_context(self.root),
                                   fixtures.synthetic_resolution(period='2026-Q2'), symbol='ACME')
        self.assertEqual(self.snapshot_bytes(), before)

    def test_scope_index_defensively_copies_reviewed_metadata(self):
        import opportunity_admin as admin
        import opportunity_state as state
        _, manifest = self.scoped_history()
        admin.import_manifest(self.root, manifest, approved_manifest_sha256=admin.canonical_manifest_digest(manifest))
        index = state.load_index(self.root)
        with self.assertRaises(TypeError):
            index.unresolved_issuer_scopes[DOSSIER_B]['issuer_cik'] = '0001888888'
        with self.assertRaises(TypeError):
            index.unresolved_issuer_scopes[DOSSIER_A] = {}

    # --- Step 1 core: model text never satisfies an approved condition. ---

    def test_model_json_cannot_satisfy_approved_condition(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        self.approved_condition(resolution)
        self.assertFalse(admin.evaluate_condition(
            self.approved_condition(resolution),
            {"metric": "completed_close_usd", "value": "1", "approved": True},
            now=self.now))

    def test_evaluate_condition_rejects_unsealed_and_raw_observations(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        condition = self.approved_condition(resolution)
        raw = state.ConditionObservation(
            event_id=resolution.event_id, metric='completed_close_usd',
            value=Decimal('52.5'), units='USD',
            source_kind='massive_consolidated_completed_daily',
            observed_at=dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.timezone.utc),
            evidence_ref=CAPTURE_REF, seal=None)
        self.assertFalse(admin.evaluate_condition(condition, raw, now=self.now))
        sealed = admin.observe_completed_close(
            self.adapter_result(), event_id=resolution.event_id,
            evidence_ref=CAPTURE_REF)
        self.assertTrue(admin.evaluate_condition(condition, sealed, now=self.now))
        forged = state.ConditionObservation(**{
            **{f: getattr(sealed, f) for f in (
                'event_id', 'metric', 'value', 'units', 'source_kind',
                'observed_at', 'evidence_ref')},
            'value': Decimal('1'), 'seal': sealed.seal})
        self.assertFalse(admin.evaluate_condition(condition, forged, now=self.now))

    def test_unsupported_condition_parameters_fail_closed(self):
        import opportunity_admin as admin
        self.build_history()
        base = dict(condition_id='cond-x', event_id='oe1:' + '1' * 64,
                    allowance_id='oa1:' + '2' * 64, metric='completed_close_usd',
                    operator='>=', threshold='50', units='USD',
                    source_kind='massive_consolidated_completed_daily',
                    expires_at=FAR_FUTURE, observation_max_age_seconds=86400,
                    baseline_ref='baseline-1')
        for overrides in ({'metric': 'price_movement'}, {'units': 'EUR'},
                          {'source_kind': 'model_guess'}, {'operator': '~'},
                          {'threshold': '0'}, {'threshold': '-5'},
                          {'threshold': 'NaN'}, {'observation_max_age_seconds': -1}):
            with self.subTest(overrides=overrides):
                with self.assertRaises(ValueError):
                    admin.Condition(**{**base, **overrides})
        admin.Condition(**base)  # Supported parameters construct cleanly.

    def test_observation_factory_only_trusts_synchronized_adapter_results(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        observation = self.observation(resolution)
        self.assertEqual(observation.observed_at,
                         dt.datetime(2026, 11, 4, 12, 0, tzinfo=dt.timezone.utc))
        for bad in ({'metric': 'other'}, {'units': 'EUR'},
                    {'source': 'candidate_price'}, {'value': 'NaN'},
                    {'value': '-1'}, {'value': '0'}, {'market_prices_at': None},
                    {'market_prices_at': '2026-11-04T25:00:00+00:00'}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):
                    admin.observe_completed_close(
                        self.adapter_result(**bad), event_id=resolution.event_id,
                        evidence_ref=CAPTURE_REF)
        with self.assertRaises(ValueError):
            admin.observe_completed_close(self.adapter_result(),
                                          event_id='',
                                          evidence_ref=CAPTURE_REF)

    def test_stale_wrong_unit_wrong_event_future_and_expired_denied(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        condition = self.approved_condition(resolution)
        sealed = self.observation(resolution)
        self.assertTrue(admin.evaluate_condition(condition, sealed, now=self.now))
        # Expiry equality is still within validity; one second later is expired.
        edge = admin.Condition(
            'cond-edge', resolution.event_id,
            self.condition_record(resolution)['allowance_id'],
            'completed_close_usd', '>=', '50', 'USD',
            'massive_consolidated_completed_daily',
            '2026-11-04T13:00:00+00:00', 86400, 'baseline-1')
        self.assertTrue(admin.evaluate_condition(edge, sealed, now=self.now))
        self.assertFalse(admin.evaluate_condition(
            edge, sealed, now=self.now + dt.timedelta(seconds=1)))
        self.assertFalse(admin.evaluate_condition(
            condition, sealed, now=self.now + dt.timedelta(seconds=86401)))
        future = self.observation(
            resolution, market_prices_at='2026-11-04T13:00:01+00:00')
        self.assertFalse(admin.evaluate_condition(condition, future, now=self.now))
        other = admin.Condition(
            'cond-other', 'oe1:' + '8' * 64,
            self.condition_record(resolution)['allowance_id'],
            'completed_close_usd', '>=', '50', 'USD',
            'massive_consolidated_completed_daily', FAR_FUTURE, 86400, 'baseline-1')
        self.assertFalse(admin.evaluate_condition(other, sealed, now=self.now))
        below = self.observation(resolution, value='49.9')
        self.assertFalse(admin.evaluate_condition(condition, below, now=self.now))

    # --- Manifest validate/import. ---

    def test_exact_reviewed_manifest_imports_once_idempotently(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        manifest = self.manifest(resolution)
        report = admin.validate_manifest(self.root, manifest)
        self.assertTrue(report['valid'], report)
        digest = admin.canonical_manifest_digest(manifest)
        result = admin.import_manifest(self.root, manifest,
                                       approved_manifest_sha256=digest)
        self.assertEqual(result['appended'], 2)
        again = admin.import_manifest(self.root, manifest,
                                      approved_manifest_sha256=digest)
        self.assertEqual(again['appended'], 0)
        rows = storage.read_jsonl_stream_readonly(self.root / POLICY)
        self.assertEqual(len(rows), 4)  # activation, resolution, alias, condition
        self.assertEqual(sum(1 for r in rows if r.get('alias') == 'alias-a'), 1)

    def test_changed_source_digest_sequence_or_alias_fails(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        rows = storage.read_jsonl_stream_readonly(self.root / POLICY)
        identity_row = rows[1]
        good = {'record_type': 'identity_resolution', 'schema_version': 1,
                'timestamp': '2026-11-04T12:00:00+00:00',
                'resolution': fixtures.synthetic_resolution_payload(),
                'source': {'stream': POLICY, 'sequence': 2,
                           'row_sha256': hashlib.sha256(canonical_bytes(identity_row)).hexdigest()}}
        self.assertTrue(admin.validate_manifest(
            self.root, {'manifest_version': 1, 'records': [good]})['valid'])
        changed = dict(good, source={'stream': POLICY, 'sequence': 2,
                                     'row_sha256': 'd' * 64})
        self.assertFalse(admin.validate_manifest(
            self.root, {'manifest_version': 1, 'records': [changed]})['valid'])
        wrong_sequence = dict(good, source={'stream': POLICY, 'sequence': 1,
                                            'row_sha256': 'd' * 64})
        self.assertFalse(admin.validate_manifest(
            self.root, {'manifest_version': 1, 'records': [wrong_sequence]})['valid'])
        digest = admin.canonical_manifest_digest(
            {'manifest_version': 1, 'records': [changed]})
        with self.assertRaises(admin.OpportunityAdminError):
            admin.import_manifest(self.root, {'manifest_version': 1,
                                              'records': [changed]},
                                  approved_manifest_sha256=digest)
        self.assertEqual(len(storage.read_jsonl_stream_readonly(self.root / POLICY)), 2)

    def test_unsupported_manifest_version_and_missing_approval_fail(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        manifest = self.manifest(resolution, manifest_version=2)
        self.assertFalse(admin.validate_manifest(self.root, manifest)['valid'])
        digest = admin.canonical_manifest_digest(manifest)
        with self.assertRaises(admin.OpportunityAdminError):
            admin.import_manifest(self.root, manifest, approved_manifest_sha256=digest)
        changed = self.manifest(resolution)
        with self.assertRaises(admin.OpportunityAdminError):
            admin.import_manifest(self.root, changed,
                                  approved_manifest_sha256=digest)
        empty = self.manifest(resolution, records=[])
        self.assertTrue(admin.validate_manifest(self.root, empty)['valid'])
        result = admin.import_manifest(self.root, empty,
                                       approved_manifest_sha256=admin.canonical_manifest_digest(empty))
        self.assertEqual(result['appended'], 0)

    def test_hidden_resets_are_rejected(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        digest = admin.canonical_manifest_digest(self.manifest(resolution))
        admin.import_manifest(self.root, self.manifest(resolution),
                              approved_manifest_sha256=digest)
        # Re-pointing an alias at another event is a hidden reset.
        other = fixtures.synthetic_resolution(period='2026-Q1')
        conflicting = {'manifest_version': 1, 'records': [
            {'record_type': 'document_alias', 'schema_version': 1,
             'timestamp': '2026-11-04T12:00:00+00:00', 'alias': 'alias-a',
             'event_id': other.event_id}]}
        self.assertFalse(admin.validate_manifest(self.root, conflicting)['valid'])
        # Reopening grants and activations never arrive through a manifest.
        for record_type in ('reopen_grant', 'activation'):
            smuggled = {'manifest_version': 1, 'records': [
                {'record_type': record_type, 'schema_version': 1,
                 'timestamp': '2026-11-04T12:00:00+00:00'}]}
            report = admin.validate_manifest(self.root, smuggled)
            self.assertFalse(report['valid'], record_type)

    def test_validate_import_and_audit_never_write(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        before = self.snapshot_bytes()
        manifest = self.manifest(resolution)
        admin.validate_manifest(self.root, manifest)
        admin.audit_history(self.root)
        self.assertEqual(self.snapshot_bytes(), before)
        with self.assertRaises(admin.OpportunityAdminError):
            admin.import_manifest(self.root, manifest,
                                  approved_manifest_sha256='f' * 64)
        self.assertEqual(self.snapshot_bytes(), before)

    def test_audit_reports_bindings_watermarks_and_unresolved_separately(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        self.write(POLICY, [
            fixtures.policy_row('identity_resolution',
                                unresolved={'dossier_hash': DOSSIER_B,
                                            'status': 'unknown', 'reason': 'no_history'}),
        ])
        report = admin.audit_history(self.root)
        self.assertEqual(report['policy_version'], 1)
        self.assertIn(resolution.event_id, report['proposed_bindings'])
        self.assertEqual(report['unresolved_cases'], [DOSSIER_B])
        self.assertTrue(report['base_watermark'])

    # --- Activation. ---

    def test_activation_idempotent_and_preserves_earliest_dissent(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        manifest = self.manifest(resolution, activation={'policy_version': 2})
        digest = admin.canonical_manifest_digest(manifest)
        first = admin.activate(self.root, manifest, approved_manifest_sha256=digest)
        self.assertTrue(first['appended_activation'])
        second = admin.activate(self.root, manifest, approved_manifest_sha256=digest)
        self.assertFalse(second['appended_activation'])
        rows = storage.read_jsonl_stream_readonly(self.root / POLICY)
        self.assertEqual(sum(1 for r in rows if r['record_type'] == 'activation'), 2)
        index = state.load_index(self.root)
        self.assertEqual(index.activated_version, 2)
        # Earliest dissent: the HOLD review still spends despite later approval.
        self.write(REVIEWS, [
            fixtures.review_row(DOSSIER_A, EVIDENCE_1,
                                [{'decision': 'APPROVE'}, {'decision': 'APPROVE'}],
                                proposal_hash='p' * 64),
        ])
        index = state.load_index(self.root)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B)
        self.assertEqual((result.outcome, result.reason), ('skip', 'unchanged_opportunity'))

    # --- Reopening claims. ---

    def test_satisfied_condition_yields_pending_reopening_research_only(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        self.write(POLICY, [
            fixtures.policy_row('condition_approval', condition_id='cond-1',
                                event_id=resolution.event_id,
                                condition=self.condition_record(resolution)),
        ])
        observation = self.observation(resolution)
        index = state.load_index(self.root)
        claim = admin.make_reopening_claim(index, resolution, observation,
                                           now=self.now)
        self.assertIsNotNone(claim)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B,
                                      reopening_claim=claim)
        self.assertEqual(result.outcome, 'reopening_pending')
        # Research-only: it cannot authorize paid reviews before commit.
        self.assertNotEqual(result.outcome, 'eligible')
        unsatisfied = self.observation(resolution, value='10')
        self.assertIsNone(admin.make_reopening_claim(
            index, resolution, unsatisfied, now=self.now))
        self.assertIsNone(admin.make_reopening_claim(
            index, resolution,
            state.ConditionObservation(**{**{f: getattr(observation, f) for f in (
                'event_id', 'metric', 'value', 'units', 'source_kind',
                'observed_at', 'evidence_ref')}, 'seal': None}),
            now=self.now))

    def test_claim_survives_trusted_persistence_and_restores_once(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        self.assertIsNotNone(claim)
        admin.record_reopening_claim(self.root, claim)
        index = state.load_index(self.root)
        restored = admin.restore_reopening_claim(index, DOSSIER_A, now=self.now)
        self.assertEqual(admin.serialize_reopening_claim(restored),
                         admin.serialize_reopening_claim(claim))
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_A,
                                      reopening_claim=restored)
        self.assertEqual(result.outcome, 'reopening_pending')

    def test_commit_revalidates_under_lock_and_grants_one_shot_allowance(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        admin.record_reopening_claim(self.root, claim)
        first = admin.commit_reopening_claim(self.root, claim,
                                             dossier_hash=DOSSIER_A, now=self.now)
        expected = state.allowance_identifier(resolution.event_id, 1)
        self.assertEqual(first, expected)
        rows = storage.read_jsonl_stream_readonly(self.root / POLICY)
        grants = [r for r in rows if r.get('record_type') == 'reopen_grant']
        self.assertEqual(len(grants), 1)
        # Replay of the same durable claim returns the same durable allowance.
        replay = admin.commit_reopening_claim(self.root, claim,
                                              dossier_hash=DOSSIER_A, now=self.now)
        self.assertEqual(replay, expected)
        rows = storage.read_jsonl_stream_readonly(self.root / POLICY)
        self.assertEqual(
            len([r for r in rows if r.get('record_type') == 'reopen_grant']), 1)
        # The condition is consumed: no further claim from it, no replay grant.
        index = state.load_index(self.root)
        self.assertIsNone(admin.make_reopening_claim(
            index, resolution, self.observation(resolution), now=self.now))
        with self.assertRaises(admin.OpportunityAdminError):
            admin.restore_reopening_claim(index, DOSSIER_A, now=self.now)
        # Commit advances policy but deliberately does not rebind the old dossier.
        old = state.event_decision(index, resolution, dossier_hash=DOSSIER_A)
        self.assertEqual((old.outcome, old.reason), ('unknown', 'dossier_binding_missing'))
        fresh = state.event_decision(index, resolution)
        self.assertEqual((fresh.outcome, fresh.reason, fresh.allowance_id),
                         ('eligible', 'allowance_available', expected))
        # A genuinely new current-bound dossier can spend the grant; replay of
        # the old claim must not refill it, even after the new HOLD.
        self.write(CANDIDATES, [fixtures.candidate_link(
            DOSSIER_B, resolution.event_id, expected)])
        self.write(REVIEWS, [fixtures.review_row(
            DOSSIER_B, 'evidence-2', [{'decision': 'HOLD'}])])
        self.assertEqual(admin.commit_reopening_claim(
            self.root, claim, dossier_hash=DOSSIER_A, now=self.now), expected)
        current = state.load_index(self.root)
        self.assertEqual(len(current.grants), 1)
        spent = state.event_decision(current, resolution, dossier_hash=DOSSIER_B)
        self.assertEqual((spent.outcome, spent.reason, spent.allowance_id),
                         ('skip', 'unchanged_opportunity', expected))
        with self.assertRaises(admin.OpportunityAdminError):
            admin.commit_reopening_claim(self.root, claim,
                                         dossier_hash=DOSSIER_B, now=self.now)

    def test_commit_refuses_unspent_or_unbacked_claims(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history(decision='APPROVE')  # lone APPROVE spends? no dual pair
        # lone-APPROVE rows spend fail-closed: the event is spent by this review.
        self.write(POLICY, [
            fixtures.policy_row('condition_approval', condition_id='cond-1',
                                event_id=resolution.event_id,
                                condition=self.condition_record(resolution)),
        ])
        observation = self.observation(resolution)
        index = state.load_index(self.root)
        claim = admin.make_reopening_claim(index, resolution, observation, now=self.now)
        self.assertIsNotNone(claim)
        # Never recorded durably: commit must fail closed.
        with self.assertRaises(admin.OpportunityAdminError):
            admin.commit_reopening_claim(self.root, claim,
                                         dossier_hash=DOSSIER_A, now=self.now)
        self.assertEqual(
            len([r for r in storage.read_jsonl_stream_readonly(self.root / POLICY)
                 if r.get('record_type') == 'reopen_grant']), 0)

    def test_altered_lineage_and_forged_serialization_fail_closed(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        admin.record_reopening_claim(self.root, claim)
        serialized = admin.serialize_reopening_claim(claim)
        tampered = dict(serialized, observation=dict(
            serialized['observation'], value='999'))
        (self.root / CLAIMS).write_text(
            json.dumps(tampered, sort_keys=True, separators=(',', ':')) + '\n',
            encoding='utf-8')
        index = state.load_index(self.root)
        with self.assertRaises(admin.OpportunityAdminError):
            admin.restore_reopening_claim(index, DOSSIER_A, now=self.now)
        # A fabricated seal on a rebuilt observation never passes evaluation.
        forged = state.ConditionObservation(**{
            **{f: getattr(claim.observation, f) for f in (
                'event_id', 'metric', 'value', 'units', 'source_kind',
                'observed_at', 'evidence_ref')},
            'value': Decimal('999'), 'seal': claim.observation.seal})
        self.assertFalse(admin.evaluate_condition(
            self.approved_condition(resolution), forged, now=self.now))

    def test_explicit_grant_requires_approval_digest_and_consumes_once(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        observation = self.observation(resolution)
        admin.record_observation_evidence(self.root, observation)
        approval = {'approval_version': 1, 'kind': 'explicit_reopening',
                    'event_id': resolution.event_id,
                    'prior_allowance_id': state.allowance_identifier(
                        resolution.event_id, 0),
                    'reason': 'explicit evidence-backed reopening',
                    'changed_fact': 'corrected completed close',
                    'observation_sha256': admin.observation_digest(observation)}
        digest = admin.canonical_manifest_digest(approval)
        allowance = admin.grant_reopening(self.root, approval,
                                          approved_manifest_sha256=digest)
        self.assertEqual(allowance,
                         state.allowance_identifier(resolution.event_id, 1))
        # The real administrator grant makes only the new allowance usable.
        before_candidates = storage.read_jsonl_stream_readonly(self.root / CANDIDATES)
        before_reviews = storage.read_jsonl_stream_readonly(self.root / REVIEWS)
        old = state.event_decision(state.load_index(self.root), resolution,
                                   dossier_hash=DOSSIER_A)
        self.assertEqual((old.outcome, old.reason), ('unknown', 'dossier_binding_missing'))
        self.write(CANDIDATES, [fixtures.candidate_link(
            DOSSIER_B, resolution.event_id, allowance)])
        index = state.load_index(self.root)
        for dossier in (None, DOSSIER_B):
            with self.subTest(dossier=dossier):
                result = state.event_decision(index, resolution, dossier_hash=dossier)
                self.assertEqual((result.outcome, result.reason, result.allowance_id),
                                 ('eligible', 'allowance_available', allowance))
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root / CANDIDATES)[:-1],
                         before_candidates)
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root / REVIEWS), before_reviews)
        # Idempotent re-grant returns the same durable allowance, no new row.
        again = admin.grant_reopening(self.root, approval,
                                      approved_manifest_sha256=digest)
        self.assertEqual(again, allowance)
        rows = storage.read_jsonl_stream_readonly(self.root / POLICY)
        self.assertEqual(
            len([r for r in rows if r.get('record_type') == 'reopen_grant']), 1)
        # Wrong digest (e.g. inferred from source/model text) fails closed.
        with self.assertRaises(admin.OpportunityAdminError):
            admin.grant_reopening(self.root, approval,
                                  approved_manifest_sha256='0' * 64)
        # A model approved=true field is not an approval.
        forged = dict(approval, approved=True)
        with self.assertRaises(admin.OpportunityAdminError):
            admin.grant_reopening(
                self.root, forged,
                approved_manifest_sha256=admin.canonical_manifest_digest(forged))

    def test_source_change_without_grant_remains_spent(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        # New alias/document for the same event, imported without any grant.
        manifest = self.manifest(resolution)
        digest = admin.canonical_manifest_digest(manifest)
        admin.import_manifest(self.root, manifest, approved_manifest_sha256=digest)
        index = state.load_index(self.root)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_B)
        self.assertEqual((result.outcome, result.reason),
                         ('skip', 'unchanged_opportunity'))

    def test_serialization_fields_grant_no_authority(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        serialized = admin.serialize_reopening_claim(claim)
        rebuilt = state.ReopeningClaim(
            condition_id=serialized['condition_id'],
            prior_allowance_id=serialized['prior_allowance_id'],
            observation=state.ConditionObservation(
                event_id=serialized['event_id'],
                metric=serialized['observation']['metric'],
                value=Decimal(serialized['observation']['value']),
                units=serialized['observation']['units'],
                source_kind=serialized['observation']['source_kind'],
                observed_at=dt.datetime.fromisoformat(
                    serialized['observation']['observed_at']),
                evidence_ref=serialized['observation']['evidence_ref'],
                seal=None),
            seal=serialized.get('claim_sha256'))
        index = state.load_index(self.root)
        result = state.event_decision(index, resolution, dossier_hash=DOSSIER_A,
                                      reopening_claim=rebuilt)
        self.assertEqual(result.outcome, 'skip')

    # --- CLI boundary. ---

    def write_manifest_file(self, manifest, *, canonical=True):
        path = self.root / 'outside' / 'manifest.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_bytes(manifest) if canonical else (
            canonical_bytes(manifest) + b'\n')
        path.write_bytes(payload)
        os.chmod(path, 0o600)
        return path

    def test_cli_audit_validate_readonly_and_out_artifact_0600(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        before = self.snapshot_bytes()
        external = tempfile.TemporaryDirectory()
        self.addCleanup(external.cleanup)
        out = Path(external.name) / 'audit.json'
        manifest = self.manifest(resolution)
        path = self.write_manifest_file(manifest)
        before = self.snapshot_bytes()
        self.assertEqual(admin.main(['audit', str(self.root), '--out', str(out)]), 0)
        self.assertEqual(out.stat().st_mode & 0o777, 0o600)
        parsed = json.loads(out.read_text(encoding='utf-8'))
        self.assertIn(resolution.event_id, parsed['proposed_bindings'])
        self.assertEqual(out.read_bytes(), canonical_bytes(parsed))
        self.assertEqual(admin.main(['validate', str(self.root),
                                     '--manifest', str(path)]), 0)
        self.assertEqual(self.snapshot_bytes(), before)

    def test_cli_mutations_require_explicit_flags_and_apply(self):
        import opportunity_admin as admin
        resolution = self.build_history()
        manifest = self.manifest(resolution)
        digest = admin.canonical_manifest_digest(manifest)
        path = self.write_manifest_file(manifest)
        # Missing --apply: explicit refusal, zero writes.
        self.assertNotEqual(admin.main(['import', str(self.root), '--manifest',
                                        str(path), '--approved-sha256', digest]), 0)
        self.assertEqual(len(storage.read_jsonl_stream_readonly(self.root / POLICY)), 2)
        self.assertEqual(admin.main(['import', str(self.root), '--manifest', str(path),
                                     '--approved-sha256', digest, '--apply']), 0)
        self.assertEqual(len(storage.read_jsonl_stream_readonly(self.root / POLICY)), 4)
        # Wrong digest refused.
        self.assertNotEqual(admin.main(['import', str(self.root), '--manifest',
                                        str(path), '--approved-sha256', 'e' * 64,
                                        '--apply']), 0)
        # Non-canonical artifact bytes refused even when content parses equal.
        loose = self.write_manifest_file(manifest, canonical=False)
        self.assertNotEqual(admin.main(['import', str(self.root), '--manifest',
                                        str(loose), '--approved-sha256', digest,
                                        '--apply']), 0)
        # Activation through the CLI.
        activated = self.manifest(resolution, activation={'policy_version': 2})
        activate_path = self.write_manifest_file(activated)
        self.assertEqual(admin.main(
            ['activate', str(self.root), '--manifest', str(activate_path),
             '--approved-sha256', admin.canonical_manifest_digest(activated),
             '--apply']), 0)

    def test_cli_reopen_requires_approval_digest_and_apply(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        observation = self.observation(resolution)
        admin.record_observation_evidence(self.root, observation)
        approval = {'approval_version': 1, 'kind': 'explicit_reopening',
                    'event_id': resolution.event_id,
                    'prior_allowance_id': state.allowance_identifier(
                        resolution.event_id, 0),
                    'reason': 'explicit evidence-backed reopening',
                    'changed_fact': 'corrected completed close',
                    'observation_sha256': admin.observation_digest(observation)}
        digest = admin.canonical_manifest_digest(approval)
        path = self.write_manifest_file(approval)
        self.assertNotEqual(admin.main(['reopen', str(self.root), '--manifest',
                                        str(path), '--approved-sha256', digest]), 0)
        self.assertEqual(len(storage.read_jsonl_stream_readonly(self.root / POLICY)), 2)
        self.assertEqual(admin.main(['reopen', str(self.root), '--manifest', str(path),
                                     '--approved-sha256', digest, '--apply']), 0)
        index = state.load_index(self.root)
        self.assertEqual(admin.audit_history(self.root)['policy_version'], 1)
        self.assertIn(state.allowance_identifier(resolution.event_id, 1),
                      index.allowance_events)

    def test_lost_append_ack_resume_and_replay(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        # Lost append acknowledgement: the record is durable, the caller replays.
        admin.record_reopening_claim(self.root, claim)
        admin.record_reopening_claim(self.root, claim)
        self.assertEqual(
            len(storage.read_jsonl_stream_readonly(self.root / CLAIMS)), 1)
        index = state.load_index(self.root)
        restored = admin.restore_reopening_claim(index, DOSSIER_A, now=self.now)
        self.assertEqual(restored.condition_id, claim.condition_id)
        # Simulate a real lost acknowledgement *after* the canonical grant
        # append succeeds; recovery must read it back rather than append again.
        from unittest.mock import patch
        append_grant = admin._append_grant

        def append_then_lose_ack(root, record):
            append_grant(root, record)
            raise admin.OpportunityAdminError('synthetic_lost_ack')

        with patch.object(admin, '_append_grant', side_effect=append_then_lose_ack):
            with self.assertRaisesRegex(admin.OpportunityAdminError, 'synthetic_lost_ack'):
                admin.commit_reopening_claim(self.root, restored,
                                             dossier_hash=DOSSIER_A, now=self.now)
        first = admin.commit_reopening_claim(self.root, restored,
                                             dossier_hash=DOSSIER_A, now=self.now)
        second = admin.commit_reopening_claim(self.root, claim,
                                              dossier_hash=DOSSIER_A, now=self.now)
        self.assertEqual(first, second)
        self.assertEqual(
            len([r for r in storage.read_jsonl_stream_readonly(self.root / POLICY)
                 if r.get('record_type') == 'reopen_grant']), 1)

    def test_reopening_does_not_deadlock_or_authorize_precommit(self):
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        admin.record_reopening_claim(self.root, claim)
        index = state.load_index(self.root)
        # Pre-commit: the pending claim cannot authorize reviews for gen 1.
        with self.assertRaises(state.OpportunityStateError):
            state.authorize_current_attempt(
                index, dossier_hash=DOSSIER_A, proposal_hash='p' * 64,
                evidence_id=EVIDENCE_1)
        # Commit revalidates under the entry lock; nested/reentrant calls and
        # replayed commits return without hanging behind their own spent gate.
        allowance = admin.commit_reopening_claim(self.root, claim,
                                                 dossier_hash=DOSSIER_A, now=self.now)
        self.assertEqual(allowance,
                         state.allowance_identifier(resolution.event_id, 1))


    def test_record_claim_and_evidence_append_inside_entry_lock(self):
        """M1: the claims-stream check-then-append executes inside the
        entry_state lock, so concurrent invocations serialize their duplicate
        check against the append (sequential proof: instrumented lock observed
        held across the whole check-then-append window)."""
        import contextlib
        import unittest.mock
        import entry_state
        import opportunity_admin as admin
        import opportunity_state as state
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        observation = self.observation(resolution)
        real_lock = entry_state.lock
        held = []

        @contextlib.contextmanager
        def recording_lock(root):
            with real_lock(root):
                held.append(True)
                try:
                    yield
                finally:
                    held.pop()

        for record_call in (lambda: admin.record_reopening_claim(self.root, claim),
                            lambda: admin.record_observation_evidence(
                                self.root, observation)):
            with unittest.mock.patch.object(entry_state, 'lock', recording_lock):
                original_append = storage.append_jsonl

                def locked_append(path, row, _original=original_append):
                    self.assertTrue(held,
                                    'claims append happened outside the entry lock')
                    return _original(path, row)

                with unittest.mock.patch.object(storage, 'append_jsonl',
                                                locked_append):
                    result = record_call()
            self.assertTrue(result['recorded'])
        # Sequential replay stays idempotent under the same lock discipline.
        self.assertEqual(
            len(storage.read_jsonl_stream_readonly(self.root / CLAIMS)), 2)
        self.assertEqual(admin.record_reopening_claim(self.root, claim)['recorded'],
                         False)
        self.assertEqual(
            len(storage.read_jsonl_stream_readonly(self.root / CLAIMS)), 2)

    def test_replay_with_mismatched_dossier_fails_typed(self):
        """M2: the lost-ack replay fast path enforces the same dossier
        binding the slow path enforces."""
        import opportunity_admin as admin
        resolution = self.build_history()
        claim = self.sealed_claim(resolution)
        admin.record_reopening_claim(self.root, claim)
        first = admin.commit_reopening_claim(self.root, claim,
                                             dossier_hash=DOSSIER_A, now=self.now)
        with self.assertRaises(admin.OpportunityAdminError) as caught:
            admin.commit_reopening_claim(self.root, claim,
                                         dossier_hash=DOSSIER_B, now=self.now)
        self.assertIn('claim_dossier_mismatch', str(caught.exception))
        # The replay refusal neither grants nor removes the durable allowance.
        rows = storage.read_jsonl_stream_readonly(self.root / POLICY)
        grants = [r for r in rows if r.get('record_type') == 'reopen_grant']
        self.assertEqual(len(grants), 1)
        self.assertEqual(grants[0]['allowance_id'], first)
        # The correctly bound replay still returns the same allowance ID.
        self.assertEqual(
            admin.commit_reopening_claim(self.root, claim,
                                         dossier_hash=DOSSIER_A, now=self.now),
            first)


if __name__ == '__main__':
    unittest.main()
