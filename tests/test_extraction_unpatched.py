"""Offline safety and real isolated-runtime compatibility checks for the probe."""
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProbeTests(unittest.TestCase):
    def probe(self):
        path = ROOT / 'scripts/probe_project_extraction.py'
        self.assertTrue(path.is_file(), 'bounded network-only probe is missing')
        spec = importlib.util.spec_from_file_location('extraction_probe', path)
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_duplicate_urls_rejected(self):
        probe = self.probe()
        with self.assertRaises(ValueError):
            probe.validate_cohort(['https://example.com/a'] * 2)
        for value in ([], ['file:///private'], ['https://example.com'] * 13):
            with self.assertRaises(ValueError):
                probe.validate_cohort(value)

    def test_probe_never_calls_trading(self):
        import alpha_radar
        import autotrader
        from unittest.mock import patch
        probe = self.probe()
        body = 'Company revenue increased following the announced transaction. ' * 20
        result = {'version': 1, 'status': 'ok', 'page': {
            'url': 'https://example.com/a', 'title': 'Release', 'text': body,
        }}
        with patch.object(alpha_radar, 'record_source_verification_diagnostic', side_effect=AssertionError('journal')), \
             patch.object(autotrader, 'journal_confirmed_fill', side_effect=AssertionError('execution')), \
             patch.object(autotrader, 'reconcile_pending_orders', side_effect=AssertionError('orders')):
            report = probe.run_probe(['https://example.com/a'], 'worker',
                                     runner=lambda *args: (result, {'attempts': [], 'module_paths': {}}))
        self.assertEqual(report['accepted'] + report['rejected'], 1)
        self.assertEqual(report['rows'][0]['reason'], 'source_freshness_unknown')
        self.assertGreaterEqual(report['rows'][0]['elapsed_seconds'], 0)
        self.assertIn('attempts', report['rows'][0])

    def test_unobserved_success_does_not_claim_zero_network_requests(self):
        probe = self.probe()
        result = {'version': 1, 'status': 'ok', 'page': {
            'url': 'https://example.com/a', 'title': 'Release', 'text': 'Company release. ' * 100}}
        report = probe.run_probe(['https://example.com/a'], 'worker',
            runner=lambda *args: (result, {'attempts': [], 'baseline': True}))
        self.assertIsNone(report['request_count'])
        self.assertFalse(report['rows'][0]['request_count_complete'])

    def test_private_output_boundary(self):
        probe = self.probe()
        with self.assertRaises(ValueError):
            probe.write_private(ROOT / 'outside-probe.json', {})
        import tempfile
        with tempfile.TemporaryDirectory(dir=probe.ARTIFACTS) as directory:
            target = Path(directory) / 'detail.json'
            probe.write_private(target, {'private': True})
            self.assertEqual(target.stat().st_mode & 0o777, 0o600)

    def test_imports_from_selected_unpatched_root(self):
        import os
        import runtime_paths
        probe = self.probe()
        source = Path(os.environ.get('TRADEY_UNPATCHED_ROOT',
            '/home/hermes/.hermes/cache/scratch/project-extraction-unpatched'))
        self.assertTrue(source.is_dir(), 'explicit unpatched checkout required')
        with __import__('unittest.mock', fromlist=['patch']).patch.dict(os.environ, {'HERMES_SOURCE_ROOT': str(source)}):
            python, selected = runtime_paths.hermes_runtime()
            self.assertEqual(selected.resolve(), source.resolve())
            for mode in ('worker', 'focused'):
                with self.subTest(mode=mode):
                    result, detail = probe.run_source('http://127.0.0.1/probe', mode)
                    self.assertEqual(result['status'], 'error')
                    self.assertEqual(detail['source_sha'], 'd923a5eb487a17c0a68801bba9ef0f56c81040a8')
                    self.assertFalse(detail['patched_publication_module'])
                    self.assertEqual(detail['cache_calls'], 0)
                    self.assertTrue(detail['module_paths'])
                    for path in detail['module_paths'].values():
                        self.assertTrue(Path(path).is_relative_to(source))
                    self.assertEqual(detail['entrypoint'], mode)


if __name__ == '__main__':
    unittest.main()
