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

    def test_missing_body_capture_can_reach_same_existing_recovery_batch(self):
        page=retain_article({**PAGE,'text':'Menu only.'},RAW)
        selected=recovery.choose_recovery_pages([{'symbol':'ABC','urls':[page['url']]}],[page],[],publisher=radar.publisher_domain,filter_pages=radar.filter_evidence)
        self.assertEqual(len(selected),1)
