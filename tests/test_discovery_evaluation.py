import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'test_artifacts/six-lane-historical-audit-20261022T005728Z'
LABELS=ROOT/'test_artifacts/discovery-quality-first/frozen-labels.json'


class EvaluationTests(unittest.TestCase):
    def api(self):
        p=ROOT/'scripts/evaluate_discovery_quality.py'
        self.assertTrue(p.exists(),'evaluator implementation missing')
        spec=importlib.util.spec_from_file_location('quality_evaluator',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

    def test_complete_frozen_inventory_is_accounted(self):
        m=self.api();r=m.evaluate(DATA/'discovery-inventory.json',DATA,LABELS)
        self.assertEqual(r['inventory'],{'sessions':37,'production_sessions':34,'diagnostic_sessions':3,'calls':225,'records':2250})
        self.assertEqual(sum(r['handoff']['new_row_reasons'].values()),57)
        self.assertEqual(r['handoff']['raw_candidates'],57)
        self.assertEqual(r['handoff']['known_overlength_cases'],9)
        self.assertEqual(r['handoff']['known_event_state_cases'],10)
        self.assertEqual(r['handoff']['known_index_cases'],5)
        self.assertEqual(r['live_coverage'],'UNEXERCISED')
        self.assertIsNone(r['new_final_qualified_candidates'])
        self.assertEqual(r['selector_accuracy'],'UNEXERCISED')

    def test_hash_and_missing_fixture_fail_not_skip(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'labels.json';labels=json.loads(LABELS.read_text());labels['hashes']['outcome-sessions.json']='0'*64;p.write_text(json.dumps(labels))
            with self.assertRaises(ValueError):m.evaluate(DATA/'discovery-inventory.json',DATA,p)
            with self.assertRaises((ValueError,OSError)):m.evaluate(DATA/'missing.json',DATA,LABELS)

    def test_semantic_cases_and_fresh_omissions_are_not_claimed_fixed(self):
        m=self.api();r=m.evaluate(DATA/'discovery-inventory.json',DATA,LABELS)
        self.assertEqual(len(r['semantic_review_cases']),10)
        self.assertTrue(all(x['new_semantic_adjudication']=='UNEXERCISED' for x in r['semantic_review_cases']))
        self.assertEqual({x['symbol'] for x in r['fresh_lead_omission_examples']},{'IART','TMO'})
        self.assertTrue(all(not x['trade_eligibility_established'] and not x['selected_in_original_run'] for x in r['fresh_lead_omission_examples']))

    def test_policy_outcomes_are_not_system_errors(self):
        m=self.api();r=m.evaluate(DATA/'discovery-inventory.json',DATA,LABELS)
        self.assertEqual(r['historical_production_outcomes'],{'system_failure':15,'zero_discovery':11,'policy_or_qualification_rejection':7,'new_qualification':1})
        self.assertEqual(r['integration_status'],'UNEXERCISED')

    def test_cli_produces_private_artifacts_and_no_live_mode(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            out=Path(d)/'test_artifacts/report'
            code=m.main(['--inventory',str(DATA/'discovery-inventory.json'),'--results',str(DATA),'--labels',str(LABELS),'--out',str(out)])
            self.assertEqual(code,0);self.assertEqual((out/'summary.json').stat().st_mode&0o777,0o600)
            self.assertEqual(out.stat().st_mode&0o777,0o700)
            self.assertTrue((out/'session-replay.jsonl').exists())
            with self.assertRaises(SystemExit):m.main(['--live'])

    def test_whole_funnel_cases_are_real_intake_not_input_echo(self):
        self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'cases.json';p.write_text(json.dumps({'cases':['supported','earnings_block','missing_publisher']}))
            out=Path(d)/'test_artifacts/report'
            run=subprocess.run([sys.executable,str(ROOT/'scripts/evaluate_discovery_quality.py'),'--inventory',str(DATA/'discovery-inventory.json'),'--results',str(DATA),'--labels',str(LABELS),'--out',str(out),'--integration-fixtures',str(p)],capture_output=True,text=True,timeout=30)
            self.assertEqual(run.returncode,0,run.stdout+run.stderr)
            r=json.loads((out/'summary.json').read_text());cases=r['integration_cases']
            self.assertEqual(cases['supported']['outcome'],'qualified_fixture')
            self.assertTrue(cases['supported']['receipts_verified'])
            self.assertEqual(cases['supported']['accepted_domains'],2)
            self.assertEqual(cases['earnings_block']['outcome'],'policy_block')
            self.assertIn('near_term_earnings',cases['earnings_block']['reason'])
            self.assertEqual(cases['missing_publisher']['outcome'],'evidence_block')
            self.assertEqual(r['integration_status'],'SYNTHETIC_FIXTURES_ONLY')
