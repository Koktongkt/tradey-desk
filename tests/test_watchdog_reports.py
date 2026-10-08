import importlib.util
import json
import tempfile
import unittest
from dataclasses import asdict
from pathlib import Path
from test_watchdog_store import observation


class ReportTests(unittest.TestCase):
    def test_public_nested_projection_private_compact_report(self):
        self.assertIsNotNone(importlib.util.find_spec('watchdog.reports'), 'report projections missing')
        from watchdog.reports import public_summary, private_report, render_alert
        report = asdict(observation())
        report['positions'][0]['candidate_id'] = 'SECRET_ID'
        report['portfolio']['account'].update(account_id='SECRET_ID', buying_power='PRIVATE_TOKEN',
            reasons=['raw error https://private.test/?token=PRIVATE_TOKEN'], provenance={'equity':'SECRET_ID'})
        report['portfolio']['strategy'].update(return_kind='total_return', **{'return': '0.002'})
        report['thesis'] = [dict(position_id='p1', symbol='ABC', status='review_required',
            events=[dict(fact='compact', urls=['https://private.test/full?token=PRIVATE_TOKEN'])])]
        report['reasons'] = ['raw error PRIVATE_TOKEN', 'source_coverage_incomplete']
        safe = public_summary(report)
        text = json.dumps(safe)
        for token in ('SECRET_ID', 'PRIVATE_TOKEN', 'private.test', 'provenance', 'candidate_id', 'buying_power'):
            self.assertNotIn(token, text)
        self.assertEqual('10000', safe['strategy']['initial_capital'])
        self.assertEqual('10020', safe['strategy']['marked_equity'])
        self.assertEqual('50000', safe['account']['equity'])
        self.assertIn('source_coverage_incomplete', safe['reasons'])
        private = private_report(report)
        self.assertIn('https://private.test/full?token=PRIVATE_TOKEN', private)
        self.assertIn('shadow', private.lower())
        self.assertNotIn('PRIVATE_TOKEN', render_alert(dict(kind='protection', status='raw PRIVATE_TOKEN', symbol='PRIVATE_TOKEN', severity='critical')))

    def test_unknown_and_malicious_allowlisted_strings_withheld(self):
        from watchdog.reports import public_summary
        report = asdict(observation())
        for target in (report, report['coverage'], report['portfolio']['strategy'], report['portfolio']['account'], report['positions'][0]):
            target['private_url'] = 'https://private.test/SECRET'
            target['reasons'] = ['SECRET', {'code':'SECRET'}]
        report['portfolio']['strategy']['coverage']['status'] = 'https://private.test/SECRET'
        report['portfolio']['strategy']['marked_equity'] = 'SECRET'
        report['portfolio']['account']['at'] = 'SECRET'
        report['positions'][0].update(symbol='<script>SECRET</script>', protection_status='SECRET')
        report['coverage']['status'] = {'raw':'SECRET'}
        text = json.dumps(public_summary(report))
        self.assertNotIn('SECRET', text)
        self.assertNotIn('private.test', text)
        self.assertIsNone(public_summary(report)['strategy']['marked_equity'])

    def test_unknown_ownership_and_shadow_are_not_actual(self):
        from watchdog.reports import public_summary
        report = asdict(observation())
        report['positions'][0]['ownership_status'] = 'unknown'
        report['portfolio']['strategy']['scope'] = 'shadow'
        report['portfolio']['strategy']['return'] = '999'
        safe = public_summary(report)
        self.assertEqual([], safe['positions'])
        self.assertIsNone(safe['strategy']['return'])
        self.assertIsNone(safe['strategy']['marked_equity'])

    def test_real_comparator_labels_and_verified_accounting_exposure(self):
        from watchdog.reports import public_summary
        report = asdict(observation())
        report['portfolio']['strategy'].update(return_kind='total_return', conditional_planned_loss='15',
            positions=[dict(position_id='p1', symbol='ABC', market_value='210', weight_vs_sleeve_equity='0.0209')])
        report['portfolio']['benchmark'] = dict(return_kind='price_return_only', benchmark_return='0.01',
            excess_total_return='SECRET', excess_price_comparator='-0.008', coverage={'status':'complete'})
        safe = public_summary(report)
        self.assertEqual('price_return_only', safe['benchmark']['return_kind'])
        self.assertIsNone(safe['benchmark']['excess_total_return'])
        self.assertEqual('210', safe['positions'][0]['market_value'])
        self.assertEqual('15', safe['strategy']['conditional_planned_loss'])

    def test_atomic_private_pair_and_public_install_failure(self):
        from watchdog import reports
        self.assertTrue(hasattr(reports, 'install_reports'), 'atomic report install missing')
        from watchdog.store import commit_observation
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'test_artifacts'
            db = root / 'private/watchdog/monitoring.sqlite3'
            commit_observation(db, observation())
            reports.install_reports(db)
            private = db.parent
            before = ((private/'latest.json').read_bytes(), (private/'latest.md').read_bytes(),
                      (root/'public/watchdog.json').read_bytes())
            commit_observation(db, observation('r2', '2026-10-08T20:30:00Z', 'covered'))
            with patch('watchdog.reports.private_report', side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError):
                    reports.install_reports(db)
            self.assertEqual(before, ((private/'latest.json').read_bytes(), (private/'latest.md').read_bytes(),
                                    (root/'public/watchdog.json').read_bytes()))
            reports.install_reports(db)
            self.assertEqual('r2', json.loads((private/'latest.json').read_text())['run_id'])
            public_text = (root/'public/watchdog.json').read_text()
            self.assertNotIn('position_id', public_text)
            self.assertIn('Primary managed strategy', public_text)

    def test_built_and_rendered_fixture_artifacts_are_private_free(self):
        import public_dashboard
        import subprocess
        import shutil
        from unittest.mock import patch
        from watchdog.store import commit_observation
        from watchdog.reports import install_reports
        node = shutil.which('node')
        if not node:
            self.fail('node required for offline dashboard renderer verification')
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'test_artifacts'
            db = root/'private/watchdog/monitoring.sqlite3'
            o = observation()
            o.positions[0]['candidate_id'] = 'PRIVATE_CANARY'
            o.portfolio['account']['account_id'] = 'PRIVATE_CANARY'
            o.thesis = [dict(position_id='p1', symbol='ABC', status='baseline_incomplete', baseline={
                'summary':'PRIVATE_CANARY', 'version':'v'}, baseline_version='v')]
            commit_observation(db, o)
            install_reports(db)
            with patch('public_dashboard.rows', return_value=[]):
                data = public_dashboard.build_data(root)
            html = public_dashboard.html_template()
            public = root/'public'
            (public/'dashboard.json').write_text(json.dumps(data))
            (public/'index.html').write_text(html)
            script = html.split('<script>')[1].split('</script>')[0]
            # Exercise actual dashboard JavaScript offline, not a reimplementation.
            harness = """const fs=require('fs'),vm=require('vm');
const data=JSON.parse(fs.readFileSync(process.argv[1],'utf8'));
const els=new Map(); const doc={querySelector(k){if(!els.has(k))els.set(k,{innerHTML:'',value:'all',addEventListener(){},insertAdjacentHTML(){}});return els.get(k)}};
const code=fs.readFileSync(process.argv[2],'utf8');
vm.runInNewContext(code,{document:doc,fetch:()=>Promise.resolve({ok:true,json:()=>Promise.resolve(data)}),console});
setImmediate(()=>fs.writeFileSync(process.argv[3],doc.querySelector('#app').innerHTML));
"""
            script_path = root/'dashboard-script.js'
            script_path.write_text(script)
            rendered = public/'rendered.html'
            result = subprocess.run([node, '-e', harness, str(public/'dashboard.json'), str(script_path), str(rendered)],
                capture_output=True, text=True, timeout=10)
            self.assertEqual(0, result.returncode, result.stderr)
            for path in public.iterdir():
                self.assertNotIn('PRIVATE_CANARY', path.read_text(), str(path))
            page = rendered.read_text()
            self.assertIn('Primary managed strategy', page)
            self.assertIn('$10,020', page)
            self.assertIn('$50,000', page)
            self.assertIn('not actual protected-trade returns', page)

    def test_unowned_thesis_symbol_and_wrong_capital_withheld(self):
        from watchdog.reports import public_summary
        report = asdict(observation())
        report['thesis'] = [dict(position_id='p1', symbol='XYZ', status='review_required')]
        report['portfolio']['strategy']['initial_capital'] = '20000'
        safe = public_summary(report)
        self.assertEqual([], safe['thesis'])
        self.assertIsNone(safe['strategy']['marked_equity'])

    def test_install_interrupt_at_pointer_keeps_previous_pair(self):
        from watchdog.store import commit_observation, pending_alerts
        from watchdog.reports import install_reports
        from unittest.mock import patch
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'test_artifacts'
            db = root/'private/watchdog/monitoring.sqlite3'
            commit_observation(db, observation())
            install_reports(db)
            before = [(db.parent/name).read_bytes() for name in ('latest.json','latest.md')]
            pending = pending_alerts(db)
            commit_observation(db, observation('r2', '2026-10-08T20:30:00Z'))
            real = os.replace
            def interrupt(source, dest):
                if Path(dest).name == 'current':
                    raise OSError('injected install interruption')
                return real(source, dest)
            with patch('os.replace', side_effect=interrupt):
                with self.assertRaises(OSError):
                    install_reports(db)
            self.assertEqual(before, [(db.parent/name).read_bytes() for name in ('latest.json','latest.md')])
            self.assertTrue(all(row in pending_alerts(db) for row in pending))
            install_reports(db)
            self.assertEqual('r2', json.loads((db.parent/'latest.json').read_text())['run_id'])

    def test_generations_bounded_and_output_symlinks_rejected(self):
        from watchdog.store import commit_observation
        from watchdog.reports import install_reports
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'test_artifacts'
            db = root/'private/watchdog/monitoring.sqlite3'
            commit_observation(db, observation())
            for _ in range(5):
                install_reports(db)
            with self.subTest('bounded'):
                self.assertLessEqual(len(list((db.parent/'.reports').glob('generation-*'))), 3)
            import shutil
            shutil.rmtree(root/'public')
            outside = Path(tmp)/'outside'
            outside.mkdir()
            (root/'public').symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                install_reports(db)
            self.assertEqual([], list(outside.iterdir()))

    def test_evidence_alert_render_keeps_typed_effect(self):
        from watchdog.reports import render_alert
        self.assertIn('potential-break', render_alert(dict(kind='evidence', status='potential-break', severity='critical', symbol='ABC')))

    def test_public_install_failure_is_atomic_and_retryable_after_private_publish(self):
        from watchdog.store import commit_observation, pending_alerts
        from watchdog.reports import install_reports
        from unittest.mock import patch
        import os
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)/'test_artifacts'
            db = root/'private/watchdog/monitoring.sqlite3'
            commit_observation(db, observation())
            install_reports(db)
            before = (root/'public/watchdog.json').read_bytes()
            commit_observation(db, observation('r2', '2026-10-08T20:30:00Z', 'covered'))
            pending = pending_alerts(db)
            replace = os.replace
            def interrupt(source, dest):
                if Path(dest).name == 'watchdog.json':
                    raise OSError('public install interrupted')
                return replace(source, dest)
            with patch('os.replace', side_effect=interrupt):
                with self.assertRaises(OSError):
                    install_reports(db)
            self.assertEqual(before, (root/'public/watchdog.json').read_bytes())
            self.assertEqual('r2', json.loads((db.parent/'latest.json').read_text())['run_id'])
            self.assertEqual(pending, pending_alerts(db))
            install_reports(db)
            self.assertEqual('2026-10-08', json.loads((root/'public/watchdog.json').read_text())['session_date'])

    def test_private_injection_into_every_nested_object_is_removed(self):
        from watchdog.reports import public_summary
        report = asdict(observation())
        report['portfolio']['strategy']['positions'] = [dict(position_id='p1', symbol='ABC', market_value='210')]
        report['portfolio']['benchmark'] = dict(return_kind='price_return_only', coverage={'status':'complete'}, observations=[{'date':'2026-10-07','benchmark_equity':'10001'}])
        report['thesis'] = [dict(position_id='p1', symbol='ABC', status='review_required', coverage_status='complete',
            coverage={'issuer':{'status':'complete'}}, events=[dict(fact='compact', urls=['https://private.test/PRIVATE_NESTED_CANARY'])])]
        report['attribution'] = dict(actual={'realized_pnl':'10'}, research=[{'forward_return':'0.1'}], shadow=[{'return':'0.2'}])
        def inject(value):
            if isinstance(value, dict):
                for item in list(value.values()):
                    inject(item)
                for key in ('account_id','broker_order_id','private_url','raw_exception','prompt','token','filesystem_path'):
                    value[key] = 'PRIVATE_NESTED_CANARY https://private.test/trace'
                value['reasons'] = ['PRIVATE_NESTED_CANARY raw exception https://private.test/trace']
            elif isinstance(value, list):
                for item in value:
                    inject(item)
        inject(report)
        text = json.dumps(public_summary(report))
        for value in ('PRIVATE_NESTED_CANARY', 'private.test', 'raw exception', 'filesystem_path', 'broker_order_id'):
            self.assertNotIn(value, text)
        self.assertIn('10020', text)
        self.assertIn('210', text)

    def test_public_summary_malformed_identity_is_safe(self):
        from watchdog.reports import public_summary
        report = asdict(observation())
        report['positions'][0]['position_id'] = ['SECRET']
        self.assertNotIn('SECRET', json.dumps(public_summary(report)))

    def test_dashboard_missing_and_incomplete_store_is_read_only(self):
        import public_dashboard
        from unittest.mock import patch
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'test_artifacts'
            root.mkdir()
            with patch('public_dashboard.rows', return_value=[]):
                data = public_dashboard.build_data(root)
            self.assertIn('watchdog', data)
            self.assertFalse(data['watchdog']['available'])
            self.assertEqual([], list(root.iterdir()))
            path = root / 'private/watchdog/monitoring.sqlite3'
            path.parent.mkdir(parents=True)
            path.write_bytes(b'incomplete monitoring file')
            before = path.read_bytes()
            with patch('public_dashboard.rows', return_value=[]):
                data = public_dashboard.build_data(root)
            self.assertFalse(data['watchdog']['available'])
            self.assertEqual(before, path.read_bytes())
            html = public_dashboard.html_template()
            self.assertIn('Primary managed strategy', html)
            self.assertIn('Secondary full account', html)
            self.assertIn('not actual protected-trade returns', html)


if __name__ == '__main__':
    unittest.main()
