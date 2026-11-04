"""End-to-end opportunity workflow isolation scenarios (synthetic only).

Real Radar-to-review orchestration in caller-owned temporary roots: every
research, review, fill and rollback artifact below is explicitly synthetic
fictional-issuer state. No operational issuer, trade history, broker
endpoint, model call or network access participates. The compatibility-floor
rollback scenario executes a pinned, authenticated floor source copy that is
supplied outside publishable source (TRADEY_OPPORTUNITY_FLOOR_SOURCE); the
copy is digest-authenticated before any replay and never mutates production.
"""
import argparse
import contextlib
import copy
import datetime as dt
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch

import alpha_radar as radar
import autotrader
import opportunity_identity as identity
import opportunity_state as state
import opportunity_fixtures as fixtures
import sqlite_ledger as storage
from support_fixtures import broker_snapshot, policy_config
from retained_article import original_text, retain_article

FLOOR_COMMIT_DIGESTS = {
    # Pinned accepted compatibility floor (SUPPORTED_POLICY_VERSION=0).
    'opportunity_activation.py': '6807664d2c0d2f4cd6f69823507c6008cc3165c09f0313d1376cc2f9b3448eaa',
}

# Synthetic managed-protection scenario rows (fictional symbol/prices only).
_PROTECTION_PLAN = {'action': 'BUY', 'symbol': 'ZS', 'quantity': 3,
                    'stop': 151.24, 'target': 184.37}
_PROTECTION_TARGET = dict(
    client_order_id='replacement', symbol='ZS', side='sell',
    position_intent='sell_to_close', order_class='oco', type='limit', qty='3',
    filled_qty='3', filled_avg_price='184.44',
    filled_at='2026-09-14T14:48:15.061577Z', status='filled',
    limit_price='184.37', time_in_force='gtc')
_PROTECTION_STOP = dict(_PROTECTION_TARGET, client_order_id='stop', type='stop',
                        filled_qty='0', status='canceled', stop_price='151.24')
_PROTECTION_TARGET['legs'] = [_PROTECTION_STOP]
_PROTECTION_PARENT = dict(
    client_order_id='parent', symbol='ZS', side='buy',
    position_intent='buy_to_open', order_class='bracket', qty='3',
    filled_qty='3', filled_avg_price='162.79',
    filled_at='2026-09-08T13:40:00Z', status='filled', legs=[
        dict(_PROTECTION_STOP, client_order_id='old-stop', order_class='bracket'),
        dict(_PROTECTION_TARGET, client_order_id='old-target', order_class='bracket',
             status='expired', filled_qty='0', legs=[])])

_FLOOR_DRIVER = r'''
"""Authenticated floor-subprocess driver; isolated root only, no network."""
import argparse, contextlib, io, json, os, sys
from pathlib import Path
from unittest.mock import patch

floor = os.environ['TRADEY_OPPORTUNITY_FLOOR_SOURCE']
sys.path.insert(0, floor)

# Offline boundary before any application import: every outbound socket
# primitive raises. The floor scenario uses a synthetic in-process broker.
import socket
def _forbidden(*_args, **_kwargs):
    raise AssertionError('floor scenario network forbidden')
for name in ('connect', 'connect_ex', 'sendto', 'sendmsg'):
    setattr(socket.socket, name, _forbidden)
socket.getaddrinfo = _forbidden
socket.gethostbyname = _forbidden

import autotrader as floor_autotrader
import opportunity_activation as floor_activation

stub_path, root = sys.argv[1], Path(sys.argv[2])
stub = json.loads(Path(stub_path).read_text(encoding='utf-8'))

def broker(operation, payload=None):
    if operation in ('reconcile_many', 'reconciliation_snapshot'):
        refs = (payload or {}).get('client_order_ids', [])
        return dict(copy := dict(stub['snapshot']),
                    orders=[stub['orders'][ref] for ref in refs])
    if operation == 'snapshot':
        return dict(stub['snapshot'])
    raise AssertionError('unexpected floor broker operation: ' + operation)

out = io.StringIO()
with patch.object(floor_autotrader, 'ROOT', root), \
        patch.object(floor_autotrader, '_broker_bridge', side_effect=broker), \
        contextlib.redirect_stdout(out):
    code = floor_autotrader.run(argparse.Namespace(dry_run_fixture=False, live_dry_run=False))
print(json.dumps({'code': code, 'output': out.getvalue(),
                  'supported_policy_version': floor_activation.SUPPORTED_POLICY_VERSION}))
'''


class OpportunityWorkflowScenario(unittest.TestCase):
    """Radar-to-review orchestration, rollback floor and injection matrix."""

    def setUp(self):
        for target in ('socket.socket.connect', 'socket.socket.connect_ex',
                       'socket.socket.sendto', 'socket.socket.sendmsg',
                       'socket.getaddrinfo', 'socket.gethostbyname',
                       'socket.gethostbyname_ex', 'socket.gethostbyaddr'):
            self.enterContext(patch(target, side_effect=AssertionError('synthetic network forbidden')))
        self.enterContext(patch('urllib.request.urlopen',
                                side_effect=AssertionError('synthetic test network forbidden')))
        self.stack = self.enterContext(contextlib.ExitStack())
        self.root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixtures.make_root(self.root, active=True)
        (self.root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': []}))
        self.enterContext(patch.object(radar, 'ROOT', self.root))
        self.enterContext(patch.object(autotrader, 'ROOT', self.root))
        cfg = policy_config()
        cfg.update(enabled=True, broker_mode='paper',
                   pending_entry_policy='exact_owned_zero_fill_v1',
                   max_pending_entry_parents=2)
        # Deterministic offline retrieval path; focused retrieval is its own
        # covered feature and would otherwise consult the model CLI.
        cfg['focused_retrieval_enabled'] = False
        (self.root / 'autonomy_config.json').write_text(json.dumps(cfg))
        self.cfg = cfg
        now = dt.datetime.now(dt.timezone.utc)
        self.snapshot = broker_snapshot(
            captured_at=now.isoformat(), quote={'bid': 99.98, 'ask': 100.05,
                                                'timestamp': now.isoformat()},
            cash=10000.0, earnings_status='reported', earnings_sessions_away=None,
            trading_sessions=[(now.date() + dt.timedelta(days=i)).isoformat()
                              for i in range(31)])
        self.snapshot['buying_power_semantics'] = 'available_net'
        self.snapshot['cash_semantics'] = 'gross'
        self.pages = fixtures.earnings_pages()
        first = self.pages[0]
        url = first['url'].replace('1999999', '1888888')
        raw = original_text(first).replace('ACME', 'NEXT').replace('1999999', '1888888')
        second = {k: v for k, v in first.items() if not k.startswith('_')}
        second.update(url=url, returned_url=url)
        self.pages += [retain_article(second, raw)]
        self.resolutions = [
            identity.resolve_event(symbol, [page], known_resolutions=())
            for symbol, page in zip(('ACME', 'NEXT'), self.pages)]
        for resolution in self.resolutions:
            identity.retain_observations(self.root, resolution, self.pages)
            storage.append_jsonl(self.root / state.POLICY_STREAM, fixtures.policy_row(
                'identity_resolution', resolution=identity.candidate_identity(resolution)))
        # The second lead is literally the rewritten report under the NEXT
        # issuer; the first is the original ACME report.
        self.scouts = []
        self.bundles = []
        for symbol, page in zip(('ACME', 'NEXT'), self.pages):
            secondary = {'url': f'https://news.example/{symbol}',
                         'title': 'Synthetic news', 'text': 'Synthetic results ' * 80,
                         'published_at': '2026-11-04T12:00:00Z'}
            self.scouts.append({'symbol': symbol, 'urls': [page['url'], secondary['url']],
                                'event_date': '2026-11-04', 'catalyst': 'synthetic results'})
            self.bundles.append([page, secondary])
        self.synthesized = []
        self.discovery_calls = 0
        self.review_calls = []
        exit_date = now.date()
        sessions = 0
        while sessions < 6:
            exit_date += dt.timedelta(days=1)
            if exit_date.weekday() < 5:
                sessions += 1
        self.exit_at = exit_date.isoformat() + 'T20:00:00Z'
        self.earnings_at = (now + dt.timedelta(days=45)).isoformat()

    # ------------------------------------------------------------------
    # orchestration helpers
    # ------------------------------------------------------------------
    def run_research(self, *, scouts=None, bundles=None, overrides=()):
        """One real Radar CLI cycle with offline synthetic discovery/model
        boundaries; returns (code, output, stored candidate row or None)."""
        scouts = self.scouts if scouts is None else scouts
        bundles = self.bundles if bundles is None else bundles
        before = len(storage.read_jsonl_stream_readonly(self.root / state.CANDIDATES_STREAM))

        def discovery(*_args, **_kwargs):
            self.discovery_calls += 1
            return copy.deepcopy(scouts), {'reason': 'ok'}

        def scout(*_args, **_kwargs):
            candidates, _ = discovery()
            return subprocess.CompletedProcess([], 0, json.dumps({'candidates': candidates}), '')

        def synthesis(_cfg, selected, evidence, _deadline, **_kwargs):
            self.synthesized.append(selected['symbol'])
            return {'symbol': selected['symbol'],
                    'price': 100.05, 'spy_price': 500.0,
                    'instrument_type': 'cash_equity',
                    'catalyst': 'synthetic results',
                    'thesis': 'Synthetic thesis for fixture only.',
                    'setup_type': 'breakout',
                    'planned_exit_at': self.exit_at,
                    'horizon_rationale': 'Synthetic six-session fixture window.',
                    'earnings_event_at': self.earnings_at,
                    'sources': [{'url': page['url'], 'title': page.get('title', 'synthetic'),
                                 'published_at': page.get('published_at')}
                                for page in evidence]}

        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(radar.subprocess, 'run', side_effect=scout))
            stack.enter_context(patch('discovery_pipeline.discover', side_effect=discovery))
            stack.enter_context(patch.object(
                radar, 'scout_parse_result',
                side_effect=lambda *a, **k: (copy.deepcopy(scouts), {'reason': 'ok'})))
            stack.enter_context(patch.object(radar, 'discovery_command', return_value=['synthetic']))
            stack.enter_context(patch.object(radar, 'sec_filing_date_for_url', return_value=None))
            stack.enter_context(patch.object(radar, 'gather_evidence',
                                             return_value=sum(bundles, [])))
            stack.enter_context(patch.object(radar, 'filter_evidence',
                                             side_effect=lambda pages: (pages, [])))
            stack.enter_context(patch.object(
                radar, 'recover_publications', side_effect=lambda c, p, *a, **k: (p, [])))
            stack.enter_context(patch.object(radar, 'synthesize_candidate', side_effect=synthesis))
            stack.enter_context(patch.object(radar, 'source_verification_result',
                                             return_value={'passed': True}))
            for module, name, options in overrides:
                stack.enter_context(patch.object(module, name, **options))
            output = io.StringIO()
            stack.enter_context(patch('sys.stdout', output))
            code = radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
            rows = storage.read_jsonl_stream_readonly(self.root / state.CANDIDATES_STREAM)
            stored = rows[-1] if len(rows) > before else None
            return code, output.getvalue(), stored

    def radar_cli(self):
        output = io.StringIO()
        with patch.object(radar, 'reusable_fresh_candidate',
                          wraps=radar.reusable_fresh_candidate) as reuse, \
                patch('sys.stdout', output):
            code = radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        return code, output.getvalue(), reuse

    def run_entry(self, *, symbol, positions=None, reviewer=None):
        snapshot = copy.deepcopy(self.snapshot)
        snapshot['asset'] = dict(snapshot['asset'], symbol=symbol)
        if positions is not None:
            snapshot['positions'] = copy.deepcopy(positions)
        # Activated policy: broker truth is carried as one bounded v1
        # entry observation over this synthetic acquisition window.
        import entry_eligibility
        now = dt.datetime.now(dt.timezone.utc)
        snapshot['entry_observation'] = entry_eligibility.entry_observation(
            started_at=now, finished_at=now, duration_seconds=0.0,
            positions=snapshot['positions'], open_orders=snapshot['open_orders'])

        def broker(operation, _payload=None):
            if operation in ('reconcile_many', 'reconciliation_snapshot'):
                return dict(copy.deepcopy(snapshot), orders=[])
            if operation == 'snapshot':
                return copy.deepcopy(snapshot)
            raise AssertionError('unexpected broker operation: ' + operation)

        def reviews(bundle, _cfg):
            proposal = bundle['proposal']
            self.review_calls.append(copy.deepcopy(proposal))
            if reviewer is not None:
                return reviewer(bundle, _cfg)
            return [{'proposal_hash': proposal['proposal_hash'], 'decision': 'HOLD',
                     'fatal_flags': [], 'reason_codes': ['synthetic_hold']}
                    for _ in range(2)]

        output = io.StringIO()
        with patch.object(autotrader, '_broker_bridge', side_effect=broker), \
                patch.object(autotrader, 'independent_reviews', side_effect=reviews), \
                contextlib.redirect_stdout(output):
            code = autotrader.run(argparse.Namespace(dry_run_fixture=False, live_dry_run=False))
        return code, output.getvalue()

    def review_rows(self):
        path = self.root / state.REVIEWS_STREAM
        if not path.exists():
            return []
        return storage.read_jsonl(path)

    def candidates(self):
        return storage.read_jsonl_stream_readonly(self.root / state.CANDIDATES_STREAM)

    def research_and_review(self, symbol, scouts=None, bundles=None, positions=None):
        """One full Radar-to-review cycle; returns (code, output, stored row)."""
        radar_code, radar_output, stored = self.run_research(scouts=scouts,
                                                             bundles=bundles)
        self.assertEqual((radar_code, radar_output),
                         (0, f'DECISION candidate_qualified {symbol}\n'), radar_output)
        self.assertEqual(stored['symbol'], symbol)
        entry_code, entry_output = self.run_entry(symbol=symbol, positions=positions)
        return radar_code, radar_output, stored, entry_code, entry_output

    # ------------------------------------------------------------------
    # end-to-end workflow
    # ------------------------------------------------------------------
    def test_repeated_report_spends_once_then_rewritten_candidate_advances(self):
        # Phase A: the first (original) report reaches reviewers and its HOLD
        # review durably spends the allowance.
        self.assertIsNone(radar.reusable_fresh_candidate(
            self.root / state.CANDIDATES_STREAM, self.root / state.REVIEWS_STREAM))
        radar_code, radar_output, stored, entry_code, entry_output = \
            self.research_and_review('ACME')
        self.assertEqual((radar_code, radar_output),
                         (0, 'DECISION candidate_qualified ACME\n'), radar_output)
        self.assertEqual(entry_code, 2, entry_output)
        self.assertIn('BLOCKER', entry_output)
        self.assertEqual(self.synthesized, ['ACME'])
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual(stored['event_id'], self.resolutions[0].event_id)
        self.assertEqual(stored['allowance_id'],
                         state.allowance_identifier(self.resolutions[0].event_id, 0))
        rows = self.review_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['dossier_hash'], stored['dossier_hash'])
        self.assertEqual(len(self.review_calls), 1)

        # Phase B: the repeated report cannot resurrect the spent event; the
        # reuse fast path and the research fallback both decline, with no new
        # synthesis and no extra discovery spend.
        self.synthesized.clear()
        self.discovery_calls = 0
        self.assertIsNone(radar.reusable_fresh_candidate(
            self.root / state.CANDIDATES_STREAM, self.root / state.REVIEWS_STREAM))
        code, output, none_stored = self.run_research(scouts=self.scouts[:1],
                                                      bundles=self.bundles[:1])
        self.assertEqual((code, output),
                         (0, 'DECISION skipped no_new_eligible_opportunity\n'))
        self.assertIsNone(none_stored)
        self.assertEqual(self.synthesized, [])
        self.assertEqual(self.discovery_calls, 1)
        self.assertEqual(len(self.candidates()), 1)
        self.assertEqual(len(self.review_rows()), 1)

        # Phase C: the rewritten-report candidate (NEXT issuer) advances to
        # unchanged normal gates and reaches reviewers exactly once.
        self.synthesized.clear()
        self.discovery_calls = 0
        _rc, _ro, stored_next, entry_code, entry_output = self.research_and_review('NEXT')
        self.assertEqual(entry_code, 2, entry_output)
        self.assertIn('BLOCKER', entry_output)
        self.assertEqual(self.synthesized, ['NEXT'])
        self.assertEqual(self.discovery_calls, 1)
        self.assertEqual(stored_next['event_id'], self.resolutions[1].event_id)
        stored = self.candidates()
        self.assertEqual(len(stored), 2)
        self.assertEqual(len(self.review_rows()), 2)
        self.assertEqual(len(self.review_calls), 2)

    def test_new_supported_event_reaches_unchanged_gates_after_other_spend(self):
        # Spend ACME, then introduce a genuinely new supported event (a fresh
        # fictional quarterly report) that must traverse the same unchanged
        # gates and reach reviewers.
        self.research_and_review('ACME')
        self.assertEqual(len(self.review_rows()), 1)
        new_pages = fixtures.earnings_pages(period='2026-Q2')
        page = new_pages[0]
        url = page['url'].replace('000001', '000007')
        new_page = retain_article(
            {**{k: v for k, v in page.items() if not k.startswith('_')},
             'url': url, 'returned_url': url}, original_text(page))
        resolution = identity.resolve_event('ACME', [new_page], known_resolutions=())
        self.assertNotEqual(resolution.event_id, self.resolutions[0].event_id)
        secondary = {'url': 'https://news.example/acme-q2', 'title': 'Synthetic news',
                     'text': 'Synthetic results ' * 80, 'published_at': '2026-11-04T12:00:00Z'}
        scout = {'symbol': 'ACME', 'urls': [new_page['url'], secondary['url']],
                 'event_date': '2026-11-04', 'catalyst': 'synthetic results'}
        self.synthesized.clear()
        self.discovery_calls = 0
        _rc, _ro, stored_new, entry_code, entry_output = self.research_and_review(
            'ACME', scouts=[scout], bundles=[[new_page, secondary]])
        self.assertEqual(entry_code, 2, entry_output)
        self.assertIn('BLOCKER', entry_output)
        self.assertEqual(self.synthesized, ['ACME'])
        self.assertEqual(stored_new['event_id'], resolution.event_id)
        stored = self.candidates()
        self.assertEqual(len(stored), 2)
        self.assertEqual(stored[-1]['event_id'], resolution.event_id)
        rows = self.review_rows()
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[-1]['dossier_hash'], stored[-1]['dossier_hash'])

    def test_after_fill_no_add_on_reaches_reviewers(self):
        # A filled position is broker truth: the next candidate for the same
        # symbol is blocked before sizing and no add-on review is purchased.
        self.research_and_review('ACME')
        first_stored = self.candidates()[0]
        reviews_before = len(self.review_calls)
        storage.append_jsonl(self.root / 'trade_journal.jsonl',
                             {'action': 'BUY', 'symbol': 'ACME', 'quantity': 2,
                              'entry': 100.05, 'status': 'filled'})
        # A second, unspent event for the same issuer researches normally.
        new_pages = fixtures.earnings_pages(period='2026-Q2')
        page = new_pages[0]
        url = page['url'].replace('000001', '000008')
        new_page = retain_article(
            {**{k: v for k, v in page.items() if not k.startswith('_')},
             'url': url, 'returned_url': url}, original_text(page))
        secondary = {'url': 'https://news.example/acme-add', 'title': 'Synthetic news',
                     'text': 'Synthetic results ' * 80, 'published_at': '2026-11-04T12:00:00Z'}
        scout = {'symbol': 'ACME', 'urls': [new_page['url'], secondary['url']],
                 'event_date': '2026-11-04', 'catalyst': 'synthetic results'}
        self.synthesized.clear()
        self.discovery_calls = 0
        _rc, _ro, _stored_add, entry_code, entry_output = self.research_and_review(
            'ACME', scouts=[scout], bundles=[[new_page, secondary]],
            positions=[{'symbol': 'ACME', 'side': 'long', 'qty': '2',
                        'market_value': '200.1'}])
        self.assertEqual(entry_code, 2, entry_output)
        self.assertIn('position_already_held', entry_output)
        # No add-on reviewer call beyond the first cycle's HOLD reviews.
        self.assertEqual(len(self.review_calls), reviews_before)
        # The only review rows remain the first cycle's HOLD; no add-on review.
        rows = self.review_rows()
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]['dossier_hash'], first_stored['dossier_hash'])

    # ------------------------------------------------------------------
    # crash durability
    # ------------------------------------------------------------------
    def test_crash_after_durable_review_or_grant_before_index_refresh(self):
        # Activated root, one bound unspent candidate generation.
        resolution = self.resolutions[0]
        dossier = 'a' * 64
        storage.append_jsonl(self.root / state.CANDIDATES_STREAM, fixtures.candidate_link(
            dossier, resolution.event_id, state.allowance_identifier(resolution.event_id, 0)))
        candidate = dict(self.candidates()[0])
        candidate['opportunity_identity'] = identity.candidate_identity(resolution)
        stale_index = state.load_index(self.root)

        # Crash: the review is durably appended but no refresh ever runs.
        storage.append_jsonl(self.root / state.REVIEWS_STREAM, fixtures.review_row(
            dossier, 'synthetic-review', [{'decision': 'HOLD'}]))
        # The stale in-memory index still believes the allowance is unspent;
        # the boundary reloader must never trust it.
        decision = state.require_current_allowance(self.root, candidate)
        self.assertEqual((decision.outcome, decision.reason),
                         ('skip', 'unchanged_opportunity'))
        self.assertIsNotNone(decision.allowance_id)
        self.assertEqual(state.require_current_allowance(
            self.root, candidate).outcome, 'skip')
        del stale_index

        # Durable grant to generation 1: the old dossier stays bound to the
        # spent generation 0 and can never borrow the new allowance.
        grant = {'record_type': 'reopen_grant', 'schema_version': 1,
                 'timestamp': '2026-11-04T13:00:00+00:00',
                 'event_id': resolution.event_id, 'generation': 1,
                 'condition_id': 'synthetic-condition',
                 'prior_allowance_id': state.allowance_identifier(resolution.event_id, 0),
                 'allowance_id': state.allowance_identifier(resolution.event_id, 1)}
        storage.append_jsonl(self.root / state.POLICY_STREAM, grant)
        decision = state.require_current_allowance(self.root, candidate)
        self.assertEqual((decision.outcome, decision.reason),
                         ('unknown', 'dossier_binding_missing'))
        # A fresh dossier bound to the new generation is required, and it is
        # eligible only through the same durable link, never by assertion.
        new_dossier = 'b' * 64
        storage.append_jsonl(self.root / state.CANDIDATES_STREAM, fixtures.candidate_link(
            new_dossier, resolution.event_id, state.allowance_identifier(resolution.event_id, 1)))
        fresh_candidate = {'dossier_hash': new_dossier,
                           'opportunity_identity': identity.candidate_identity(resolution)}
        decision = state.require_current_allowance(self.root, fresh_candidate)
        self.assertEqual((decision.outcome, decision.reason),
                         ('eligible', 'allowance_available'))
        self.assertEqual(decision.allowance_id,
                         state.allowance_identifier(resolution.event_id, 1))

    # ------------------------------------------------------------------
    # compatibility-floor rollback (pinned source subprocess)
    # ------------------------------------------------------------------
    def floor_source(self):
        source = os.environ.get('TRADEY_OPPORTUNITY_FLOOR_SOURCE')
        if not source:
            candidate = Path(__file__).resolve().parents[1] / 'private/task7-evidence/floor-source'
            source = str(candidate) if candidate.is_dir() else None
        if source is None:
            self.skipTest('pinned compatibility-floor source copy not provided')
        path = Path(source)
        for name, digest in FLOOR_COMMIT_DIGESTS.items():
            blob = path / name
            self.assertTrue(blob.is_file(), f'missing floor source file {name}')
            self.assertEqual(hashlib.sha256(blob.read_bytes()).hexdigest(), digest,
                             'floor source copy failed digest authentication')
        return path

    def write_floor_root(self, *, protective):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        (root / 'private').mkdir()
        (root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': ['AAPL' if protective else 'ZS']}))
        cfg = policy_config()
        cfg.update(enabled=True, broker_mode='paper',
                   entry_expiry_policy='new_intents_session_close_v1')
        (root / 'autonomy_config.json').write_text(json.dumps(cfg))
        now = dt.datetime.now(dt.timezone.utc)
        stub_snapshot = broker_snapshot(
            captured_at=now.isoformat(),
            quote={'bid': 99.98, 'ask': 100.05, 'timestamp': now.isoformat()},
            cash=10000.0, earnings_status='reported', earnings_sessions_away=None,
            trading_sessions=[(now.date() + dt.timedelta(days=i)).isoformat()
                              for i in range(31)])
        stub_snapshot['asset'] = dict(stub_snapshot['asset'], symbol='ZS')
        stub = {'snapshot': stub_snapshot,
                'orders': {'parent': _PROTECTION_PARENT, 'replacement': _PROTECTION_TARGET}}
        if protective:
            def write(name, row, json_file=False):
                path = root / name
                path.write_text(json.dumps(row) + ('' if json_file else '\n'))
            write('private/broker_baseline.json', {'preexisting_symbols': ['AAPL']}, True)
            write('order_ledger.jsonl', {'client_order_id': 'parent', 'status': 'filled'})
            write('private/order_intents.jsonl', {'client_order_id': 'parent',
                                                  'plan': _PROTECTION_PLAN})
            write('trade_journal.jsonl', {'action': 'BUY', 'symbol': 'ZS', 'quantity': 3,
                                          'entry': 162.79, 'status': 'filled'})
            write('private/protection_orders.jsonl',
                  {'parent_client_order_id': 'parent',
                   'protection_client_order_id': 'replacement', 'symbol': 'ZS',
                   'quantity': 3, 'stop': 151.24, 'target': 184.37,
                   'registered_at': '2026-09-08T14:00:00Z'})
        else:
            (root / 'candidates.jsonl').write_text(json.dumps({
                'symbol': 'ZS', 'sources_verified_at': now.isoformat()}) + '\n')
        # The activated v1 record is exactly what the floor must reject.
        storage.append_jsonl(root / 'private/opportunity_policy.jsonl', {
            'record_type': 'activation', 'schema_version': 1, 'policy_version': 1,
            'manifest_sha256': 'a' * 64, 'timestamp': '2026-11-04T12:00:00+00:00'})
        stub_path = root / 'floor_broker_stub.json'
        stub_path.write_text(json.dumps(stub))
        return root, stub_path

    def run_floor(self, stub_path, root):
        source = self.floor_source()
        env = dict(os.environ,
                   PYTHONDONTWRITEBYTECODE='1',
                   TRADEY_OPPORTUNITY_FLOOR_SOURCE=str(source),
                   HERMES_DISABLE_LAZY_INSTALLS='1')
        env.pop('PYTHONPATH', None)
        result = subprocess.run(
            [os.environ.get('TRADEY_TEST_PYTHON', __import__('sys').executable),
             '-c', _FLOOR_DRIVER, str(stub_path), str(root)],
            cwd=str(root), env=env, capture_output=True, text=True, timeout=120)
        self.assertEqual(result.returncode, 0,
                         f'floor driver failed: {result.stderr[-2000:]}')
        return json.loads(result.stdout.strip().splitlines()[-1])

    def floor_guard_and_lifecycle_scenario(self):
        """Execute the pinned floor against an activated v1 root, twice:
        once with live protective state and once with entry-only state."""
        self.protection_reconciled = False
        self.new_entry_submitted = False
        self.blocker = None
        protective_root, protective_stub = self.write_floor_root(protective=True)
        protective = self.run_floor(protective_stub, protective_root)
        self.assertEqual(protective['supported_policy_version'], 0)
        self.assertEqual(protective['code'], 0, protective['output'])
        self.assertIn('TRADE SELL 3', protective['output'])
        journal = storage.read_jsonl(protective_root / 'trade_journal.jsonl')
        sells = [row for row in journal if row.get('action') == 'SELL']
        self.assertEqual(len(sells), 1)
        self.assertEqual((sells[0]['symbol'], sells[0]['quantity']), ('ZS', 3))
        self.protection_reconciled = True
        # No new BUY entry may appear in the protective cycle (the fixture
        # BUY row is preexisting history).
        ledger = storage.read_jsonl(protective_root / 'order_ledger.jsonl')
        self.assertFalse(any(row.get('action') == 'BUY' and row.get('status') == 'proposed'
                             for row in ledger))

        entry_root, entry_stub = self.write_floor_root(protective=False)
        entry = self.run_floor(entry_stub, entry_root)
        self.assertEqual(entry['supported_policy_version'], 0)
        self.assertEqual(entry['code'], 2, entry['output'])
        self.assertEqual(entry['output'], 'BLOCKER opportunity_policy_version_unsupported\n')
        self.blocker = 'opportunity_policy_version_unsupported'
        self.assertFalse((entry_root / 'private/reviews.jsonl').exists())
        ledger = storage.read_jsonl(entry_root / 'order_ledger.jsonl') \
            if (entry_root / 'order_ledger.jsonl').exists() else []
        self.assertFalse(any(row.get('action') == 'BUY' for row in ledger))
        self.assertFalse((entry_root / 'trade_journal.jsonl').exists())

    def test_floor_rollback_blocks_entry_but_preserves_protection(self):
        self.floor_guard_and_lifecycle_scenario()
        self.assertTrue(self.protection_reconciled)
        self.assertFalse(self.new_entry_submitted)
        self.assertEqual(self.blocker, 'opportunity_policy_version_unsupported')

    def test_malformed_or_incomplete_activation_cannot_silently_disable_guard(self):
        # A corrupted activation envelope must fail closed at every boundary:
        # Radar research, the entry boundary and the direct guard API.
        path = self.root / state.POLICY_STREAM
        rows = storage.read_jsonl(path)
        rows[0]['schema_version'] = 2
        path.write_text(''.join(json.dumps(row) + '\n' for row in rows))
        with self.assertRaises(state.OpportunityStateError):
            state.require_current_allowance(
                self.root, {'opportunity_identity': fixtures.synthetic_resolution_payload()})
        output = io.StringIO()
        with patch('sys.stdout', output):
            code = radar.main_with_args(argparse.Namespace(dry_run_fixture=False))
        self.assertEqual((code, output.getvalue()),
                         (3, 'SYSTEM_FAILURE opportunity_policy_state_unavailable\n'))
        entry_code, entry_output = self.run_entry(symbol='ACME')
        # Lifecycle reconciliation is itself entitled to the same canonical
        # state and fails closed first; the guard is never silently disabled.
        self.assertEqual(entry_code, 2, entry_output)
        self.assertTrue(entry_output.startswith('BLOCKER'), entry_output)
        self.assertEqual(self.review_calls, [])
        self.assertFalse((self.root / state.REVIEWS_STREAM).exists())
        # An activation projection whose database sidecar went missing is
        # incomplete state, never a silent downgrade to the legacy floor.
        fresh = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixtures.make_root(fresh, active=True)
        storage.migrate_jsonl(fresh)
        (fresh / 'private/opportunity_policy.jsonl').unlink()
        with self.assertRaises(state.OpportunityStateError) as caught:
            state.require_current_allowance(
                fresh, {'opportunity_identity': fixtures.synthetic_resolution_payload()})
        self.assertNotEqual(str(caught.exception), 'opportunity_policy_not_activated')

    # ------------------------------------------------------------------
    # wrong-result injection matrix
    # ------------------------------------------------------------------
    def activated_candidate_root(self):
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixtures.make_root(root, active=True)
        (root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': []}))
        resolution = identity.resolve_event(
            'ACME', fixtures.earnings_pages(), known_resolutions=())
        identity.retain_observations(root, resolution, fixtures.earnings_pages())
        storage.append_jsonl(root / state.POLICY_STREAM, fixtures.policy_row(
            'identity_resolution', resolution=identity.candidate_identity(resolution)))
        dossier = 'a' * 64
        storage.append_jsonl(root / state.CANDIDATES_STREAM, fixtures.candidate_link(
            dossier, resolution.event_id, state.allowance_identifier(resolution.event_id, 0)))
        return root, resolution, dossier

    def test_wrong_row_results_fail_closed_per_important_row(self):
        # Each important row is injected with a wrong result; every injection
        # must produce its intended typed, fail-closed outcome (never a setup
        # error and never a permissive default).
        base_root, resolution, dossier = self.activated_candidate_root()
        candidate = {'dossier_hash': dossier,
                     'opportunity_identity': identity.candidate_identity(resolution)}

        # 1. activation envelope corrupted: typed unavailable, not legacy.
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        storage.append_jsonl(root / 'private/opportunity_policy.jsonl', {
            'record_type': 'activation', 'schema_version': 2, 'policy_version': 1,
            'manifest_sha256': 'a' * 64, 'timestamp': '2026-11-04T12:00:00+00:00'})
        with self.assertRaisesRegex(state.OpportunityStateError,
                                    'opportunity_policy_state_unavailable'):
            state.require_current_allowance(root, candidate)

        # 2. identity resolution row points at a conflicting issuer record.
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixtures.make_root(root, active=True)
        (root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': []}))
        resolution = identity.resolve_event(
            'ACME', fixtures.earnings_pages(), known_resolutions=())
        identity.retain_observations(root, resolution, fixtures.earnings_pages())
        forged = identity.candidate_identity(resolution)
        forged['issuer']['legal_name'] = 'Wrong Name Inc.'
        storage.append_jsonl(root / state.POLICY_STREAM, fixtures.policy_row(
            'identity_resolution', resolution=forged))
        context = state.load_policy_context(root)
        decision = state.candidate_policy(context, resolution, symbol='ACME')
        self.assertEqual((decision.outcome, decision.reason),
                         ('unknown', 'opportunity_identity_conflict'))

        # 3. candidate link borrowed from another event's allowance.
        root = Path(self.enterContext(tempfile.TemporaryDirectory()))
        fixtures.make_root(root, active=True)
        (root / 'private/broker_baseline.json').write_text(
            json.dumps({'preexisting_symbols': []}))
        resolution = identity.resolve_event(
            'ACME', fixtures.earnings_pages(), known_resolutions=())
        identity.retain_observations(root, resolution, fixtures.earnings_pages())
        storage.append_jsonl(root / state.POLICY_STREAM, fixtures.policy_row(
            'identity_resolution', resolution=identity.candidate_identity(resolution)))
        storage.append_jsonl(root / state.CANDIDATES_STREAM, fixtures.candidate_link(
            dossier, resolution.event_id, state.allowance_identifier('ev-other', 0)))
        # A link to an allowance that was never bound to this event is not a
        # coherent index: typed unavailable, never a permissive decision.
        with self.assertRaises(state.OpportunityStateError):
            state.require_current_allowance(root, candidate)

        # 4. review-row wrong results: marker output never spends, real
        # decisions always spend.
        root, _r, _d = self.activated_candidate_root()
        storage.append_jsonl(root / state.REVIEWS_STREAM, fixtures.review_row(
            dossier, 'synthetic-marker', [{'decision': 'reconciliation_blocked'}]))
        decision = state.require_current_allowance(root, candidate)
        self.assertEqual((decision.outcome, decision.reason),
                         ('eligible', 'allowance_available'))
        storage.append_jsonl(root / state.REVIEWS_STREAM, fixtures.review_row(
            dossier, 'synthetic-hold', [{'decision': 'HOLD'}]))
        decision = state.require_current_allowance(root, candidate)
        self.assertEqual((decision.outcome, decision.reason), ('skip', 'unchanged_opportunity'))

        # 5. grant chain inconsistency: typed unavailable, never a reset.
        root, _r, _d = self.activated_candidate_root()
        event_id = resolution.event_id
        storage.append_jsonl(root / state.POLICY_STREAM, {
            'record_type': 'reopen_grant', 'schema_version': 1,
            'timestamp': '2026-11-04T13:00:00+00:00', 'event_id': event_id,
            'generation': 1, 'condition_id': 'synthetic-condition',
            'prior_allowance_id': state.allowance_identifier('ev-wrong', 0),
            'allowance_id': state.allowance_identifier(event_id, 1)})
        with self.assertRaises(state.OpportunityStateError):
            state.load_index(root)

        # 6. malformed broker baseline: typed failure, not flat permission.
        root, _r, _d = self.activated_candidate_root()
        (root / 'private/broker_baseline.json').write_text('not-json')
        with self.assertRaisesRegex(state.OpportunityStateError, 'broker_baseline_invalid'):
            state.load_policy_context(root)


if __name__ == '__main__':
    unittest.main()
