"""Offline contracts for the explicitly opt-in real-source byte probe."""
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest

import test_research_extraction as fixtures

BODY, URL, row = fixtures.BODY, fixtures.URL, fixtures.row

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'scripts/probe_extraction_capacity.py'


class CapacityProbeTests(unittest.TestCase):
    def load_probe(self):
        self.assertTrue(SCRIPT.is_file(), 'bounded count-only probe is missing')
        spec = importlib.util.spec_from_file_location('capacity_probe', SCRIPT)
        assert spec is not None and spec.loader is not None
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_count_only_observation_executes_real_worker_and_final_filter(self):
        probe = self.load_probe()
        fixture = fixtures.DispatcherTests()
        # This owner is a plain TestCase: borrowing an IsolatedAsyncioTestCase's
        # doCleanups without its runner leaks every patch into subsequent modules.
        # Register patch restoration with the actual runner-owned test instead.
        fixture.addCleanup = self.addCleanup
        fixture.setUp()
        text = BODY * 70
        fixture.responses['primary'] = [row(content=text, raw_content=text)]
        with tempfile.TemporaryDirectory() as directory:
            target = Path(directory) / 'counts.json'
            out = probe.observe({'version': 1, 'url': URL, 'timeout_seconds': 30}, target)
            counts = json.loads(target.read_text())
        self.assertEqual(out['status'], 'ok')
        self.assertFalse(counts['source_accepted'])  # Undated synthetic body.
        self.assertEqual(len(counts['routes']), 1)
        self.assertGreater(counts['routes'][0]['raw_envelope_bytes'], 100000)
        self.assertEqual(counts['routes'][0].get('prechange_raw_cap_outcome'), 'output_limit')
        self.assertTrue(counts['routes'][0]['rows'][0]['exact_content_duplicate'])
        self.assertEqual(counts['capture_status'], 'complete')
        self.assertNotIn(BODY[:40], json.dumps(counts))
        self.assertNotIn(URL, json.dumps(counts))
        self.assertTrue(any(x.get('folded_row_indices') == [0] for x in counts['size_checks']))

    def test_failed_cohort_is_joined_to_original_exact_urls(self):
        probe = self.load_probe()
        import hashlib
        urls = [URL, URL + '/other', URL + '/not-failed']
        with tempfile.TemporaryDirectory() as directory:
            cohort = Path(directory)
            (cohort / 'shared-discovery.json').write_text(json.dumps({'candidates': [{'urls': urls}]}))
            for arm in ('prior', 'v2'):
                private = cohort / arm / 'test_artifacts/private'
                private.mkdir(parents=True)
                attempts = [{'run_id': 'fixture',
                             'url_id': hashlib.sha256(('fixture' + url).encode()).hexdigest(),
                             'fallback_result': 'output_limit' if index < 2 else 'success'}
                            for index, url in enumerate(urls)]
                (private / 'source_attempts.jsonl').write_text('\n'.join(map(json.dumps, attempts)))
            self.assertEqual(probe.failed_urls(cohort), urls[:2])
