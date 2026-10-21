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


    def test_precision_loss_counter_distinguishes_day_vs_instant_and_exact(self):
        m = probe()
        rows = [dict(id='d', kind='real', url='https://one.example/a', event='a',
                     label={'value':'2025-01-02T23:00:00-05:00','precision':'instant'},
                     fetch_error=None, parsing_error=None),
                dict(id='x', kind='real', url='https://two.example/a', event='b',
                     label={'value':'2025-01-02T23:00:00-05:00','precision':'instant'},
                     fetch_error=None, parsing_error=None),
                dict(id='w', kind='real', url='https://three.example/a', event='c',
                     label={'value':'2025-01-02T23:00:00-05:00','precision':'instant'},
                     fetch_error=None, parsing_error=None)]
        claims = {'d': {'value':'2025-01-02','precision':'day'},
                  'x': {'value':'2025-01-02T23:00:00-05:00','precision':'instant'},
                  'w': {'value':'2025-01-03','precision':'day'}}
        counts = m.score_claims(rows, claims, accepted_ids=set())
        self.assertEqual(counts['real']['precision_loss'], 1)
        self.assertEqual(counts['real']['correct'], 2)
        self.assertEqual(counts['real']['wrong_claims'], 1)
        self.assertEqual(counts['real']['missed_known'], 1)

    def test_replay_accepts_bytes_stdout_like_real_runner(self):
        m = probe()
        page = {'url':'https://synthetic.example/b','title':'Results',
                'text':'Results\nPublished: January 2, 2025\n'+'Revenue improved during the quarter. '*5}
        row = dict(id='s', kind='synthetic', url=page['url'], event='b', cohort='fixed',
                   page=page, legacy=None, label={'value':'2025-01-02','precision':'day'})
        data = {'version':1,'cohorts':{'fixed':'2025-01-03T12:00:00+00:00'},'rows':[row]}
        raw = {'version':1,'results':[{'id':'p0','value':'2025-01-02','precision':'day',
                                       'support':'Published: January 2, 2025','location':'header'}]}
        result = m.evaluate(data, {'page_ids':['s'],'stdout':json.dumps(raw).encode(),'origin':'synthetic_control'})
        self.assertEqual(result['raw']['synthetic']['correct'], 1)
        self.assertEqual(result['model_evaluated']['synthetic'], 1)

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


    # --- metadata-region extraction (approved Task5 scope extension) ---

    def test_metadata_region_extract_slices_to_bounded_header_region(self):
        m = probe()
        capture = '<html><head><meta property="article:published_time" content="2025-06-10">' + 'x' * 20000
        n = len(capture)
        sliced = m.metadata_region_extract(capture)
        self.assertLessEqual(len(sliced), 8192)
        self.assertTrue(sliced.startswith('<html>'))
        # Original capture is never mutated or replaced.
        self.assertEqual(len(capture), n)
        self.assertIn('article:published_time', sliced)
        with self.assertRaises(ValueError):
            m.metadata_region_extract(12345)
        with self.assertRaises(ValueError):
            m.metadata_region_extract(capture, limit=0)
        with self.assertRaises(ValueError):
            m.metadata_region_extract(capture, limit=10000)

    def _synthetic_oversized_row(self, m, head_html, body_fill, label):
        import hashlib
        capture = head_html + body_fill
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'captures').mkdir(mode=0o700)
            (base / 'captures' / 's0.original.txt').write_text(capture)
            page = {'url': 'https://synthetic.example/a', 'title': 'Release',
                    'text': 'Release\n' + 'Filler body line. ' * 400,
                    'publication_observation': {'invalid': True}}
            row = dict(id='s0', kind='real', url=page['url'], event=page['url'],
                       class_='independent reporting', cohort='fixed', representation='html',
                       label=label, label_witness='w', label_rationale='r',
                       fetch_error=None, parsing_error=None, page=page,
                       capture='captures/s0.original.txt',
                       capture_sha256=hashlib.sha256(capture.encode()).hexdigest())
            data = {'version': 1, 'cohorts': {'fixed': '2025-06-11T12:00:00+00:00'}, 'rows': [row]}
            return m.evaluate_metadata_region(data, base_dir=str(base))

    def test_synthetic_oversized_header_metadata_recovers_without_model(self):
        m = probe()
        head = ('<html><head><title>Release</title>'
                '<meta property="article:published_time" content="2025-06-10T08:00:00-04:00">'
                '</head><body>')
        result = self._synthetic_oversized_row(
            m, head, 'Body prose. ' * 20000,
            {'value': '2025-06-10', 'precision': 'day'})
        totals = result['totals']
        self.assertEqual(totals['oversized'], 1)
        self.assertEqual(totals['hash_verified'], 1)
        self.assertEqual(totals['recovered_without_model'], 1)
        self.assertEqual(totals['still_unresolved'], 0)
        self.assertEqual(totals['wrong_accepted'], 0)
        self.assertEqual(totals['precision_loss'], 0)

    def test_synthetic_body_embedded_metadata_stays_unresolved_honestly(self):
        m = probe()
        head = '<html><head><title>Release</title></head><body>'
        result = self._synthetic_oversized_row(
            m, head, 'Body prose. ' * 20000 + 'Published 2025-06-10 in the deep body. ',
            {'value': '2025-06-10', 'precision': 'day'})
        totals = result['totals']
        self.assertEqual(totals['recovered_without_model'], 0)
        self.assertEqual(totals['still_unresolved'], 1)
        self.assertEqual(totals['wrong_accepted'], 0)

    def test_real_corpus_metadata_region_scoring_is_hash_bound_and_honest(self):
        m = probe()
        dataset_path = ROOT / 'test_artifacts/publication-hybrid-validation/dataset.json'
        if not dataset_path.exists():
            self.skipTest('private frozen corpus absent')
        data = json.loads(dataset_path.read_text())
        result = m.evaluate_metadata_region(data)
        totals = result['totals']
        self.assertEqual(totals['hash_verified'], totals['oversized'])
        self.assertEqual(totals['oversized'], 17)
        # Every counted outcome sums exactly to the oversized total
        # (freshness_rejected/precision_loss overlap recovered_without_model).
        self.assertEqual(totals['recovered_without_model'] + totals['still_unresolved']
                         + totals['wrong_accepted'] + totals['validator_rejections'],
                         totals['oversized'])
        # Apple JSON-LD dates sit ~250k deep: header slice must NOT recover them.
        by_id = {r['id']: r for r in result['rows']}
        self.assertEqual(by_id['r00']['result'], 'unresolved')
        self.assertEqual(by_id['r01']['result'], 'unresolved')
        # Head-region metadata pages (PRNewswire/Guardian/BBC/NASA) do recover.
        self.assertEqual(by_id['r04']['result'], 'recovered')
        # Guardian instant dates are correct but stale at the 2026-04-01 cohort
        # clock: recovery counted, freshness rejection as a separate counter.
        self.assertEqual(by_id['r10']['result'], 'recovered_freshness_rejected')
        self.assertIn(by_id['r10']['id'],
                      [row['id'] for row in result['rows']
                       if row['result'].startswith('recovered')])
        # Controller-ruled generic JSON-LD/cXenseParse recognition replaced the
        # closed BBC refusal: the BBC head-region JSON-LD (ReportageNewsArticle)
        # now recovers even under the old fixed header slice.
        self.assertIn(by_id['r18']['result'], ('recovered', 'recovered_freshness_rejected'))
        self.assertEqual(by_id['r22']['result'], 'recovered_freshness_rejected')
        # Per-publisher summary present and consistent.
        self.assertTrue(result['per_publisher'])
        for domain, agg in result['per_publisher'].items():
            self.assertEqual(agg['recovered_without_model'] + agg['still_unresolved']
                             + agg['wrong_accepted'] + agg['validator_rejections'],
                             agg['representations'])

    # --- date-candidate context extraction (controller-ruled header-slice
    # replacement): full-capture date signals — JSON-LD datePublished fields,
    # generic publish/date meta names, itemprop time tags, prose datelines —
    # extracted as bounded candidate contexts, never a fixed first-8k slice.

    def _date_candidate_row(self, m, head_html, body_fill, label, url='https://synthetic.example/a'):
        import hashlib
        capture = head_html + body_fill
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            (base / 'captures').mkdir(mode=0o700)
            (base / 'captures' / 's0.original.txt').write_text(capture)
            page = {'url': url, 'title': 'Release',
                    'text': 'Release\n' + 'Filler body line. ' * 400,
                    'publication_observation': {'invalid': True}}
            row = dict(id='s0', kind='real', url=page['url'], event=page['url'],
                       class_='independent reporting', cohort='fixed', representation='html',
                       label=label, label_witness='w', label_rationale='r',
                       fetch_error=None, parsing_error=None, page=page,
                       capture='captures/s0.original.txt',
                       capture_sha256=hashlib.sha256(capture.encode()).hexdigest())
            data = {'version': 1, 'cohorts': {'fixed': '2025-06-11T12:00:00+00:00'}, 'rows': [row]}
            return m.evaluate_date_candidates(data, base_dir=str(base))

    def test_evaluate_date_candidates_deep_metadata_recovers_without_model(self):
        m = probe()
        head = '<html><head><title>Release</title></head><body>'
        deep = ('<p>Filler paragraph with no dates.</p>' * 1500
                + '<script type="application/ld+json">'
                  '{"@context":"http://schema.org","@type":"NewsArticle",'
                  '"mainEntityOfPage":"https://synthetic.example/a",'
                  '"datePublished":"2025-06-10T08:00:00-04:00"}</script>'
                + '<p>Filler paragraph with no dates.</p>' * 1500)
        result = self._date_candidate_row(
            m, head, deep, {'value': '2025-06-10T08:00:00-04:00', 'precision': 'instant'})
        totals = result['totals']
        self.assertEqual(totals['oversized'], 1)
        self.assertEqual(totals['hash_verified'], 1)
        self.assertEqual(totals['recovered_without_model'], 1)
        self.assertEqual(totals['still_unresolved'], 0)
        self.assertEqual(totals['wrong_accepted'], 0)
        self.assertEqual(totals['validator_rejections'], 0)

    def test_evaluate_date_candidates_no_signal_stays_unresolved_honestly(self):
        m = probe()
        head = '<html><head><title>Release</title></head><body>'
        result = self._date_candidate_row(
            m, head, '<p>Filler prose without any dates or signals.</p>' * 2500,
            {'value': '2025-06-10', 'precision': 'day'})
        totals = result['totals']
        self.assertEqual(totals['recovered_without_model'], 0)
        self.assertEqual(totals['still_unresolved'], 1)
        self.assertEqual(totals['wrong_accepted'], 0)

    def test_real_corpus_date_candidates_scoring_is_hash_bound_and_honest(self):
        m = probe()
        dataset_path = ROOT / 'test_artifacts/publication-hybrid-validation/dataset.json'
        if not dataset_path.exists():
            self.skipTest('private frozen corpus absent')
        data = json.loads(dataset_path.read_text())
        result = m.evaluate_date_candidates(data)
        totals = result['totals']
        self.assertEqual(totals['oversized'], 17)
        self.assertEqual(totals['hash_verified'], totals['oversized'])
        self.assertEqual(totals['recovered_without_model'] + totals['still_unresolved']
                         + totals['wrong_accepted'] + totals['validator_rejections'],
                         totals['oversized'])
        # The ten formerly header-slice-unresolved representations recover
        # through bounded date-candidate extraction (deep JSON-LD, deep
        # publish metadata, generic subtypes, prose place datelines).
        by_id = {r['id']: r for r in result['rows']}
        for rid in ('r00', 'r01', 'r02', 'r03', 'r15', 'r16', 'r17', 'r18', 'r19', 'r20'):
            self.assertIn(by_id[rid]['result'],
                          ('recovered', 'recovered_freshness_rejected'), rid)
        # No regressions and no false acceptances anywhere.
        self.assertEqual(totals['wrong_accepted'], 0)
        for domain, agg in result['per_publisher'].items():
            self.assertEqual(agg['recovered_without_model'] + agg['still_unresolved']
                             + agg['wrong_accepted'] + agg['validator_rejections'],
                             agg['representations'])


if __name__ == '__main__':
    unittest.main()
