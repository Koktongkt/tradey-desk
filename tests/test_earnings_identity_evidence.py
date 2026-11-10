"""Evidence-readiness contracts; retained real captures are source-only fixtures."""
import hashlib
import html
import json
import os
from pathlib import Path
import unittest

import opportunity_identity as identity
from retained_article import retain_article

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT/'test_artifacts'/'identity_handoff'
PERIODIC_URL = 'https://www.sec.gov/Archives/edgar/data/1446847/000110465926123319/irwd-20260930x10q.htm'
COVER_URL = 'https://www.sec.gov/Archives/edgar/data/1420520/000168316826008161/atomera_8k.htm'
EXHIBIT_URL = COVER_URL.replace('atomera_8k.htm', 'atomera_ex9901.htm')


def original(name):
    path = FIXTURES/name
    if not path.exists():
        raise unittest.SkipTest('source-only identity fixture not provisioned: '+name)
    return path.read_bytes()


def retained(url):
    for path in FIXTURES.glob('*.json'):
        value = json.loads(path.read_text())
        if isinstance(value, dict) and value.get('url') == url:
            return value
    raise unittest.SkipTest('source-only retained identity fixture not provisioned')


class EvidenceReadinessTests(unittest.TestCase):
    def test_flattened_filing_cannot_bootstrap_identity(self):
        page = retain_article({'url':PERIODIC_URL, 'title':'Results', 'text':'Readable quarterly report'},
                              'Readable quarterly report')
        self.assertEqual(identity.resolve_event('IRWD', [page], known_resolutions=()).status, 'unknown')

    def test_authentic_periodic_source_has_explicit_fiscal_facts(self):
        raw = original('irwd-original.html')
        self.assertEqual(hashlib.sha256(raw).hexdigest(),
                         '4ccde4d55477d895a35a06c8eb2f7131ed4f695e3b3e7988c1a62b7cce0e26af')
        parser = identity._Cover(); parser.feed(raw.decode('utf-8')); parser.close()
        self.assertFalse(parser.bad_structure)
        facts = [f for f in parser.facts.values() if f.get('dei:TradingSymbol') == ['IRWD']]
        self.assertEqual(len(facts), 1)
        self.assertEqual(facts[0]['dei:DocumentFiscalPeriodFocus'], ['Q3'])
        self.assertEqual(facts[0]['dei:DocumentFiscalYearFocus'], ['2026'])
        self.assertEqual(facts[0]['dei:EntityCentralIndexKey'], ['0001446847'])
        # This is authentic formatted source text, not a manufactured ISO cover.
        self.assertEqual(facts[0]['dei:DocumentPeriodEndDate'], ['September 30, 2026'])

    def test_authenticated_results_source_has_literal_exhibit_link(self):
        cover = retained(COVER_URL); exhibit = retained(EXHIBIT_URL)
        self.assertEqual(hashlib.sha256(cover['text'].encode()).hexdigest(), cover['sha256'])
        self.assertEqual(hashlib.sha256(exhibit['text'].encode()).hexdigest(), exhibit['sha256'])
        from html.parser import HTMLParser
        class Links(HTMLParser):
            def __init__(self): super().__init__(); self.links=[]
            def handle_starttag(self, tag, attrs):
                if tag == 'a': self.links.extend(v for k,v in attrs if k == 'href')
        parser=Links(); parser.feed(cover['text'])
        from urllib.parse import urljoin
        self.assertIn(EXHIBIT_URL, [urljoin(COVER_URL, link) for link in parser.links])
        p=identity._Cover(); p.feed(cover['text']); p.close()
        subjects=[f for f in p.facts.values() if f.get('dei:TradingSymbol') == ['ATOM']]
        self.assertEqual(subjects[0]['dei:EntityCentralIndexKey'], ['0001420520'])
        self.assertEqual(subjects[0]['dei:DocumentType'], ['8-K'])

    def test_actual_oversize_transport_did_not_create_cropped_fixture(self):
        receipt=FIXTURES/'sbac-acquisition.json'
        if not receipt.exists(): self.skipTest('source-only capacity receipt not provisioned')
        value=json.loads(receipt.read_text())
        self.assertEqual(value['reason'], 'source_capacity')
        self.assertFalse((FIXTURES/'sbac-original.html').exists())


class IdentityCaptureTests(unittest.TestCase):
    def api(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('earnings_identity_evidence'),
                             'identity capture contract is not implemented')
        import earnings_identity_evidence
        return earnings_identity_evidence

    def capture(self, raw=b'<html><body>Complete source</body></html>'):
        return self.api().capture_identity_source(PERIODIC_URL, raw,
            returned_url=PERIODIC_URL, content_type='text/html')

    def test_complete_wire_bytes_round_trip_without_article_limit(self):
        api=self.api(); raw=original('irwd-original.html'); capture=self.capture(raw)
        self.assertTrue(api.validate_identity_capture(capture))
        self.assertEqual(api.identity_source_bytes(capture), raw)
        self.assertEqual(capture.source_sha256, '4ccde4d55477d895a35a06c8eb2f7131ed4f695e3b3e7988c1a62b7cce0e26af')
        self.assertGreater(len(capture.canonical), 85000)
        self.assertLessEqual(len(capture.canonical), 3000000)
        self.assertFalse(api.validate_identity_capture(json.loads(capture.canonical)))

    def test_capture_rejects_capacity_encoding_and_locator_mismatch(self):
        api=self.api()
        for raw in [b'x'*2000001, b'\xff', b'']:
            with self.subTest(size=len(raw)), self.assertRaises(ValueError): self.capture(raw)
        for returned in [EXHIBIT_URL, PERIODIC_URL+'?changed=1', 'https://attacker.test/report.htm']:
            with self.subTest(returned=returned), self.assertRaises(ValueError):
                api.capture_identity_source(PERIODIC_URL, b'<html></html>',returned_url=returned,content_type='text/html')
        with self.assertRaises(ValueError):
            api.capture_identity_source(PERIODIC_URL,b'<html></html>',returned_url=PERIODIC_URL,content_type='text/plain')

    def test_capture_metadata_and_duplicate_json_tampering_rejected(self):
        from dataclasses import replace
        api=self.api(); capture=self.capture()
        value=json.loads(capture.canonical);value['url']=EXHIBIT_URL
        for raw in [json.dumps(value).encode(), capture.canonical[:-1]+b',"complete":true}', b'{"complete":NaN}']:
            changed=replace(capture, canonical=raw)
            self.assertFalse(api.validate_identity_capture(changed))
            self.assertIsNone(api.identity_source_bytes(changed))

    def test_retention_is_private_idempotent_and_rejects_symlink_or_collision(self):
        api=self.api()
        self.assertTrue(hasattr(api,'retain_identity_captures'), 'durable identity retention is missing')
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);capture=self.capture()
            api.retain_identity_captures(root,(capture,))
            target=root/capture.retained_ref
            self.assertEqual(target.read_bytes(),capture.canonical)
            self.assertEqual(target.stat().st_mode&0o777,0o600)
            self.assertEqual(target.parent.stat().st_mode&0o777,0o700)
            before=target.stat().st_mtime_ns
            api.retain_identity_captures(root,(capture,))
            self.assertEqual(target.stat().st_mtime_ns,before)
            target.write_bytes(b'changed')
            with self.assertRaises((ValueError,OSError)): api.retain_identity_captures(root,(capture,))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);outside=root/'outside';outside.mkdir()
            (root/'private').symlink_to(outside,target_is_directory=True)
            with self.assertRaises(OSError): api.retain_identity_captures(root,(self.capture(),))
            self.assertFalse((outside/'opportunity_evidence').exists())

    def test_actual_provider_truncation_footer_is_not_complete_evidence(self):
        value=retain_article({'url':PERIODIC_URL,'title':'Report','text':'Readable report'},
            'Readable report\nThis content has been truncated to stay below 50000 characters')
        self.assertEqual(value.get('_capture_status'), 'incomplete')


if __name__ == '__main__': unittest.main()
