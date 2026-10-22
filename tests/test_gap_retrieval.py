"""Gap search selection must remain source-attested, finite and candidate-bound."""
import importlib.util
import json
from pathlib import Path
import subprocess
import time
import unittest
from unittest.mock import patch


class GapRetrievalTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('gap_retrieval'),'gap search not implemented')
        import gap_retrieval as m
        return m

    def test_query_and_picker_skip_attempted_and_accepted_publishers(self):
        m=self.api();seen=[]
        def runner(command,data,**kw):
            seen.append(json.loads(data))
            return subprocess.CompletedProcess([],0,json.dumps({'status':'ok','records':[{'url':'https://issuer.example/old'},{'url':'https://issuer.example/new'},{'url':'https://reporter.example/report'}]}),'')
        with patch.object(m,'run_process',side_effect=runner):
            url=m.search_gap('ABC','Results and guidance','2026-10-21',role='independent',attempted={'https://issuer.example/old'},accepted_domains={'issuer.example'},deadline=time.monotonic()+2)
        self.assertEqual(url,'https://reporter.example/report');self.assertEqual(len(seen),1)
        self.assertIn('ABC',seen[0]['query']);self.assertIn('2026-10-21',seen[0]['query'])

    def test_empty_expired_or_malformed_never_invent_url(self):
        m=self.api()
        for result in [subprocess.CompletedProcess([],0,'{"status":"ok","records":[]}',''),subprocess.CompletedProcess([],0,'not json','')]:
            with patch.object(m,'run_process',return_value=result):
                self.assertIsNone(m.search_gap('ABC','results','2026-10-21',role='wire',attempted=set(),accepted_domains=set(),deadline=time.monotonic()+2))
        with patch.object(m,'run_process',side_effect=AssertionError('late launch')):
            self.assertIsNone(m.search_gap('ABC','results','2026-10-21',role='wire',attempted=set(),accepted_domains=set(),deadline=time.monotonic()-1))

    def test_unconfirmed_search_cleanup_is_not_an_empty_lane(self):
        m=self.api();self.assertTrue(hasattr(m,'GapContainmentError'))
        failure=subprocess.CompletedProcess([],1,'{"reason":"containment_unconfirmed"}','')
        with patch.object(m,'run_process',return_value=failure):
            with self.assertRaises(m.GapContainmentError):m.search_gap('ABC','results','2026-10-21',role='wire',attempted=set(),accepted_domains=set(),deadline=time.monotonic()+2)

    def test_alpha_route_is_opt_in_and_scope_resets(self):
        import alpha_radar as r
        self.assertTrue(hasattr(r,'_gap_directed'),'missing gap retrieval scope')
        f=r.correlated_research_run(lambda cfg:r._gap_directed.get())
        self.assertTrue(f({'gap_retrieval_enabled':True}));self.assertFalse(r._gap_directed.get())
        m=self.api();token=r._gap_directed.set(True)
        try:
            with patch.object(m,'search_gap',return_value='https://reporter.example/article') as run:
                value=r.gateway_rescue_url('ABC','results',deadline=time.monotonic()+2,event_date='2026-10-21',attempted={'https://issuer.example/old'},accepted_domains={'issuer.example'})
            self.assertEqual(value,'https://reporter.example/article');self.assertEqual(run.call_count,1)
        finally:r._gap_directed.reset(token)

    def test_focused_prompt_carries_unverified_seed_gaps_not_verified_claims(self):
        from focused_search import search_prompt
        p=search_prompt([{'symbol':'ABC','event_date':'2026-10-21','catalyst':'results','urls':['https://issuer.example/announcement']}])
        self.assertIn('seed_publishers_unverified',p);self.assertIn('same company-event',p)
        self.assertIn('at most five calls total',p)
