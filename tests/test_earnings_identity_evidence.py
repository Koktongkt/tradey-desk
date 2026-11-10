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


if __name__ == '__main__': unittest.main()
