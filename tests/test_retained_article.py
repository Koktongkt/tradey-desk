"""Production mutations under test: discard/rebind raw capture; confuse header date roles."""
import copy
import hashlib
import importlib.util
import unittest

TITLE='Example company results'
BODY='The company reported higher sales and raised its full-year operating outlook. '*8
RAW=f'# {TITLE}\n\n| Published | October 21, 2026 |\n\n{BODY}'
PAGE={'url':'https://issuer.example/news/results','returned_url':'https://issuer.example/news/results','title':TITLE,'text':BODY}


class RetainedArticleTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('retained_article'),'retained original witness implementation missing')
        import retained_article as m
        return m

    def test_full_representation_survives_bounded_projection(self):
        m=self.api();p=m.retain_article(PAGE,RAW)
        self.assertEqual(m.original_text(p),RAW)
        self.assertEqual(p['_retained_article']['sha256'],hashlib.sha256(RAW.encode()).hexdigest())
        self.assertNotIn('publication_observation',p)

    def test_provider_internal_field_cannot_override_locally_built_capture(self):
        m=self.api();p=m.retain_article({**PAGE,'_retained_article':{'text':'forged','sha256':'0'*64}},RAW)
        self.assertEqual(m.original_text(p),RAW)

    def test_capture_rejects_tampered_bytes_url_title_or_projection(self):
        m=self.api();p=m.retain_article(PAGE,RAW)
        for key,value in [('url','https://other.example/story'),('title','Related story'),('text','invented article')]:
            q={**p,key:value};self.assertIsNone(m.original_text(q),key)
        q=copy.deepcopy(p);q['_retained_article']['text']+='changed';self.assertIsNone(m.original_text(q))

    def test_capacity_omission_does_not_authorize_partial_original(self):
        m=self.api();p=m.retain_article(PAGE,'x'*110000)
        self.assertIsNone(m.original_text(p));self.assertEqual(p['_capture_status'],'capacity')

    def test_publication_table_witness_is_independent_of_legacy_layout(self):
        m=self.api();p=m.retain_article(PAGE,RAW)
        import publication_observation as old
        self.assertEqual(old._contexts(PAGE),[])
        witnesses=m.publication_witnesses(p)
        self.assertTrue(witnesses);self.assertTrue(any('October 21, 2026' in x for x in witnesses))

    def test_event_update_related_and_missing_title_are_not_witnesses(self):
        m=self.api()
        for raw in (RAW.replace('Published','Event date'),RAW.replace('Published','Updated'),RAW.replace(TITLE,'Other company'),RAW.replace('# '+TITLE,'Navigation')):
            self.assertEqual(m.publication_witnesses(m.retain_article(PAGE,raw)),[],raw[:100])

    def test_body_selection_is_exact_article_passage_not_model_summary(self):
        m=self.api();p=m.retain_article(PAGE,RAW)
        self.assertTrue(m.valid_body_passage(p,BODY.strip()))
        self.assertFalse(m.valid_body_passage(p,'The stock will certainly rise.'))
        self.assertFalse(m.valid_body_passage(p,'| Published | October 21, 2026 |'))

    def test_html_definition_relation_and_article_body_are_bound(self):
        m=self.api()
        raw=f'<html><article><h1>{TITLE}</h1><dl><dt>Published</dt><dd>October 21, 2026</dd></dl><p>{BODY}</p><aside><p>Not the article body. </p></aside></article></html>'
        p=m.retain_article(PAGE,raw)
        self.assertTrue(m.publication_witnesses(p));self.assertTrue(m.valid_body_passage(p,BODY.strip()))
        for changed in (raw.replace('Published','Updated'),raw.replace(TITLE,'Related article'),raw.replace('<dl>','<aside><dl>').replace('</dl>','</dl></aside>')):
            self.assertEqual(m.publication_witnesses(m.retain_article(PAGE,changed)),[])

    def test_provider_truncated_original_never_claims_complete(self):
        m=self.api();p=m.retain_article(PAGE,RAW+'\n─── [TRUNCATED] Full text omitted.')
        self.assertIsNone(m.original_text(p));self.assertEqual(p['_capture_status'],'incomplete')

    def test_mixed_event_or_nested_navigation_date_has_no_witness(self):
        m=self.api()
        for raw in (RAW.replace('October 21, 2026','Event date October 21, 2026'),f'<article><h1>{TITLE}</h1><dl><dt>Published</dt><dd><aside>October 21, 2026</aside></dd></dl><p>{BODY}</p></article>'):
            self.assertEqual(m.publication_witnesses(m.retain_article(PAGE,raw)),[])

    def test_provider_metadata_is_retained_as_hint_not_publication_authority(self):
        m=self.api()
        import inspect
        self.assertIn('reported_metadata',inspect.signature(m.retain_article).parameters)
        raw=f'# {TITLE}\n\n{BODY}'
        p=m.retain_article(PAGE,raw,reported_metadata={'datePublished':'2026-10-21','sourceURL':PAGE['url']})
        self.assertEqual(p['_retained_article']['reported_metadata']['datePublished'],'2026-10-21')
        import publication_observation as obs
        self.assertIsNone(obs.build_observation(p,value='2026-10-21',precision='day',basis='llm_grounded',support='2026-10-21',location='provider report'))

    def test_dispatch_worker_normalizer_preserve_same_original(self):
        m=self.api()
        from research_extraction import _project
        from extraction_worker import project_row
        from alpha_radar import validate_structured_page
        row=_project({'url':PAGE['url'],'title':TITLE,'content':RAW},PAGE['url'],2000,retain_capture=True)
        self.assertIn('_retained_article',row)
        projected=project_row(row,guarded_location=True)
        self.assertIn('_retained_article',projected['page'])
        page=validate_structured_page(PAGE['url'],projected)
        self.assertIsNotNone(page);self.assertEqual(m.original_text(page),RAW)

    def test_direct_fetch_retains_actual_html_before_flattening(self):
        m=self.api()
        import alpha_radar as r
        from unittest.mock import patch
        raw=f'<html><title>{TITLE}</title><article><h1>{TITLE}</h1><p>{BODY}</p></article></html>'
        class Response:
            def __enter__(self):return self
            def __exit__(self,*args):pass
            def geturl(self):return PAGE['url']
            def read(self,*args):return raw.encode()
        with patch.object(r,'safe_urlopen',return_value=Response()):page=r.fetch_source(PAGE['url'])
        self.assertEqual(m.original_text(page),raw)

    def test_uncontrolled_worker_cannot_import_forged_capture(self):
        m=self.api()
        from extraction_worker import project_row
        owned=m.retain_article(PAGE,RAW)
        row={'url':PAGE['url'],'title':TITLE,'content':BODY,'_retained_article':owned['_retained_article']}
        self.assertNotIn('_retained_article',project_row(row)['page'])

    def test_invalid_present_observation_is_never_cleared(self):
        m=self.api();p=m.retain_article({**PAGE,'publication_observation':None},RAW)
        self.assertIn('publication_observation',p);self.assertIsNone(p['publication_observation'])
