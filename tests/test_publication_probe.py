"""Offline synthetic scoring controls; never vendor captures or model calls."""
import importlib.util
import unittest
import tempfile
import json
import os
from unittest.mock import patch
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def probe():
    spec = importlib.util.spec_from_file_location('publication_probe', ROOT/'scripts/probe_publication_recovery.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class PublicationProbeTests(unittest.TestCase):
    def test_scoring_separates_failures_pairs_synthetic_and_wrong_acceptance(self):
        m = probe()
        rows = [dict(id=str(i), kind='real', url='https://one.example/a', event='a',
                     label={'value':'2025-01-02','precision':'day'}, fetch_error=None,
                     parsing_error=None) for i in range(2)]
        rows += [dict(id='s',kind='synthetic',url='https://synthetic.example/a',event='s',
                      label=None,fetch_error=None,parsing_error=None),
                 dict(id='f',kind='real',url='https://two.example/a',event='b',
                      label=None,fetch_error='http_error',parsing_error=None),
                 dict(id='p',kind='real',url='https://three.example/a',event='c',
                      label=None,fetch_error=None,parsing_error='invalid_capture')]
        results={'0':{'value':'2025-01-02','precision':'day'},
                 '1':{'value':'2025-01-03','precision':'day'},
                 's':{'value':'2025-01-02','precision':'day'}}
        counts=m.score_claims(rows,results,accepted_ids={'1','s'})
        self.assertEqual(counts['real']['independent_urls'],3)
        self.assertEqual(counts['real']['scored_representations'],2)
        self.assertEqual(counts['real']['fetch_errors'],1)
        self.assertEqual(counts['real']['parsing_errors'],1)
        self.assertEqual(counts['real']['correct'],1)
        self.assertEqual(counts['real']['wrong_accepted'],1)
        self.assertEqual(counts['real']['missed_known'],1)
        self.assertEqual(counts['synthetic']['unknown_falsely_accepted'],1)
        self.assertEqual(counts['real']['accepted'],1)


    def test_replay_wrong_proposal_does_not_count_as_real_recovery(self):
        m = probe()
        page={'url':'https://one.example/a','title':'Quarterly results',
              'text':'Quarterly results\nPublished: January 2, 2025\n'+'Revenue improved during the quarter. '*5}
        row=dict(id='s',kind='synthetic',url=page['url'],event='a',cohort='fixed',
                 page=page,legacy=None,label={'value':'2025-01-02','precision':'day'})
        data={'version':1,'cohorts':{'fixed':'2025-01-03T12:00:00+00:00'},'rows':[row]}
        raw={'version':1,'results':[{'id':'p0','value':'2025-01-03','precision':'day',
                                  'support':'Published: January 2, 2025','location':'header'}]}
        result=m.evaluate(data,{'page_ids':['s'],'stdout':json.dumps(raw),'origin':'synthetic_control'})
        self.assertEqual(result['raw']['synthetic']['wrong_claims'],1)
        self.assertEqual(result['hybrid']['synthetic']['wrong_accepted'],0)
        self.assertEqual(result['model_evaluated']['real'],0)
        self.assertEqual(result['diagnostics'][0]['reason'],'inadmissible_publication')

    def test_precision_aware_claim_comparison_does_not_invent_midnight(self):
        m=probe()
        self.assertFalse(m.same_claim({'value':'2025-01-02T00:00:00Z','precision':'instant'},
                                     {'value':'2025-01-02','precision':'day'}))
        self.assertTrue(m.same_claim({'value':'2025-01-02T23:00:00-05:00','precision':'instant'},
                                    {'value':'2025-01-03T04:00:00Z','precision':'instant'}))


    def test_exclusive_invocation_record_refuses_failed_or_timeout_retry(self):
        m=probe()
        parent=ROOT/'test_artifacts/publication-hybrid-validation/tests'
        parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.TemporaryDirectory(dir=parent) as td:
            path=Path(td)/'invocation.json'
            m.private_json(path,{'status':'timeout'},exclusive=True)
            self.assertEqual(path.stat().st_mode & 0o777,0o600)
            with self.assertRaises(FileExistsError):
                m.private_json(path,{'status':'started'},exclusive=True)
            self.assertEqual(json.loads(path.read_text())['status'],'timeout')

    def test_admission_preserves_invalid_present_markers_and_large_witness(self):
        m=probe()
        rows=[]
        for i,marker in enumerate([None,False,{},'invalid']):
            page={'url':f'https://p{i}.example/a','title':'Results',
                  'text':'Results\nDate unavailable\n'+'Revenue growth continued. '*8,
                  'publication_observation':marker}
            rows.append(dict(id=str(i),kind='real',url=page['url'],page=page,cohort='fixed'))
        original=json.dumps(rows,sort_keys=True)
        selected,_,_=m.admit({'rows':rows})
        self.assertEqual(selected,[])
        self.assertEqual(json.dumps(rows,sort_keys=True),original)

    def test_default_cli_score_never_calls_live_command(self):
        m=probe()
        parent=ROOT/'test_artifacts/publication-hybrid-validation/tests'
        parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.TemporaryDirectory(dir=parent) as td:
            data=Path(td)/'dataset.json'; results=Path(td)/'results.json'
            data.write_text(json.dumps({'version':1,'rows':[],'cohorts':{}}))
            with patch.object(m,'run_live',side_effect=AssertionError('live not allowed')):
                self.assertEqual(m.main(['--dataset',str(data),'--results',str(results)]),0)
            self.assertEqual(json.loads(results.read_text())['model_evaluated']['real'],0)
            self.assertEqual(results.stat().st_mode & 0o777,0o600)


    def test_live_preparation_failure_is_sticky_and_never_launches(self):
        m=probe()
        parent=ROOT/'test_artifacts/publication-hybrid-validation/tests'
        parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        with tempfile.TemporaryDirectory(dir=parent) as td:
            data=Path(td)/'dataset.json';data.write_text('{}')
            with self.assertRaises(FileNotFoundError):
                m.run_live(data,Path(td)/'out')
            record=data.with_name(data.name+'.invocation.json')
            self.assertEqual(json.loads(record.read_text())['launches'],0)
            with self.assertRaises(FileExistsError):
                m.run_live(data,Path(td)/'second-out')
            self.assertFalse((Path(td)/'second-out').exists())

    def test_day_recovery_is_not_a_fabricated_instant(self):
        m=probe()
        label={'value':'2025-01-02T23:00:00-05:00','precision':'instant'}
        self.assertTrue(m.same_claim({'value':'2025-01-02','precision':'day'},label))
        self.assertFalse(m.same_claim({'value':'2025-01-03','precision':'day'},label))

    def test_live_gate_requires_frozen_independent_coverage(self):
        m=probe()
        with self.assertRaises(ValueError):
            m.validate_freeze({'version':1,'rows':[],'cohorts':{}},{'dataset_sha256':'x'},b'{}')


    def test_stale_grounded_proposal_is_not_needless_validator_rejection(self):
        m=probe()
        page={'url':'https://synthetic.example/old','title':'Results',
              'text':'Results\nPublished: January 2, 2025\n'+'Operating income improved. '*8}
        row={'id':'old','kind':'synthetic','event':'old','url':page['url'],'page':page,
             'cohort':'fixed','label':{'value':'2025-01-02','precision':'day'},'legacy':None}
        proposals={'origin':'synthetic_control','page_ids':['old'],'stdout':json.dumps({'version':1,'results':[
            {'id':'p0','value':'2025-01-02','precision':'day','support':'Published: January 2, 2025','location':'header'}]})}
        scored=m.evaluate({'version':1,'cohorts':{'fixed':'2026-04-01T12:00:00Z'},'rows':[row]},proposals)
        self.assertEqual(scored['raw']['synthetic']['correct'],1)
        self.assertEqual(scored['grounded_recovery']['synthetic'],1)
        self.assertEqual(scored['freshness_rejection']['synthetic'],1)
        self.assertEqual(scored['validator_induced_rejection']['synthetic'],0)
        self.assertEqual(scored['hybrid']['synthetic']['accepted'],0)


if __name__ == '__main__':
    unittest.main()
