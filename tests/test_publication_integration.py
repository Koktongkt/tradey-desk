"""Offline integration; all constructed publisher-style examples are synthetic."""
import datetime as dt
import io
import hashlib
import copy
import json
from pathlib import Path
import tempfile
import subprocess
from time import monotonic
import unittest
from unittest.mock import patch

import alpha_radar as radar
import publication_observation as publication

NOW = dt.datetime(2026, 10, 21, 16, 30, tzinfo=dt.timezone.utc)
URL = 'https://news.example/story'
BODY = 'The company reported stronger revenue and raised its annual outlook. ' * 12


def raw(text, url=URL):
    return {'url': url, 'title': 'Quarterly results', 'text': text}


def envelope(text, url=URL):
    return {'version': 1, 'status': 'ok', 'page': raw(text, url)}


class PublicationIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='publication-task2-')
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.root_patch = patch.object(radar, 'ROOT', self.home)
        self.root_patch.start()
        self.addCleanup(self.root_patch.stop)

    def dated_pages(self):
        text = '<meta property="article:published_time" content="2026-10-21"><article>' + BODY + '</article>'
        return [radar.validate_structured_page(url, envelope(text, url))
                for url in [URL, 'https://independent.example/article']]

    def synthesized(self):
        candidate = {'symbol':'ABC', 'sources':[{'url':page['url'], 'publication_precision':'second', 'publication_basis':'forged'} for page in self.dated_pages()],
                     'instrument_type':'cash_equity', 'setup_type':'event_momentum', 'planned_exit_at':(dt.datetime.now(dt.timezone.utc)+dt.timedelta(days=3)).isoformat(),
                     'horizon_rationale':'Dated guidance catalyst', 'earnings_event_at':'2027-02-01T12:00:00Z', 'earnings_source':'trusted_fixture'}
        with patch.object(radar, 'synthesis_command', return_value=['offline']), patch.object(radar.subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, json.dumps(candidate), '')), patch.object(radar, 'resolve_candidate_earnings', side_effect=lambda c, **kw:c), patch.object(radar, 'synchronized_completed_close_prices', return_value={'price':20,'spy_price':600}):
            return radar.synthesize_candidate({'max_position_usd':100}, {'symbol':'ABC'}, self.dated_pages(), monotonic()+120)

    def test_day_observation_survives_receipt_synthesis_and_review_projection(self):
        import autotrader
        candidate = self.synthesized()
        cfg = {'min_price_usd':5,'max_position_usd':100,'earnings_blackout_sessions':2}
        # Shared intake runs the real receipt and distinct-publisher gates;
        # only earnings/calendar predicates are isolated from live enrichment.
        with patch.object(radar, 'earnings_intake_blocker', return_value=None):
            candidate = radar.prepare_candidate(candidate, cfg)
        self.assertTrue(radar.verify_sources(candidate))
        bundle = autotrader.build_review_bundle(candidate, {'captured_at':NOW.isoformat()}, {})
        for source in bundle['evidence']['candidate']['sources']:
            self.assertEqual(source['publication_precision'], 'day')
            self.assertEqual(source['publication_basis'], 'structured_metadata')
            self.assertNotIn('publication_observation', source)
            self.assertNotIn('support', source)

    def test_source_model_cannot_replace_precision_or_basis(self):
        candidate = self.synthesized()
        for source in candidate['sources']:
            self.assertEqual(source['publication_precision'], 'day')
            self.assertEqual(source['publication_basis'], 'structured_metadata')

    def test_new_receipt_precision_mismatch_fails(self):
        pages = self.dated_pages()
        receipts = radar.build_source_receipts(pages)
        sources = [{key:page[key] for key in ['url','title','published_at','publication_precision','publication_basis']} for page in pages]
        for owner in ['sources', '_source_receipts']:
            for key in ['publication_precision','publication_basis']:
                for altered in [None, 'forged']:
                    c = copy.deepcopy({'sources':sources,'_source_receipts':receipts})
                    if altered is None:c[owner][0].pop(key, None)
                    else:c[owner][0][key] = altered
                    self.assertFalse(radar.verify_sources(c), (owner,key,altered))

    def test_genuine_legacy_receipt_compatible_and_two_publishers_unchanged(self):
        pages = [{'url':url,'title':'Legacy','published_at':'2026-10-21T10:00:00Z','text':BODY}
                 for url in [URL,'https://independent.example/article']]
        receipts = radar.build_source_receipts(pages)
        sources = [{k:p[k] for k in ['url','title','published_at']} for p in pages]
        self.assertTrue(radar.verify_sources({'sources':sources,'_source_receipts':receipts}))
        self.assertFalse(radar.verify_sources({'sources':[sources[0],sources[0]],'_source_receipts':receipts}))

    def test_day_focused_reuse_and_project_cache_keep_binding(self):
        text = '<meta property="article:published_time" content="2026-10-21"><article>' + BODY + '</article>'
        cache = self.home/'cache.json'
        with patch.object(radar, 'is_safe_public_url', return_value=True), patch.object(radar, 'fetch_source', side_effect=AssertionError('network')), patch.object(radar, 'fetch_source_via_gateway', side_effect=AssertionError('gateway')):
            pages = radar.gather_evidence([URL], focused_pages={URL:envelope(text)}, cache_path=cache)
            self.assertTrue(pages[0]['publication_observation'])
            # Focused reuse intentionally does not write ordinary fetch cache.
            cache.write_text(json.dumps({URL:{'checked_at':dt.datetime.now(dt.timezone.utc).isoformat(),'page':pages[0]}}))
            cached = radar.gather_evidence([URL], cache_path=cache)
        self.assertEqual(cached, pages)
        self.assertTrue(publication.validate_observation(cached[0], cached[0]['publication_observation']))

    def test_normalized_extraction_retains_metadata_for_ingestion(self):
        import research_extraction
        text = '<meta property="article:published_time" content="2026-10-21"><article>' + BODY + '</article>'
        row = research_extraction._project({'url':URL,'title':'Quarterly results','content':text}, URL, 6000)
        page = radar.validate_structured_page(URL, envelope(row['content']))
        self.assertEqual(page['publication_observation']['precision'], 'day')

    def test_observation_receipt_rejects_rewritten_publication_value(self):
        page = self.dated_pages()[0]
        page['published_at'] = '2025-01-01'
        with self.assertRaises(ValueError):
            radar.build_source_receipts([page])

    def test_related_article_exact_metadata_cannot_become_legacy_publication(self):
        text = '<script type="application/ld+json">' + json.dumps({'@type':'NewsArticle','url':'https://foreign.example/article','datePublished':'2026-10-21T10:00:00Z'}) + '</script><article>' + BODY + '</article>'
        page = radar.validate_structured_page(URL, envelope(text))
        self.assertEqual(radar.filter_evidence([page], NOW)[0], [])

    def test_selection_does_not_truncate_bound_observations(self):
        pages = self.dated_pages()
        large = publication.prepare_publication_evidence(raw('<meta property="article:published_time" content="2026-10-21">'), extracted_text=BODY*10)
        large['url'] = URL
        pages[0] = large
        candidate = {'symbol': 'ABC', 'urls': [p['url'] for p in pages]}
        originals = {page['url']: copy.deepcopy(page) for page in pages}
        self.assertEqual([len(page['text']) for page in pages], [6000, 889])

        # The second complete witness cannot fit; refusing is safer than truncation.
        refused, selected = radar.select_candidate_evidence([candidate], pages, max_chars=6100)
        self.assertIsNone(refused)
        self.assertEqual(selected, [])

        # The unchanged default budget can retain both canonical sources in full.
        chosen, selected = radar.select_candidate_evidence([candidate], pages)
        self.assertIs(chosen, candidate)
        self.assertEqual(len(selected), 2)
        self.assertCountEqual([page['url'] for page in selected], candidate['urls'])
        self.assertTrue(all(page['text'] and page['publication_observation'] for page in selected))
        bindings_checked = 0
        for page in selected:
            original = originals[page['url']]
            self.assertEqual(page['text'], original['text'])
            self.assertEqual(page['publication_observation'], original['publication_observation'])
            self.assertEqual(page['publication_observation']['content_sha256'],
                             hashlib.sha256(page['text'].encode('utf-8')).hexdigest())
            self.assertTrue(publication.validate_observation(page, page['publication_observation']))
            bindings_checked += 1
        self.assertEqual(bindings_checked, 2)
        self.assertEqual(pages, [originals[url] for url in candidate['urls']])

    def test_day_metadata_direct_structured_and_filter(self):
        for date in ['2026-10-21', '2026-10-21T09:30:00']:
            text = '<meta property="article:published_time" content="' + date + '"><article>' + BODY + '</article>'
            response = io.BytesIO(text.encode())
            response.geturl = lambda: URL
            with patch.object(radar, 'safe_urlopen', return_value=response):
                direct = radar.fetch_source(URL)
            structured = radar.validate_structured_page(URL, envelope(text))
            for page in [direct, structured]:
                with self.subTest(date=date, page=page):
                    self.assertEqual(page['publication_observation']['precision'], 'day')
                    self.assertEqual(page['publication_precision'], 'day')
                    self.assertEqual(page['publication_basis'], 'structured_metadata')
                    self.assertEqual(radar.filter_evidence([page], NOW), ([page], []))

    def test_synthetic_tradeweb_equifax_headers_survive_flattening(self):
        for header in ['<header><h1>Quarterly results</h1><p>October 21, 2026</p></header>',
                       'Quarterly results\nOctober 21, 2026\n',
                       '<h1>Quarterly results</h1><div>Released: October 21, 2026</div>']:
            page = radar.validate_structured_page(URL, envelope(header + '<article>' + BODY + '</article>'))
            self.assertEqual(page['publication_observation']['value'], '2026-10-21')
            self.assertEqual(radar.filter_evidence([page], NOW), ([page], []))

    def test_witness_padding_cannot_admit_short_or_error_body(self):
        for body in ['', 'Short.', 'Access Denied']:
            text = '<meta property="article:published_time" content="2026-10-21">' + '<article>' + body + '</article>'
            response = io.BytesIO(text.encode()); response.geturl = lambda: URL
            with patch.object(radar, 'safe_urlopen', return_value=response):
                page = radar.fetch_source(URL)
            accepted, reasons = radar.filter_evidence([page], NOW)
            self.assertEqual(accepted, [])
            self.assertEqual(reasons[0]['reason'], 'article_body_missing')

    def test_provider_cannot_inject_internal_observation(self):
        for key in ['publication_observation', '_publication_body_text']:
            value = envelope(BODY)
            value['page'][key] = BODY
            self.assertIsNone(radar.validate_structured_page(URL, value))

    def test_capture_conflict_and_late_exact_precision_survive_projection(self):
        day = '<meta property="article:published_time" content="2026-04-24">'
        for suffix, precision in [('<meta property="article:published_time" content="2026-04-23">', None),
                                   ('<meta property="article:published_time" content="2026-04-24T00:00:00Z">', 'instant')]:
            source = raw(day + ('<!-- padding -->' * 700) + suffix + '<article>' + BODY + '</article>')
            page = publication.prepare_publication_evidence(source, extracted_text=BODY)
            self.assertLessEqual(len(page['text']), 6000)
            if precision:
                self.assertEqual(page['publication_observation']['precision'], precision)
                self.assertEqual(publication.evaluate_publication(page, now=NOW), (False, 'stale_source'))
            else:
                self.assertIsNone(page['publication_observation'])

    def test_too_small_projection_and_over_processing_bound_fail_closed(self):
        for source, limit in [(raw('<meta property="article:published_time" content="2026-10-21">' + BODY), 100),
                               (raw('x' * 100001), 6000)]:
            page = publication.prepare_publication_evidence(source, extracted_text=BODY, max_chars=limit)
            self.assertIsNone(page['publication_observation'])
            self.assertEqual(page['_publication_body_text'], BODY[:limit])

    def test_jsonld_current_identity_and_external_fields_not_authority(self):
        import json
        for identity, expected in [(URL, True), ('https://foreign.example/story', False)]:
            text = '<script type="application/ld+json">' + json.dumps({'@type':'NewsArticle','url':identity,'datePublished':'2026-10-21'}) + '</script>'
            page = publication.prepare_publication_evidence({**raw(text), 'publication_observation':{'fake':True}, '_publication_body_text':'fake'}, extracted_text=BODY)
            self.assertEqual(isinstance(page.get('publication_observation'), dict), expected)
            if not expected:self.assertIsNone(page['publication_observation'])
            self.assertEqual(page['_publication_body_text'], BODY)

    def test_adapter_retains_authentic_metadata_before_flattening(self):
        tag = '<meta property="article:published_time" content="2026-10-21">'
        source = raw(tag + '<article>' + BODY + '</article>')
        page = publication.prepare_publication_evidence(source, extracted_text=BODY)
        self.assertNotIn('publication_observation', source)
        self.assertIn(tag, page['text'])
        self.assertEqual(page['_publication_body_text'], BODY)
        self.assertEqual(page['publication_observation']['value'], '2026-10-21')
        self.assertTrue(publication.validate_observation(page, page['publication_observation']))
        self.assertLessEqual(len(page['text']), 6000)
