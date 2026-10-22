import datetime as dt
import importlib.util
import json
import unittest

NOW=dt.datetime(2026,10,21,15,tzinfo=dt.timezone.utc)


def collection(description='October 21 results for quarter ended September 30',url='https://issuer.example/releases/results-2026'):
    return {'version':1,'coverage_complete':True,'lanes':[{'lane':'issuer_ir','status':'ok','records':[{'id':'r1','url':url,'title':'Company reports results','description':description,'source_role':'unverified','legal_solicitation':False}]}]}


def proposal(**changes):
    row={'result_id':'r1','symbol':'ABC','event_date':'2026-10-21','catalyst':'Reported third-quarter results','support':'October 21 results','event_status':'announced'}
    row.update(changes);return json.dumps({'candidates':[row],'exclusions':[]})


class SelectionTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('discovery_selection'),'selector implementation missing')
        import discovery_selection as m
        return m

    def test_fresh_release_with_old_quarter_end(self):
        m=self.api();c,a=m.admit_selection(proposal(),collection(),now=NOW)
        self.assertEqual(c,[{'symbol':'ABC','catalyst':'Reported third-quarter results','event_date':'2026-10-21','urls':['https://issuer.example/releases/results-2026']}])
        self.assertEqual(a['parsed_candidate_count'],1)
        self.assertNotIn('discard any',m.selector_prompt(collection(),{},now=NOW).lower())

    def test_future_deadline_is_not_fresh_announcement(self):
        m=self.api();x=collection('September 2 law firm notice; October 21 deadline');x['lanes'][0]['records'][0]['legal_solicitation']=True
        c,a=m.admit_selection(proposal(support='October 21 deadline'),x,now=NOW)
        self.assertEqual(c,[]);self.assertIn('legal_solicitation',str(a['row_outcomes']))
        c,a=m.admit_selection(proposal(event_date='2026-09-02'),collection(),now=NOW)
        self.assertEqual(a['stale_event_date_rejected'],1)

    def test_result_id_url_excerpt_binding(self):
        m=self.api()
        for edits in ({'result_id':'invented'},{'support':'made up'},{'urls':['https://evil.example']},{'event_date':'2026-10-22'}):
            c,a=m.admit_selection(proposal(**edits),collection(),now=NOW)
            self.assertEqual(c,[],edits)
            self.assertEqual(len(a['row_outcomes']),1)

    def test_index_and_overlength_are_typed_rejections(self):
        m=self.api()
        c,a=m.admit_selection(proposal(),collection(url='https://example.com/news/ABC/'),now=NOW)
        self.assertEqual(c,[]);self.assertIn('article_identity_unverified',str(a['row_outcomes']))
        c,a=m.admit_selection(proposal(catalyst='x'*501),collection(),now=NOW)
        self.assertEqual(c,[]);self.assertIn('catalyst_too_long',str(a['row_outcomes']))

    def test_event_state_never_authoritative(self):
        m=self.api();c,a=m.admit_selection(proposal(event_status='completed'),collection(),now=NOW)
        self.assertEqual(len(c),1);self.assertNotIn('event_status',c[0]);self.assertFalse(a['row_outcomes'][0]['event_verified'])
        self.assertEqual(a['dispositions']['r1']['status'],'selected')

    def test_missing_exclusions_unknown_and_duplicate_ids_rejected(self):
        m=self.api();x=collection();r=x['lanes'][0]['records'][0];x['lanes'][0]['records'].append({**r,'id':'r2','url':'https://issuer.example/other'})
        c,a=m.admit_selection(proposal(),x,now=NOW)
        self.assertEqual(a['dispositions']['r2']['status'],'unaccounted')
        x['lanes'][0]['records'][1]['id']='r1'
        c,a=m.admit_selection(proposal(),x,now=NOW)
        self.assertEqual(c,[]);self.assertEqual(a['reason'],'collection_schema_rejected')

    def test_prompt_preserves_all_ids_and_caps_encoded_size(self):
        m=self.api();x=collection();r=x['lanes'][0]['records'][0]
        x['lanes'][0]['records']=[{**r,'id':f'r{i}','url':'https://issuer.example/'+('x'*4000)+str(i),'description':'é'*10000} for i in range(60)]
        p=m.selector_prompt(x,{},now=NOW);self.assertLessEqual(len(p.encode()),65536)
        payload=json.loads(p.split('\nINPUT_JSON\n',1)[1]);self.assertEqual(len(payload['results']),60)
        self.assertTrue(all(z['context_limited'] for z in payload['results']))

    def test_malformed_nested_values_fail_closed(self):
        m=self.api()
        for edits in ({'result_id':[]},{'event_status':[]},{'symbol':{}},{'support':None}):
            c,a=m.admit_selection(proposal(**edits),collection(),now=NOW)
            self.assertEqual(c,[])
            self.assertEqual(len(a['row_outcomes']),1)
        c,a=m.admit_selection(json.dumps({'candidates':[],'exclusions':[{'result_id':'r1','reason':[]}]}),collection(),now=NOW)
        self.assertEqual(c,[])

    def test_normal_empty_is_not_selector_failure(self):
        m=self.api();c,a=m.admit_selection('{"candidates":[],"exclusions":[]}',collection(),now=NOW)
        self.assertEqual(a['reason'],'no_discovered_candidate')
        c,a=m.admit_selection('bad',collection(),now=NOW);self.assertEqual(a['reason'],'invalid_json')
