"""Unfamiliar layout must recover without the old recognizer; mutations must not."""
import datetime as dt
import json
from pathlib import Path
import subprocess
import tempfile
import time
import unittest
from retained_article import retain_article
from test_retained_article import TITLE,BODY,RAW,PAGE
import publication_interpreter as model
import publication_observation as observation
import publication_recovery as recovery
import alpha_radar as radar

NOW=dt.datetime(2026,10,22,tzinfo=dt.timezone.utc)
SUPPORT='| Published | October 21, 2026 |'


class RetainedRecoveryTests(unittest.TestCase):
    def interpret(self,pages,*,support=SUPPORT,value='2026-10-21',precision='day',body=None):
        calls=[]
        def runner(command,*,input,deadline):
            calls.append(json.loads(input));rows=[]
            for p in calls[-1]['pages']:
                row={'id':p['id'],'value':value,'precision':precision,'support':support,'location':'retained article header'}
                if body is not None:row['body_support']=body
                rows.append(row)
            return subprocess.CompletedProcess([],0,json.dumps({'version':1,'results':rows}),'')
        found,notes=model.interpret_publications(pages,deadline=time.monotonic()+2,command_factory=lambda:['offline'],runner=runner,now=NOW)
        return found,notes,calls

    def test_review_nested_sections_cannot_supply_article_publication(self):
        cases=[(f'# {TITLE}\n\n## Event details\n{SUPPORT}\n\n{BODY}',SUPPORT),
            (f'<article><h1>{TITLE}</h1><section aria-label="Related story"><h2>Other company announcement</h2><dl><dt>Published</dt><dd>October 21, 2026</dd></dl></section><p>{BODY}</p></article>','<dt>Published</dt><dd>October 21, 2026</dd>')]
        for raw,support in cases:
            with self.subTest(raw=raw[:80]):self.assertEqual(self.interpret([retain_article(PAGE,raw)],support=support)[0],{})

    def test_review_unheaded_body_dates_cannot_gain_header_authority(self):
        from research_extraction import _project
        from extraction_worker import project_row
        from retained_article import publication_witnesses,visible_header_text
        url='https://issuer.example/news/results';title='Example company results'
        body='The company reported higher sales and raised its full-year operating outlook. '
        for prefix,label in [('Related story: prior quarter results\n','Published: '),
                             ('','Published: '),('Other article metadata\n','Publication date: ')]:
            with self.subTest(prefix=prefix,label=label):
                raw='# '+title+'\n\n'+body*70+'\n\n'+prefix+label+'October 21, 2026\n\n'+body*60
                row=_project({'url':url,'title':title,'content':raw},url,6000,retain_capture=True)
                page=radar.validate_structured_page(url,project_row(row,guarded_location=True))
                self.assertIsNotNone(page);self.assertNotIn('October 21',page['text'])
                self.assertEqual(publication_witnesses(page),[])
                found,notes,_=self.interpret([page],support=label+'October 21, 2026')
                updated=recovery._attach(page,found.get(url),now=NOW)
                self.assertFalse(updated and radar.filter_evidence([updated],now=NOW)[0])
                self.assertNotIn('October 21',visible_header_text(page))

    def test_review_table_witnesses_share_the_same_header_boundary(self):
        from retained_article import publication_witnesses,visible_header_text
        blocks=['Narrative results.\n'+SUPPORT,'Related story: prior quarter results\n'+SUPPORT,
                '| Related story | Prior quarter results |\n'+SUPPORT,'Narrative results.\n\n'+SUPPORT,
                '| Prior article | Older report |\n'+SUPPORT]
        for block in blocks:
            with self.subTest(block=block):
                page=retain_article(PAGE,f'# {TITLE}\n\n{block}\n\n{BODY}')
                found,_,_=self.interpret([page]);updated=recovery._attach(page,found.get(PAGE['url']),now=NOW)
                self.assertFalse(updated and radar.filter_evidence([updated],now=NOW)[0])
                self.assertEqual(publication_witnesses(page),[]);self.assertEqual(visible_header_text(page),'')

    def test_review_omitted_related_table_rejects_with_and_without_retention(self):
        from research_extraction import _project
        from extraction_worker import project_row
        raw=('# Navigation\n\n'+('Home Products Investors Company newsroom navigation. '*90)+
             f'\n\n# {TITLE}\n\n{BODY}\nRelated story: prior quarter results\n{SUPPORT}\n\n{BODY*15}')
        row=_project({'url':PAGE['url'],'title':TITLE,'content':raw},PAGE['url'],6000,retain_capture=True)
        page=radar.validate_structured_page(PAGE['url'],project_row(row,guarded_location=True))
        self.assertIsNotNone(page);self.assertNotIn('October 21',page['text'])
        for retained in (True,False):
            candidate=page if retained else {k:v for k,v in page.items() if k not in ('_retained_article','_capture_status')}
            found,_,_=self.interpret([candidate]);updated=recovery._attach(candidate,found.get(PAGE['url']),now=NOW)
            self.assertFalse(updated and radar.filter_evidence([updated],now=NOW)[0])

    def test_review_projection_cannot_launder_nested_date(self):
        raw=f'# {TITLE}\n\n## Event details\n{SUPPORT}\n\n{BODY}'
        projection=f'# {TITLE}\nPublished: October 21, 2026\n{BODY}'
        self.assertEqual(self.interpret([retain_article({**PAGE,'text':projection},raw)],support='October 21, 2026')[0],{})

    def test_review_recommendation_labels_never_authorize_foreign_body(self):
        other='An unrelated issuer reports a different transaction and revised guidance. '*8
        labels=['Recommended','**Recommended**','Recommended article','Related','**Related**',
                'Recommendation','Recommendations','Related products','> **Recommended articles**',
                '[Related](https://publisher.example/other)','<strong>Recommended</strong>',
                '__Related__','- Recommended','1. Related','More stories','More from this publisher',
                '> '*40+'Ambiguous deeply nested material']
        for label in labels:
            with self.subTest(label=label):
                raw=RAW+'\n\n'+label+'\n\n'+other
                page=retain_article(PAGE,raw)
                found,_,_=self.interpret([page],body=other.strip())
                updated=recovery._attach(page,found.get(PAGE['url']),now=NOW)
                self.assertFalse(updated and radar.filter_evidence([updated],now=NOW)[0])

    def test_review_nested_markup_punctuation_is_not_an_ownership_escape(self):
        import string
        from retained_article import valid_body_passage
        other='An unrelated issuer reports a different transaction and revised guidance. '*8
        for marker in string.punctuation:
            for role,expected in [('Related',False),('Operating results',True)]:
                with self.subTest(marker=marker,role=role):
                    page=retain_article(PAGE,RAW+'\n\n> '+marker+' '+role+'\n\n'+other)
                    self.assertEqual(valid_body_passage(page,other.strip()),expected)

    def test_review_nested_containers_preserve_recommendation_boundaries(self):
        from itertools import product
        from retained_article import valid_body_passage,original_text
        other='An unrelated issuer reports a different transaction and revised guidance. '*8
        containers=['> {}','- {}','1. {}','- [ ] {}','- [x] {}']
        for first,second,label in product(containers,containers,['Related','Recommended article']):
            wrapped=first.format(second.format(label))
            raw=RAW+'\n\n'+wrapped+'\n\n'+other;page=retain_article(PAGE,raw)
            with self.subTest(label=wrapped):
                self.assertFalse(valid_body_passage(page,other.strip()))
                self.assertEqual(original_text(page),raw)
        for label in ['1. > Related','- [ ] Recommended',
                      '| Related coverage | Other issuer |\n| --- | --- |',
                      '| Links | Recommended article |\n| --- | --- |']:
            with self.subTest(transport_label=label):
                page=retain_article(PAGE,RAW+'\n\n'+label+'\n\n'+other)
                found,_,_=self.interpret([page],body=other.strip())
                updated=recovery._attach(page,found.get(PAGE['url']),now=NOW)
                self.assertFalse(updated and radar.filter_evidence([updated],now=NOW)[0])

    def test_review_transport_recommendation_labels_reject_foreign_body(self):
        from research_extraction import _project
        from extraction_worker import project_row
        other='An unrelated issuer reports a different transaction and revised guidance. '*8
        for label in ['Recommended','**Recommended**','Recommended article','Related story: another issuer',
                      '1. > Related','- [ ] Recommended',
                      '| Related coverage | Other issuer |\n| --- | --- |',
                      '> ## Related','1. ## Related','- ### Recommended',
                      '> - ## **Related coverage**','> ![Related](https://publisher.example/icon.png)']:
            with self.subTest(label=label):
                raw=('# Navigation\n\n'+('Home Products Investors Company newsroom navigation. '*90)+
                     f'\n\n# {TITLE}\n\n{SUPPORT}\n\n{BODY*12}\n\n{label}\n\n{other}')
                row=_project({'url':PAGE['url'],'title':TITLE,'content':raw},PAGE['url'],6000,retain_capture=True)
                page=radar.validate_structured_page(PAGE['url'],project_row(row,guarded_location=True))
                self.assertIsNotNone(page)
                found,_,_=self.interpret([page],body=other.strip())
                updated=recovery._attach(page,found.get(PAGE['url']),now=NOW)
                self.assertFalse(updated and radar.filter_evidence([updated],now=NOW)[0])

    def test_review_related_body_cannot_be_selected_as_article_body(self):
        other='An unrelated issuer reports a different transaction and revised guidance. '*8
        for raw,support in [(RAW+'\n\n## Related companies\n\n'+other,SUPPORT),
            (RAW+'\n\nRelated story: another issuer\n\n'+other,SUPPORT),
            (RAW+'\n\n**Related story:** another issuer\n\n'+other,SUPPORT),
            (f'<article><h1>{TITLE}</h1><dl><dt>Published</dt><dd>October 21, 2026</dd></dl><section aria-label="Related story"><h2>Other issuer</h2><p>{other}</p></section></article>','<dt>Published</dt><dd>October 21, 2026</dd>')]:
            with self.subTest(raw=raw[:80]):self.assertEqual(self.interpret([retain_article(PAGE,raw)],support=support,body=other.strip())[0],{})

    def test_unrecognized_layout_proposal_reaches_actual_source_filter(self):
        page=retain_article(PAGE,RAW);self.assertEqual(observation._contexts(PAGE),[])
        found,notes,calls=self.interpret([page]);self.assertIn(page['url'],found)
        delivered=recovery._attach(page,found[page['url']],now=NOW)
        self.assertEqual(len(radar.filter_evidence([delivered],now=NOW)[0]),1)
        self.assertEqual(len(calls),1);self.assertIn(SUPPORT,calls[0]['pages'][0]['text'])

    def test_original_publication_conflicts_and_instant_downgrade_reject(self):
        for raw,support in [(RAW.replace(SUPPORT,SUPPORT+'\n| Published | October 20, 2026 |'),SUPPORT),(RAW.replace('October 21, 2026','2026-10-21T14:00:00Z'),'| Published | 2026-10-21T14:00:00Z |')]:
            found,_,_=self.interpret([retain_article(PAGE,raw)],support=support)
            self.assertEqual(found,{})

    def test_future_and_wrong_article_and_invalid_present_stay_rejected(self):
        for page,kw in [(retain_article(PAGE,RAW.replace('October 21, 2026','October 30, 2026')),{'value':'2026-10-30','support':SUPPORT.replace('21','30')}),(retain_article(PAGE,RAW.replace(TITLE,'Different article')),{}),(retain_article({**PAGE,'publication_observation':None},RAW),{})]:
            self.assertEqual(self.interpret([page],**kw)[0],{})

    def test_body_passage_recovers_only_exact_retained_article(self):
        page=retain_article({**PAGE,'text':'Menu only.'},RAW)
        found,_,_=self.interpret([page],body=BODY.strip());self.assertIn(page['url'],found)
        delivered=recovery._attach(page,found[page['url']],now=NOW)
        self.assertEqual(delivered['_publication_body_text'],BODY.strip())
        self.assertEqual(len(radar.filter_evidence([delivered],now=NOW)[0]),1)
        self.assertEqual(self.interpret([page],body='Invented body text. '*20)[0],{})

    def test_two_publisher_recovery_uses_one_batch_and_real_filter(self):
        pages=[retain_article({**PAGE,'url':f'https://{domain}/news/results','returned_url':f'https://{domain}/news/results'},RAW) for domain in ('issuer.example','reporter.example')]
        candidates=[{'symbol':'ABC','urls':[p['url'] for p in pages]}]
        with tempfile.TemporaryDirectory() as d:
            calls=[]
            def interpret(selected,*,deadline):
                result,notes,local=self.interpret(selected);calls.extend(local);return result,notes
            delivered,notes=recovery.recover_publications(candidates,pages,[],state=recovery.RecoveryState(),overall_deadline=time.monotonic()+200,downstream_reserve=0,cache_path=Path(d)/'cache.json',fetcher=lambda *a,**k:(_ for _ in ()).throw(AssertionError('no fetch')),interpreter=interpret,publisher=radar.publisher_domain,filter_pages=radar.filter_evidence,allow_model=True)
        accepted,_=radar.filter_evidence(delivered,now=NOW)
        self.assertEqual(len(accepted),2);self.assertEqual(len(calls),1)

    def test_review_known_publication_body_repair_preserves_proof_one_batch(self):
        for kind in ('observation','instant'):
            with self.subTest(kind=kind),tempfile.TemporaryDirectory() as d:
                raw=RAW if kind=='observation' else RAW.replace('October 21, 2026','2026-10-21T14:00:00Z')
                page=retain_article({**PAGE,'text':'Menu only.'},raw)
                if kind=='observation':
                    proof=observation.build_observation(page,value='2026-10-21',precision='day',basis='llm_grounded',support=SUPPORT,location='header')
                    self.assertIsNotNone(proof);page['publication_observation']=proof
                else:page.update(published_at='2026-10-21T14:00:00Z',publication_precision='second')
                self.assertEqual(radar.filter_evidence([page],now=NOW)[1][0]['reason'],'article_body_missing')
                calls=[]
                def interpret(selected,*,deadline):
                    def runner(command,*,input,deadline):
                        wire=json.loads(input);calls.append(wire)
                        return subprocess.CompletedProcess([],0,json.dumps({'version':1,'results':[{'id':r['id'],'body_support':BODY.strip()} for r in wire['pages']]}),'')
                    return model.interpret_publications(selected,deadline=deadline,command_factory=lambda:['offline'],runner=runner,now=NOW)
                result,notes=recovery.recover_publications([{'symbol':'ABC','urls':[page['url']]}],[page],[],state=recovery.RecoveryState(),overall_deadline=time.monotonic()+200,downstream_reserve=0,cache_path=Path(d)/'cache.json',fetcher=lambda *a,**k:(_ for _ in ()).throw(AssertionError('no fetch')),interpreter=interpret,publisher=radar.publisher_domain,filter_pages=radar.filter_evidence)
                self.assertEqual(len(calls),1);self.assertEqual(len(radar.filter_evidence(result,now=NOW)[0]),1)
                self.assertEqual(result[0]['_publication_body_text'],BODY.strip())
                if kind=='observation':
                    for field in ('value','precision','basis','support','location'):self.assertEqual(result[0]['publication_observation'][field],proof[field])
                else:
                    self.assertNotIn('publication_observation',result[0]);self.assertEqual(result[0]['published_at'],page['published_at']);self.assertEqual(result[0]['publication_precision'],'second')

    def test_review_body_only_preserves_hard_refusals_and_stale_dates(self):
        for extra,raw in [({'publication_observation':None,'published_at':'2026-10-21T14:00:00Z'},RAW),
                ({'published_at':'2025-01-01T14:00:00Z'},RAW),
                ({'published_at':'2026-10-21T14:00:00Z'},RAW.replace(TITLE,'Different article'))]:
            page=retain_article({**PAGE,'text':'Menu only.',**extra},raw)
            selected=recovery.choose_recovery_pages([{'symbol':'ABC','urls':[page['url']]}],[page],[],publisher=radar.publisher_domain,filter_pages=radar.filter_evidence)
            self.assertEqual(selected,[])
            self.assertIsNone(recovery._attach(page,{'body_support':BODY.strip()},now=NOW))

    def test_missing_body_capture_can_reach_same_existing_recovery_batch(self):
        page=retain_article({**PAGE,'text':'Menu only.'},RAW)
        selected=recovery.choose_recovery_pages([{'symbol':'ABC','urls':[page['url']]}],[page],[],publisher=radar.publisher_domain,filter_pages=radar.filter_evidence)
        self.assertEqual(len(selected),1)
