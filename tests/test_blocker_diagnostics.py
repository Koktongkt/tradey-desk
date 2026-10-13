"""Blocker-diagnostics tests.

Every deterministic rejection must persist a private structured diagnostics
row (timestamp, stage, symbol, action, reason, measured values, configured
threshold) under private/blocker_diagnostics.jsonl for real paper cycles and
test_artifacts/ for dry runs, so questions like "how wide was the spread"
are answerable without exposing sanitized public output. The public
dashboard gains a sanitized projection of those rows (no ids, no paths).
"""
import contextlib
import datetime as dt
import hashlib
import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import autotrader
from support_fixtures import broker_snapshot, policy_config as _cfg


def _quote(bid=99.98, ask=100.02):
    now = dt.datetime.now(dt.timezone.utc).isoformat().replace("+00:00", "Z")
    return {"bid": bid, "ask": ask, "timestamp": now}


def _snapshot(quote=None, cash=10000.0):
    now = dt.datetime.now(dt.timezone.utc)
    return broker_snapshot(
        captured_at=now.isoformat().replace("+00:00", "Z"), cash=cash,
        quote=quote or _quote(), earnings_status="upcoming", earnings_sessions_away=9,
        trading_sessions=[(now.date() + dt.timedelta(days=i)).isoformat() for i in range(31)],
    )


def _order():
    return {
        "action": "BUY", "symbol": "DELL", "quantity": 5, "order_type": "limit",
        "limit_price": 100.02, "stop": 95.0, "target": 108.0, "confidence": 0.9,
        "horizon": "3 sessions",
    }


class ValidateOrderDetailsTests(unittest.TestCase):
    def test_errors_identical_between_plain_and_details_variants(self):
        snap = _snapshot(quote=_quote(98.0, 105.0))  # wide spread
        errors = autotrader.validate_order(_order(), snap, _cfg(), 0, 0.0, set())
        errors2, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        self.assertEqual(errors, errors2)
        self.assertTrue(errors)

    def test_spread_too_wide_records_measured_and_threshold(self):
        snap = _snapshot(quote=_quote(98.0, 105.0))
        _, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        d = details["spread_too_wide"]
        self.assertEqual(d["bid"], 98.0)
        self.assertEqual(d["ask"], 105.0)
        self.assertAlmostEqual(d["midpoint"], 101.5)
        self.assertAlmostEqual(d["spread_bps"], (105.0 - 98.0) / 101.5 * 10000, places=1)
        self.assertEqual(d["max_spread_bps"], 600)
        self.assertEqual(d["quote_feed"], "alpaca_iex")

    def test_limit_deviation_records_reference_and_threshold(self):
        snap = _snapshot()
        order = _order()
        order["limit_price"] = 100.02 + 3.0  # BUY measured against ask
        errors, details = autotrader.validate_order_with_details(order, snap, _cfg(), 0, 0.0, set())
        self.assertIn("limit_price_too_far_from_quote", errors)
        d = details["limit_price_too_far_from_quote"]
        self.assertEqual(d["limit_price"], 103.02)
        self.assertEqual(d["reference_price"], 100.02)
        self.assertEqual(d["reference_side"], "ask")
        self.assertAlmostEqual(d["deviation_bps"], 3.0 / 100.02 * 10000, places=4)
        self.assertEqual(d["max_limit_deviation_bps"], 150)

    def test_weak_reward_to_risk_records_ratio_and_threshold(self):
        order = _order()
        order["target"] = 100.5
        errors, details = autotrader.validate_order_with_details(order, _snapshot(), _cfg(), 0, 0.0, set())
        self.assertIn("weak_reward_to_risk", errors)
        d = details["weak_reward_to_risk"]
        self.assertAlmostEqual(d["risk_reward"], (100.5 - 100.02) / (100.02 - 95.0), places=6)
        self.assertEqual(d["min_reward_risk"], 1.6)

    def test_near_term_earnings_records_state_and_blackout(self):
        snap = _snapshot()
        snap["earnings_sessions_away"] = 1
        errors, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        self.assertIn("near_term_earnings", errors)
        d = details["near_term_earnings"]
        self.assertEqual(d["earnings_status"], "upcoming")
        self.assertEqual(d["earnings_sessions_away"], 1)
        self.assertEqual(d["earnings_blackout_sessions"], 2)

    def test_insufficient_cash_records_basis_and_cash(self):
        errors, details = autotrader.validate_order_with_details(
            _order(), _snapshot(cash=10.0), _cfg(), 0, 0.0, set())
        self.assertIn("insufficient_cash", errors)
        d = details["insufficient_cash"]
        self.assertEqual(d["cash"], 10.0)
        self.assertAlmostEqual(d["dollar_basis"], 100.02 * 5, places=2)

    def test_unknown_reasons_carry_context(self):
        snap = _snapshot(quote={})
        snap["quote_feed"] = "unknown_feed"
        errors, details = autotrader.validate_order_with_details(_order(), snap, _cfg(), 0, 0.0, set())
        self.assertIn("quote_feed_unavailable", errors)
        self.assertEqual(details["quote_feed_unavailable"]["quote_feed"], "unknown_feed")
        self.assertEqual(details["quote_feed_unavailable"]["allowed_quote_feeds"], ["alpaca_iex"])


def _candidate(root):
    now = dt.datetime.now(dt.timezone.utc)
    cand = {
        "symbol": "DELL",
        "researched_at": (now - dt.timedelta(minutes=5)).isoformat().replace("+00:00", "Z"),
        "sources_verified_at": (now - dt.timedelta(minutes=4)).isoformat().replace("+00:00", "Z"),
        "sources": [{"url": "https://a.example/1", "title": "A"}, {"url": "https://b.example/2", "title": "B"}],
        "price": 100.0, "spy_price": 500.0, "instrument_type": "cash_equity",
        "setup_type": "breakout",
        "earnings_event_at": (now + dt.timedelta(days=30)).isoformat().replace("+00:00", "Z"),
        "planned_exit_at": (now + dt.timedelta(days=3)).isoformat().replace("+00:00", "Z"),
        "horizon_rationale": "short",
        "catalyst": "guidance raise", "thesis": "post-news drift",
    }
    body = {k: v for k, v in cand.items() if k != "dossier_hash"}
    cand["dossier_hash"] = hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return cand


def _setup_root(root, snapshot, quote=None):
    (root / "autonomy_config.json").write_text(json.dumps(_cfg()))
    (root / "private").mkdir(exist_ok=True)
    autotrader.append_jsonl(root / "candidates.jsonl", _candidate(root))


def _run_in_root(root, snapshot, live_dry_run=False, review_snapshot=None):
    calls = []
    def fake_bridge(op, payload=None):
        calls.append(op)
        if op == "snapshot":
            return snapshot
        if op == "review":
            return review_snapshot or snapshot
        raise AssertionError(f"unexpected bridge op {op}")
    with patch.object(autotrader, "ROOT", root), patch(
        "autotrader._broker_bridge", side_effect=fake_bridge
    ), patch("autotrader.load_baseline_symbols", return_value=set()), patch(
        "autotrader.reconcile_managed_protection", return_value=[]
    ):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = autotrader.run(autotrader.argparse.Namespace(
                dry_run_fixture=False, live_dry_run=live_dry_run))
    return code, out.getvalue(), calls


class EarningsSpendingTests(unittest.TestCase):
    def test_legacy_unlinked_rejections_preserved_without_invented_spending(self):
        import earnings_spending
        legacy = {'status': 'rejected', 'reason': ['near_term_earnings'],
                  'symbol': 'DELL', 'action': 'BUY', 'order_type': 'limit',
                  'client_order_id': 'tradey-legacy-ref', 'evidence_id': 'legacy-evidence',
                  'timestamp': '2026-09-02T14:45:55.539119Z'}
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / 'order_ledger.jsonl'
            ledger.write_text(json.dumps(legacy) + '\n')
            before = ledger.read_bytes()
            rows = earnings_spending.spending_rows(ledger)
            self.assertEqual(rows, [legacy])
            self.assertFalse(earnings_spending.is_spent(
                {'symbol': 'DELL', 'dossier_hash': 'new-dossier',
                 'earnings_event_at': '2026-11-01',
                 'planned_exit_at': '2026-10-23T20:00:00Z'}, ledger, rows=rows))
            self.assertEqual(ledger.read_bytes(), before)
            for modern in ({**legacy, 'stage': 'precheck'},
                           {**legacy, 'earnings_setup_key': None},
                           {**legacy, 'dossier_hash': None},
                           {'status': 'rejected', 'reason': 'near_term_earnings'}):
                ledger.write_text(json.dumps(modern) + '\n')
                with self.assertRaises(earnings_spending.SpendingStateError):
                    earnings_spending.spending_rows(ledger)

    def test_same_exchange_session_time_changes_cannot_revive_spent_setup(self):
        import earnings_spending
        candidate = {'symbol': 'DELL', 'dossier_hash': 'original',
                     'earnings_event_at': '2026-10-28',
                     'planned_exit_at': '2026-10-23T19:45:00Z'}
        with tempfile.TemporaryDirectory() as td:
            ledger = Path(td) / 'order_ledger.jsonl'
            autotrader.append_jsonl(ledger, earnings_spending.rejection(
                candidate, 'precheck', '2026-10-12T16:10:00Z'))
            for changes in ({'planned_exit_at': '2026-10-23T19:44:59Z'},
                            {'earnings_event_at': '2026-10-28T20:05:00Z'},
                            {'planned_exit_at': '2026-10-24T00:30:00Z'},
                            {'symbol': 'dell'}):
                with self.subTest(changes=changes):
                    self.assertTrue(earnings_spending.is_spent(
                        {**candidate, **changes, 'dossier_hash': 'refreshed'}, ledger))
            self.assertFalse(earnings_spending.is_spent(
                {**candidate, 'planned_exit_at': '2026-10-22T19:45:00Z',
                 'dossier_hash': 'genuinely-different-horizon'}, ledger))

    def test_timestamp_refresh_cannot_publish_same_earnings_exit_setup(self):
        import alpha_radar
        import earnings_spending
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            snap['earnings_sessions_away'] = 1
            _setup_root(root, snap)
            original = json.loads((root / 'candidates.jsonl').read_text())
            _run_in_root(root, snap)
            refreshed = {**original, 'candidate_id': 'new-id', 'dossier_hash': 'new-hash',
                         'researched_at': autotrader.utcnow(), 'sources_verified_at': autotrader.utcnow(),
                         'price': 102, 'thesis': 'rewritten marketing', 'catalyst': 'rewritten news'}
            for name in ('earnings_event_at', 'planned_exit_at'):
                refreshed[name] = dt.datetime.fromisoformat(original[name].replace('Z', '+00:00')).astimezone(dt.timezone(dt.timedelta(hours=-4))).isoformat()
            refreshed['dossier_hash'] = hashlib.sha256(json.dumps({k: v for k, v in refreshed.items() if k != 'dossier_hash'}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
            self.assertTrue(earnings_spending.is_spent(refreshed, root / 'order_ledger.jsonl'))
            with patch.object(alpha_radar, 'ROOT', root), patch.object(alpha_radar, 'candidate_preflight', return_value=[]), patch.object(alpha_radar, 'qualified', return_value=True), patch.object(alpha_radar, 'source_verification_result') as sources:
                with self.assertRaisesRegex(alpha_radar.CandidateRejection, 'near_term_earnings'):
                    alpha_radar.prepare_candidate(refreshed, _cfg(), ledger_path=root / 'order_ledger.jsonl')
                sources.assert_not_called()
            autotrader.append_jsonl(root / 'candidates.jsonl', refreshed)
            code, out, calls = _run_in_root(root, snap)
            self.assertEqual((code, calls), (0, []))
            self.assertIn('skipped near_term_earnings', out)
            for field, value in [('symbol', 'IBM'), ('earnings_event_at', '2027-05-01T20:00:00Z'), ('planned_exit_at', '2027-04-01T20:00:00Z')]:
                changed = {**refreshed, field: value}
                self.assertFalse(earnings_spending.is_spent(changed, root / 'order_ledger.jsonl'))
                self.assertTrue(earnings_spending.is_spent({**changed, 'dossier_hash': original['dossier_hash']}, root / 'order_ledger.jsonl'))

    def test_final_and_fresh_broker_rejections_spend_refreshed_setup(self):
        import earnings_spending
        for stage in ('final_validation', 'broker_review'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                good = _snapshot()
                _setup_root(root, good)
                candidate = json.loads((root / 'candidates.jsonl').read_text())
                def approve(bundle, cfg):
                    return [{'proposal_hash': bundle['proposal']['proposal_hash'], 'decision': 'APPROVE', 'fatal_flags': [],
                             'reason_codes': [], 'component_scores': {k: 5 for k in autotrader.RUBRIC_WEIGHTS['short_1_5']}}] * 2
                fresh = _snapshot()
                fresh['earnings_sessions_away'] = 1
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch('autotrader.independent_reviews', side_effect=approve))
                    stack.enter_context(patch('autotrader.record_shadow_decision'))
                    if stage == 'final_validation':
                        stack.enter_context(patch('autotrader.post_review_validation', return_value=(['near_term_earnings'], {})))
                    code, out, calls = _run_in_root(root, good, review_snapshot=fresh)
                self.assertEqual(code, 2, out)
                self.assertIn('near_term_earnings', out)
                self.assertEqual(calls, ['snapshot'] if stage == 'final_validation' else ['snapshot', 'review'])
                self.assertTrue(earnings_spending.is_spent({**candidate, 'dossier_hash': 'refreshed'}, root / 'order_ledger.jsonl'))
                rows = autotrader.read_jsonl(root / 'order_ledger.jsonl', strict=True)
                self.assertEqual(rows[-1]['stage'], stage)
                self.assertEqual(autotrader._daily_order_count(root / 'order_ledger.jsonl'), 0)
                self.assertFalse((root / 'trade_journal.jsonl').exists())

    def test_bad_spending_state_fails_closed_without_candidate_snapshot(self):
        import alpha_radar
        import earnings_spending
        for content in ('not-json\n', json.dumps({'status': 'rejected', 'reason': 'near_term_earnings', 'dossier_hash': []}) + '\n'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                snap = _snapshot()
                # Legacy fresh-install projections have no SQLite store yet.
                (root / 'autonomy_config.json').write_text(json.dumps(_cfg()))
                (root / 'candidates.jsonl').write_text(json.dumps(_candidate(root)) + '\n')
                (root / 'private').mkdir()
                (root / 'order_ledger.jsonl').write_text(content)
                with patch('autotrader.independent_reviews', side_effect=AssertionError('review forbidden')):
                    code, out, calls = _run_in_root(root, snap)
                self.assertEqual((code, calls), (4, []), out)
                self.assertIn('SYSTEM_FAILURE earnings_spending_state', out)
                with patch.object(alpha_radar, 'ROOT', root), patch.object(alpha_radar, 'live_research') as research, contextlib.redirect_stdout(io.StringIO()) as stdout:
                    result = alpha_radar.main_with_args(autotrader.argparse.Namespace(dry_run_fixture=False))
                self.assertEqual(result, 3)
                self.assertIn('SYSTEM_FAILURE earnings_spending_state', stdout.getvalue())
                research.assert_not_called()
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            _setup_root(root, snap)
            with patch.object(earnings_spending, 'read_jsonl', side_effect=PermissionError('unreadable')):
                code, out, calls = _run_in_root(root, snap)
            self.assertEqual((code, calls), (4, []), out)

    def test_spending_write_failure_is_not_reported_as_rejection_success(self):
        for stage in ('precheck', 'final_validation', 'broker_review'):
            with self.subTest(stage=stage), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                good = _snapshot()
                _setup_root(root, good)
                if stage == 'precheck':good['earnings_sessions_away'] = 1
                fresh = _snapshot()
                fresh['earnings_sessions_away'] = 1
                real_append = autotrader.append_jsonl
                def broken_append(path, row):
                    reason = row.get('reason')
                    if Path(path) == root / 'order_ledger.jsonl' and (reason == 'near_term_earnings' or isinstance(reason, list) and 'near_term_earnings' in reason):
                        raise OSError('durability failure')
                    return real_append(path, row)
                def approve(bundle, cfg):
                    return [{'proposal_hash': bundle['proposal']['proposal_hash'], 'decision': 'APPROVE', 'fatal_flags': [],
                             'reason_codes': [], 'component_scores': {k: 5 for k in autotrader.RUBRIC_WEIGHTS['short_1_5']}}] * 2
                with contextlib.ExitStack() as stack:
                    stack.enter_context(patch('autotrader.append_jsonl', side_effect=broken_append))
                    stack.enter_context(patch('autotrader.independent_reviews', side_effect=approve))
                    stack.enter_context(patch('autotrader.record_shadow_decision'))
                    if stage == 'final_validation':stack.enter_context(patch('autotrader.post_review_validation', return_value=(['near_term_earnings'], {})))
                    code, out, calls = _run_in_root(root, good, review_snapshot=fresh)
                self.assertEqual(code, 4, out)
                self.assertIn('SYSTEM_FAILURE earnings_spending_persistence', out)
                self.assertNotIn('place', calls)
                self.assertFalse((root / 'trade_journal.jsonl').exists())

    def test_spending_read_never_imports_unsynchronized_projection(self):
        import earnings_spending
        import alpha_radar
        from sqlite_ledger import database_path
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            _setup_root(root, _snapshot())
            ledger = root / 'order_ledger.jsonl'
            autotrader.append_jsonl(ledger, {'status': 'rejected', 'reason': 'spread_too_wide'})
            db = database_path(ledger)
            before = (db.read_bytes(), db.stat().st_mtime_ns)
            with ledger.open('a') as stream:stream.write(json.dumps({'status': 'rejected', 'reason': 'stale_quote'}) + '\n')
            candidate = json.loads((root / 'candidates.jsonl').read_text())
            with self.assertRaises(earnings_spending.SpendingStateError):
                earnings_spending.is_spent(candidate, ledger)
            self.assertEqual((db.read_bytes(), db.stat().st_mtime_ns), before)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'autonomy_config.json').write_text(json.dumps(_cfg()))
            (root / 'candidates.jsonl').write_text('')
            (root / 'order_ledger.jsonl').write_text('invalid\n')
            with self.assertRaises(earnings_spending.SpendingStateError):
                alpha_radar.reusable_fresh_candidate(root / 'candidates.jsonl', root / 'private/reviews.jsonl')

    def test_retry_marker_cannot_revive_earnings_spent_dossier(self):
        import alpha_radar
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            snap['earnings_sessions_away'] = 1
            _setup_root(root, snap)
            candidate = autotrader.read_jsonl(root / 'candidates.jsonl')[-1]
            _run_in_root(root, snap)
            autotrader.append_jsonl(root / 'private/reviews.jsonl', {'timestamp': autotrader.utcnow(), 'dossier_hash': candidate['dossier_hash'], 'evidence_id': 'approved', 'reviews': [{'decision': 'APPROVE'}] * 2})
            autotrader.note_pre_submission_retryable(root / 'private/reviews.jsonl', candidate, 'approved')
            autotrader.append_jsonl(root / 'order_ledger.jsonl', {'status': 'rejected', 'evidence_id': 'approved', 'reason': ['stale_quote']})
            with patch('autotrader.independent_reviews', side_effect=AssertionError('no reviews')):
                code, out, calls = _run_in_root(root, snap)
            self.assertEqual((code, calls), (0, []), out)
            with patch.object(alpha_radar, 'candidate_preflight', return_value=[]), patch.object(alpha_radar, 'qualified', return_value=True), patch.object(alpha_radar, 'pre_submission_retryable', return_value=True):
                self.assertIsNone(alpha_radar.reusable_fresh_candidate(root / 'candidates.jsonl', root / 'private/reviews.jsonl'))

    def test_unknown_earnings_and_transient_quote_alone_do_not_spend(self):
        import earnings_spending
        for earnings, quote in [('unknown', _quote()), ('upcoming', _quote(98, 105))]:
            with self.subTest(earnings=earnings), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                snap = _snapshot(quote=quote)
                snap['earnings_status'] = earnings
                if earnings == 'unknown':snap['earnings_sessions_away'] = None
                _setup_root(root, snap)
                candidate = autotrader.read_jsonl(root / 'candidates.jsonl')[-1]
                with patch('autotrader.independent_reviews', side_effect=AssertionError('no review')):
                    code, out, calls = _run_in_root(root, snap)
                self.assertEqual(code, 2, out)
                self.assertNotIn('near_term_earnings', out)
                self.assertEqual(calls, ['snapshot'])
                self.assertFalse(earnings_spending.is_spent(candidate, root / 'order_ledger.jsonl'))
                self.assertFalse((root / 'order_ledger.jsonl').exists())

    def test_missing_setup_identity_uses_exact_hash_only(self):
        import earnings_spending
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            candidate = {'symbol': 'DELL', 'dossier_hash': 'exact'}
            row = earnings_spending.rejection(candidate, 'precheck', autotrader.utcnow())
            autotrader.append_jsonl(root / 'order_ledger.jsonl', row)
            self.assertIsNone(row['earnings_setup_key'])
            self.assertTrue(earnings_spending.is_spent(candidate, root / 'order_ledger.jsonl'))
            self.assertFalse(earnings_spending.is_spent({**candidate, 'dossier_hash': 'different'}, root / 'order_ledger.jsonl'))
            for event in (None, 'not-a-date'):
                self.assertIsNone(earnings_spending.setup_key({**candidate, 'earnings_event_at': event, 'planned_exit_at': '2027-01-01'}))
            aware = {**candidate, 'earnings_event_at': '2027-01-01T00:00:00Z', 'planned_exit_at': '2027-02-01T00:00:00Z'}
            self.assertNotEqual(earnings_spending.setup_key(aware), earnings_spending.setup_key({**aware, 'earnings_event_at': '2027-01-01'}))
            self.assertNotEqual(earnings_spending.setup_key(aware), earnings_spending.setup_key({**aware, 'earnings_event_at': '2027-01-01T00:00:00'}))

    def test_pending_reconciliation_still_precedes_spent_skip(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            snap['earnings_sessions_away'] = 1
            _setup_root(root, snap)
            _run_in_root(root, snap)
            with patch('autotrader.reconcile_pending_orders', side_effect=RuntimeError('pending obligation')) as pending, patch('autotrader.independent_reviews', side_effect=AssertionError('no review')):
                code, out, calls = _run_in_root(root, snap)
            pending.assert_called_once()
            self.assertEqual((code, calls), (4, []))
            self.assertIn('SYSTEM_FAILURE pending_order_reconciliation', out)

    def test_fixture_and_live_dry_run_spending_is_isolated(self):
        import earnings_spending
        for fixture in (False, True):
            with self.subTest(fixture=fixture), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                snap = _snapshot()
                snap['earnings_sessions_away'] = 1
                _setup_root(root, snap)
                candidate = autotrader.read_jsonl(root / 'candidates.jsonl')[-1]
                if fixture:
                    (root / 'fixtures').mkdir()
                    (root / 'fixtures/dry_run_bundle.json').write_text(json.dumps({'snapshot': snap, 'candidate': candidate, 'review_a': {}, 'review_b': {}}))
                    with patch.object(autotrader, 'ROOT', root), patch('autotrader._broker_bridge', side_effect=AssertionError('fixture no broker')), contextlib.redirect_stdout(io.StringIO()):
                        code = autotrader.run(autotrader.argparse.Namespace(dry_run_fixture=True, live_dry_run=False))
                else:
                    with patch('autotrader.independent_reviews', side_effect=AssertionError('precheck no reviewer')):
                        code, out, calls = _run_in_root(root, snap, live_dry_run=True)
                    self.assertEqual(calls, ['snapshot'])
                self.assertEqual(code, 2)
                artifact = root / 'test_artifacts/dry_run_order_ledger.jsonl'
                self.assertTrue(earnings_spending.is_spent(candidate, artifact))
                self.assertFalse(earnings_spending.is_spent(candidate, root / 'order_ledger.jsonl'))
                self.assertFalse((root / 'order_ledger.jsonl').exists())
                with patch('autotrader.independent_reviews', side_effect=AssertionError('precheck no reviewer')):
                    code, out, calls = _run_in_root(root, snap)
                self.assertEqual((code, calls), (2, ['snapshot']))
                self.assertIn('BLOCKER near_term_earnings', out)

    def test_cycle_records_earnings_spent_as_skip_not_completion(self):
        import run_cycle
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / 'decision_audit.jsonl'
            run_cycle.audit_result('autotrader', 'execution', 0,
                                   'DECISION skipped near_term_earnings', path)
            rows = autotrader.read_jsonl(path, strict=True)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['decision'], 'skipped')
            self.assertEqual(rows[0]['reason'], 'near_term_earnings')
            self.assertEqual(rows[0]['mode'], 'autotrader')
            self.assertEqual(rows[0]['stage'], 'execution')

    def test_cycle_recognizes_spending_failure_classifications(self):
        import run_cycle
        for reason in ('earnings_spending_state', 'earnings_spending_persistence'):
            line = 'SYSTEM_FAILURE ' + reason
            self.assertEqual(run_cycle.parse_failure_event(line), line)

    def test_radar_fallback_reports_spending_state_failure(self):
        import alpha_radar
        import earnings_spending
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / 'autonomy_config.json').write_text(json.dumps(_cfg()))
            with patch.object(alpha_radar, 'ROOT', root), patch.object(alpha_radar, 'reusable_fresh_candidate', side_effect=[None, earnings_spending.SpendingStateError('bad state')]), patch.object(alpha_radar, 'live_research', side_effect=alpha_radar.ResearchFailure('research_scout_timeout')), contextlib.redirect_stdout(io.StringIO()) as stdout:
                code = alpha_radar.main_with_args(autotrader.argparse.Namespace(dry_run_fixture=False))
            self.assertEqual(code, 3)
            self.assertIn('SYSTEM_FAILURE earnings_spending_state', stdout.getvalue())

    def test_changed_earnings_or_exit_setup_faces_authoritative_checks_again(self):
        for field in ('earnings_event_at', 'planned_exit_at'):
            with self.subTest(field=field), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                snap = _snapshot()
                snap['earnings_sessions_away'] = 1
                _setup_root(root, snap)
                original = autotrader.read_jsonl(root / 'candidates.jsonl')[-1]
                _run_in_root(root, snap)
                changed = dict(original)
                changed[field] = (dt.datetime.fromisoformat(changed[field].replace('Z', '+00:00')) + dt.timedelta(days=1)).isoformat()
                changed['dossier_hash'] = hashlib.sha256(json.dumps({k: v for k, v in changed.items() if k != 'dossier_hash'}, sort_keys=True, separators=(',', ':')).encode()).hexdigest()
                autotrader.append_jsonl(root / 'candidates.jsonl', changed)
                with patch('autotrader.independent_reviews', side_effect=AssertionError('precheck must block')):
                    code, out, calls = _run_in_root(root, snap)
                self.assertEqual((code, calls), (2, ['snapshot']), out)
                self.assertIn('BLOCKER near_term_earnings', out)
                self.assertEqual(len(autotrader.read_jsonl(root / 'order_ledger.jsonl')), 2)

    def test_unrelated_older_dossier_remains_reusable(self):
        import alpha_radar
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            snap['earnings_sessions_away'] = 1
            _setup_root(root, snap)
            blocked = autotrader.read_jsonl(root / 'candidates.jsonl')[-1]
            unrelated = {**blocked, 'symbol': 'IBM', 'dossier_hash': 'unrelated'}
            autotrader.append_jsonl(root / 'candidates.jsonl', unrelated)
            autotrader.append_jsonl(root / 'candidates.jsonl', blocked)
            _run_in_root(root, snap)
            with patch.object(alpha_radar, 'candidate_preflight', return_value=[]), patch.object(alpha_radar, 'qualified', return_value=True):
                self.assertEqual(alpha_radar.reusable_fresh_candidate(root / 'candidates.jsonl', root / 'private/reviews.jsonl'), unrelated)

    def test_malformed_spending_marker_cannot_disappear_into_other_order_states(self):
        import earnings_spending
        base = earnings_spending.rejection({'symbol': 'DELL', 'dossier_hash': 'exact'}, 'precheck', autotrader.utcnow())
        for changes in ({'status': 'proposed'}, {'reason': 'stale_quote'}, {'stage': 'invented'}, {'earnings_setup_key': 'broken'}):
            with self.subTest(changes=changes), tempfile.TemporaryDirectory() as td:
                root = Path(td)
                ledger = root / 'order_ledger.jsonl'
                ledger.write_text(json.dumps({**base, **changes}) + '\n')
                with self.assertRaises(earnings_spending.SpendingStateError):
                    earnings_spending.is_spent({'dossier_hash': 'exact'}, ledger)

    def test_precheck_spends_before_review_and_both_selectors_skip(self):
        import alpha_radar
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            snap['earnings_sessions_away'] = 1
            _setup_root(root, snap)
            candidate = json.loads((root / 'candidates.jsonl').read_text())
            with patch('autotrader.independent_reviews') as reviews:
                code, out, calls = _run_in_root(root, snap)
                self.assertEqual(code, 2)
                self.assertIn('near_term_earnings', out)
                self.assertEqual(calls, ['snapshot'])
                reviews.assert_not_called()
            ledger = root / 'order_ledger.jsonl'
            self.assertTrue(ledger.exists(), 'precheck must durably spend the dossier')
            rows = autotrader.read_jsonl(ledger, strict=True)
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]['status'], 'rejected')
            self.assertEqual(rows[0]['reason'], 'near_term_earnings')
            self.assertEqual(rows[0]['stage'], 'precheck')
            self.assertEqual(rows[0]['dossier_hash'], candidate['dossier_hash'])
            from public_dashboard import sanitize_ledger_row
            public = sanitize_ledger_row(rows[0])
            for field in ('earnings_setup_key', 'dossier_hash', 'candidate_id'):
                self.assertNotIn(field, public)
            for field in ('client_order_id', 'parent_client_order_id', 'quantity', 'reviews'):
                self.assertNotIn(field, rows[0])
            self.assertEqual(autotrader._daily_order_count(ledger), 0)
            self.assertFalse((root / 'trade_journal.jsonl').exists())
            self.assertFalse((root / 'private/reviews.jsonl').exists())
            with patch('autotrader.independent_reviews') as reviews:
                code, out, calls = _run_in_root(root, snap)
                self.assertEqual(code, 0)
                self.assertIn('skipped near_term_earnings', out)
                self.assertEqual(calls, [])
                reviews.assert_not_called()
            with patch.object(alpha_radar, 'candidate_preflight', return_value=[]), patch.object(alpha_radar, 'qualified', return_value=True):
                self.assertIsNone(alpha_radar.reusable_fresh_candidate(root / 'candidates.jsonl', root / 'private/reviews.jsonl'))


class RunPrecheckDiagnosticsTests(unittest.TestCase):
    def test_validation_stage_seams_preserve_precheck_and_scope_order(self):
        proposal = {"symbol": "DELL", "confidence": 0.2}
        plan = {"symbol": "DELL", "confidence": 0.8}
        snapshot, cfg, baseline = {"quote": {}}, {"enabled": False}, {"DELL"}
        with patch("autotrader.validate_order_with_details", return_value=(["cash"], {"cash": {"measured": 1}})) as validate:
            pre = autotrader.pre_review_validation(proposal, snapshot, cfg, 1, 20.0, baseline)
            self.assertEqual(pre, (["cash"], {"cash": {"measured": 1}}))
            self.assertEqual(validate.call_args.args, ({**proposal, "confidence": 1.0}, snapshot, cfg, 1, 20.0, baseline))
            post = autotrader.post_review_validation(plan, snapshot, cfg, 2, 21.0, baseline, ["scope"])
            self.assertEqual(post, (["scope", "cash"], {"cash": {"measured": 1}}))
            self.assertEqual(validate.call_args.args, (plan, snapshot, cfg, 2, 21.0, baseline))
            fresh = autotrader.broker_review_validation(plan, snapshot, cfg, 2, 22.0, baseline, ["fresh_scope"])
            self.assertEqual(fresh, (["fresh_scope", "cash"], {"cash": {"measured": 1}}))
            self.assertEqual(validate.call_args.args, (plan, snapshot, cfg, 2, 22.0, baseline))

    def test_precheck_block_writes_private_diagnostics_rows(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot(quote=_quote(98.0, 105.0))  # wide spread + earnings far enough
            _setup_root(root, snap)
            snap["earnings_sessions_away"] = 9
            code, out, _ = _run_in_root(root, snap)
            self.assertEqual(code, 2)
            self.assertIn("spread_too_wide", out)
            path = root / "private" / "blocker_diagnostics.jsonl"
            self.assertTrue(path.exists())
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            reasons = {row["reason"] for row in rows}
            self.assertIn("spread_too_wide", reasons)
            spread_row = next(r for r in rows if r["reason"] == "spread_too_wide")
            self.assertEqual(spread_row["stage"], "precheck")
            self.assertEqual(spread_row["symbol"], "DELL")
            self.assertEqual(spread_row["action"], "BUY")
            self.assertIn("timestamp", spread_row)

            self.assertGreater(spread_row["measured"]["spread_bps"], 0)
            self.assertEqual(spread_row["threshold"]["max_spread_bps"], 600)

    def test_one_row_per_reason(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot(quote=_quote(98.0, 105.0))
            snap["earnings_sessions_away"] = 1  # adds near_term_earnings blocker
            _setup_root(root, snap)
            code, out, _ = _run_in_root(root, snap)
            self.assertEqual(code, 2)
            rows = [json.loads(line) for line in (root / "private" / "blocker_diagnostics.jsonl").read_text().splitlines()]
            reasons = [row["reason"] for row in rows]
            self.assertIn("spread_too_wide", reasons)
            self.assertIn("near_term_earnings", reasons)
            self.assertEqual(len(reasons), len(set(reasons)))

    def test_broker_review_block_tagged_stage(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            good = _snapshot()
            _setup_root(root, good)
            fresh = _snapshot(cash=1.0)  # cash evaporates between precheck and placement
            proposal, errors = autotrader.build_canonical_proposal(
                json.loads((root / "candidates.jsonl").read_text().splitlines()[0]),
                autotrader.authoritative_bundle({}, good, good["captured_at"])["broker_snapshot"],
                _cfg(), 0.0)
            self.assertEqual(errors, [])
            reviews = [
                {"proposal_hash": proposal["proposal_hash"], "decision": "APPROVE", "fatal_flags": [],
                 "reason_codes": [], "component_scores": {k: 5 for k in autotrader.RUBRIC_WEIGHTS["short_1_5"]}},
            ] * 2
            with patch("autotrader.independent_reviews", return_value=reviews), patch(
                "autotrader.record_shadow_decision"
            ):
                code, out, _ = _run_in_root(root, good, review_snapshot=fresh)
            self.assertEqual(code, 2)
            self.assertIn("insufficient_cash", out)
            rows = [json.loads(line) for line in (root / "private" / "blocker_diagnostics.jsonl").read_text().splitlines()]
            row = next(r for r in rows if r["reason"] == "insufficient_cash")
            self.assertEqual(row["stage"], "broker_review")

    def test_passing_cycle_writes_no_diagnostics(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            _setup_root(root, snap)
            reviews = [
                {"proposal_hash": "MATCH", "decision": "APPROVE", "fatal_flags": [],
                 "reason_codes": [], "component_scores": {k: 4 for k in autotrader.RUBRIC_WEIGHTS["short_1_5"]}},
            ] * 2
            placed_payload = {}
            def fake_bridge(op, payload=None):
                if op == "snapshot":
                    return snap
                if op == "review":
                    return snap
                if op == "place":
                    placed_payload.update(payload)
                    return {"status": "accepted"}
                if op == "reconcile":
                    order = placed_payload["order"]
                    return {
                        "client_order_id": payload["client_order_id"], "status": "accepted",
                        "symbol": order["symbol"], "side": order["action"].lower(),
                        "qty": str(order["quantity"]), "type": "limit", "order_class": "bracket",
                    }
                raise AssertionError(op)
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=fake_bridge
            ), patch("autotrader.load_baseline_symbols", return_value=set()), patch(
                "autotrader.reconcile_managed_protection", return_value=[]
            ), patch(
                "autotrader.independent_reviews", return_value=reviews
            ):
                out = io.StringIO()
                with contextlib.redirect_stdout(out):
                    # proposal hash must match reviews; build it the same way run does
                    proposal, errors = autotrader.build_canonical_proposal(
                        json.loads((root / "candidates.jsonl").read_text().splitlines()[0]),
                        autotrader.authoritative_bundle({}, snap, snap["captured_at"])["broker_snapshot"],
                        _cfg(), 0.0)
                    self.assertEqual(errors, [])
                    reviews[0]["proposal_hash"] = proposal["proposal_hash"]
                    reviews[1]["proposal_hash"] = proposal["proposal_hash"]
                    code = autotrader.run(autotrader.argparse.Namespace(
                        dry_run_fixture=False, live_dry_run=False))
            self.assertEqual(code, 0)
            self.assertRegex(out.getvalue(), r"^ORDER placing BUY [1-9]\d* [A-Z]{1,6} LIMIT \d+\.\d{2} STOP \d+\.\d{2} TARGET \d+\.\d{2} PAPER\n$")
            self.assertNotIn(placed_payload.get("client_order_id", "private-reference"), out.getvalue())
            markers = [json.loads(line) for line in (root / "private" / "order_notifications.jsonl").read_text().splitlines()]
            self.assertEqual(len(markers), 2)
            self.assertEqual([row["state"] for row in markers], ["prepared", "emitted"])
            self.assertTrue(all("client_order_id" not in row for row in markers))
            self.assertFalse((root / "private" / "blocker_diagnostics.jsonl").exists())

    def test_notification_failure_does_not_block_place(self):
        self._assert_notification_does_not_block_place(return_value=False)

    def test_notification_exception_does_not_block_place(self):
        self._assert_notification_does_not_block_place(side_effect=OSError("pipe"))

    def _assert_notification_does_not_block_place(self, **notification_fault):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            _setup_root(root, snap)
            proposal, errors = autotrader.build_canonical_proposal(
                json.loads((root / "candidates.jsonl").read_text().splitlines()[0]),
                autotrader.authoritative_bundle({}, snap, snap["captured_at"])[
                    "broker_snapshot"],
                _cfg(), 0.0)
            self.assertEqual(errors, [])
            reviews = [{
                "proposal_hash": proposal["proposal_hash"], "decision": "APPROVE",
                "fatal_flags": [], "reason_codes": [],
                "component_scores": {k: 4 for k in autotrader.RUBRIC_WEIGHTS["short_1_5"]},
            }] * 2
            place_calls = []
            def bridge(op, payload=None):
                if op in {"snapshot", "review"}: return snap
                if op == "place":
                    place_calls.append(payload)
                    return {"status": "accepted"}
                if op == "reconcile":
                    order = payload["order"] if payload and "order" in payload else (place_calls[-1]["order"] if place_calls else None)
                    return {
                        "client_order_id": payload["client_order_id"], "status": "accepted",
                        "symbol": order["symbol"], "side": order["action"].lower(),
                        "qty": str(order["quantity"]), "type": "limit", "order_class": "bracket",
                    }
                raise AssertionError(op)
            out = io.StringIO()
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=bridge
            ), patch("autotrader.load_baseline_symbols", return_value=set()), patch(
                "autotrader.reconcile_managed_protection", return_value=[]
            ), patch(
                "autotrader.independent_reviews", return_value=reviews
            ), patch(
                "autotrader.emit_placing_notification_once", **notification_fault
            ), contextlib.redirect_stdout(out):
                code = autotrader.run(autotrader.argparse.Namespace(
                    dry_run_fixture=False, live_dry_run=False))
            self.assertEqual(code, 0)
            self.assertEqual(len(place_calls), 1)
            self.assertEqual(out.getvalue(), "")
            ledger = [json.loads(line) for line in (root / "order_ledger.jsonl").read_text().splitlines()]
            self.assertIn("placed", {row["status"] for row in ledger})

    def test_ambiguous_place_failure_is_reconciled_without_resubmission(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot()
            _setup_root(root, snap)
            proposal, errors = autotrader.build_canonical_proposal(
                json.loads((root / "candidates.jsonl").read_text().splitlines()[0]),
                autotrader.authoritative_bundle({}, snap, snap["captured_at"])["broker_snapshot"],
                _cfg(), 0.0)
            self.assertEqual(errors, [])
            reviews = [{
                "proposal_hash": proposal["proposal_hash"], "decision": "APPROVE",
                "fatal_flags": [], "reason_codes": [],
                "component_scores": {k: 4 for k in autotrader.RUBRIC_WEIGHTS["short_1_5"]},
            }] * 2
            first_calls = []
            def first_bridge(op, payload=None):
                first_calls.append(op)
                if op in {"snapshot", "review"}: return snap
                if op == "place": raise RuntimeError("ambiguous transport failure")
                raise AssertionError(op)
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=first_bridge
            ), patch("autotrader.load_baseline_symbols", return_value=set()), patch(
                "autotrader.reconcile_managed_protection", return_value=[]
            ), patch("autotrader.independent_reviews", return_value=reviews), contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(autotrader.run(autotrader.argparse.Namespace(
                    dry_run_fixture=False, live_dry_run=False)), 4)
            ledger = [json.loads(line) for line in (root / "order_ledger.jsonl").read_text().splitlines()]
            self.assertEqual(ledger[-1]["status"], "submission_unknown")
            ref = ledger[-1]["client_order_id"]
            plan = json.loads((root / "private" / "order_intents.jsonl").read_text())["plan"]
            second_calls = []
            def second_bridge(op, payload=None):
                second_calls.append(op)
                self.assertEqual(op, "reconcile")
                return {
                    "client_order_id": ref, "status": "accepted", "symbol": plan["symbol"],
                    "side": plan["action"].lower(), "qty": str(plan["quantity"]),
                    "type": "limit", "order_class": "bracket",
                }
            output = io.StringIO()
            with patch.object(autotrader, "ROOT", root), patch(
                "autotrader._broker_bridge", side_effect=second_bridge
            ), patch("autotrader.reconcile_managed_exits", return_value=[]), patch(
                "autotrader.reconcile_managed_protection", return_value=[]
            ), patch("autotrader.independent_reviews", side_effect=AssertionError("no second review")), patch(
                "autotrader.emit_placing_notification_once", side_effect=AssertionError("no resubmission notice")
            ), contextlib.redirect_stdout(output):
                self.assertEqual(autotrader.run(autotrader.argparse.Namespace(
                    dry_run_fixture=False, live_dry_run=False)), 0)
            self.assertEqual(second_calls, ["reconcile"])
            self.assertEqual(output.getvalue(), "DECISION skipped already_reviewed\n")
            self.assertNotIn("ORDER", output.getvalue())


class DryRunDiagnosticsTests(unittest.TestCase):
    def test_live_dry_run_routes_diagnostics_to_test_artifacts(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            snap = _snapshot(quote=_quote(98.0, 105.0))
            _setup_root(root, snap)
            code, out, _ = _run_in_root(root, snap, live_dry_run=True)
            self.assertEqual(code, 2)
            self.assertIn("spread_too_wide", out)
            self.assertFalse((root / "private" / "blocker_diagnostics.jsonl").exists())
            path = root / "test_artifacts" / "blocker_diagnostics.jsonl"
            self.assertTrue(path.exists())
            rows = [json.loads(line) for line in path.read_text().splitlines()]
            self.assertTrue(any(r["reason"] == "spread_too_wide" for r in rows))


class DashboardProjectionTests(unittest.TestCase):
    def test_dashboard_projects_sanitized_blocker_diagnostics(self):
        import public_dashboard
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            (root / "private").mkdir()
            (root / "private" / "blocker_diagnostics.jsonl").write_text(json.dumps({
                "timestamp": "2026-09-05T14:00:00Z", "stage": "precheck",
                "symbol": "DELL", "action": "BUY", "reason": "spread_too_wide",
                "measured": {"bid": 98.0, "ask": 105.0, "midpoint": 101.5, "spread_bps": 689.66, "quote_feed": "alpaca_iex"},
                "threshold": {"max_spread_bps": 500},
                "secret_field": "should-not-publish", "evidence_id": "abc123", "path": "/opt/data/secret",
            }) + "\n")
            data = public_dashboard.build_data(root)
        diag = data["blocker_diagnostics"]
        self.assertEqual(len(diag), 1)
        row = diag[0]
        self.assertEqual(row["reason"], "spread_too_wide")
        self.assertEqual(row["measured"]["spread_bps"], 689.66)
        self.assertEqual(row["threshold"]["max_spread_bps"], 500)
        for forbidden in ("secret_field", "evidence_id", "path"):
            self.assertNotIn(forbidden, row)
        self.assertIn("blocker_diagnostics", public_dashboard.ACTIVITY_SUMMARIES)
        self.assertTrue(public_dashboard.ACTIVITY_SUMMARIES["blocker_diagnostics"])

    def test_dashboard_tolerates_missing_diagnostics_file(self):
        import public_dashboard
        with tempfile.TemporaryDirectory() as td:
            data = public_dashboard.build_data(Path(td))
        self.assertEqual(data["blocker_diagnostics"], [])


if __name__ == "__main__":
    unittest.main()
