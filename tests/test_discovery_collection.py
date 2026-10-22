import datetime as dt
import json
import time
import unittest
from unittest.mock import patch


class CollectionTests(unittest.TestCase):
    def api(self):
        import importlib.util
        self.assertIsNotNone(importlib.util.find_spec('discovery_collection'), 'collector implementation missing')
        import discovery_collection as m
        return m

    def requests(self, m):
        return m.make_queries({}, now=dt.datetime(2026,10,21,15,tzinfo=dt.timezone.utc))

    def test_exact_six_lanes_and_rotation(self):
        m=self.api();a=self.requests(m)
        self.assertEqual([x['lane'] for x in a], list(m.LANES))
        self.assertTrue(all(x['limit']==10 and '2026' in x['query'] for x in a))
        b=m.make_queries({},now=dt.datetime(2026,10,21,15,20,tzinfo=dt.timezone.utc))
        self.assertNotEqual(a[-1]['query'],b[-1]['query'])
        self.assertIn('site:sec.gov',a[1]['query'])
        self.assertIn('Reuters',a[3]['query']);self.assertIn('CNBC',a[3]['query'])
        with self.assertRaises(ValueError):m.make_queries({},now=dt.datetime(2026,10,21))

    def test_partial_lane_is_not_empty_success(self):
        m=self.api()
        def search(query,limit):
            if 'site:sec.gov' in query:raise OSError('private error')
            return json.dumps({'data':{'web':[{'url':'https://example.com/article','title':'release','description':'new announcement'}]},'_meta':{'provider':'exa'}})
        r=m.collect_lanes(self.requests(m),deadline=time.monotonic()+3,search=search)
        self.assertFalse(r['coverage_complete']);self.assertEqual(len(r['lanes']),6)
        self.assertEqual(sum(x['status']=='ok' for x in r['lanes']),5)
        self.assertEqual(r['lanes'][1]['reason'],'provider_error')
        self.assertNotIn('private error',json.dumps(r))

    def test_untrusted_envelope_rejected(self):
        m=self.api()
        raw=json.dumps({'status':'failed','data':{'web':[]}})
        r=m.collect_lanes(self.requests(m),deadline=time.monotonic()+3,search=lambda **kw:raw)
        self.assertFalse(r['coverage_complete'])
        self.assertTrue(all(x['reason']=='provider_error' for x in r['lanes']))

    def test_error_and_oversized_envelopes(self):
        m=self.api()
        samples=[('bad','malformed_response'),(json.dumps({'success':False,'data':{'web':[]}}),'provider_error'),('x'*(256*1024+1),'output_limit'),('{"data":{"web":[]},"data":{"web":[]}}','malformed_response')]
        for raw,reason in samples:
            r=m.collect_lanes(self.requests(m),deadline=time.monotonic()+3,search=lambda **kw:raw)
            self.assertFalse(r['coverage_complete']);self.assertTrue(all(x['reason']==reason for x in r['lanes']))

    def test_no_network_after_deadline(self):
        m=self.api();calls=[]
        r=m.collect_lanes(self.requests(m),deadline=time.monotonic()-1,search=lambda **kw:calls.append(kw))
        self.assertEqual(calls,[]);self.assertTrue(all(x['reason']=='timeout' for x in r['lanes']))

    def test_records_have_exact_binding_and_classification(self):
        m=self.api();u='https://investor.example.com/news/release'
        raw=json.dumps({'data':{'web':[{'url':u,'title':'Class Action Deadline','description':'September results; October deadline','published_at':'2026-10-21'}]},'_meta':{'backend':'wsp','provider':'exa'}})
        r=m.collect_lanes(self.requests(m),deadline=time.monotonic()+3,search=lambda **kw:raw)
        self.assertTrue(r['coverage_complete']);a=r['lanes'][0]['records'][0]
        self.assertEqual(a['url'],u);self.assertTrue(a['legal_solicitation'])
        self.assertNotIn('published_at',a)
        self.assertEqual(len({x['records'][0]['id'] for x in r['lanes']}),6)
        self.assertEqual(r['lanes'][0]['receipt']['provider'],'exa')

    def test_record_count_and_bad_url_fail_closed(self):
        m=self.api()
        for rows in [[{'url':'file:///private','title':'x','description':'x'}],[{'url':'https://example.com/a','title':'x','description':'x'}]*11]:
            r=m.collect_lanes(self.requests(m),deadline=time.monotonic()+3,search=lambda **kw:json.dumps({'data':{'web':rows}}))
            self.assertFalse(r['coverage_complete'])
