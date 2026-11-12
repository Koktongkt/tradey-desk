"""Offline functional comparison; fictional evidence and no execution authority."""
from offline_test_guard import install
install()
import copy
import json
import unittest
from unittest.mock import patch
import test_research_memory_radar as fixtures
import alpha_radar as radar
import sqlite_ledger as storage
from retained_article import original_text,retain_article


class MemoryWorkflowTests(unittest.TestCase):
    setUp=fixtures.MemoryRadarTests.setUp
    run_research=fixtures.MemoryRadarTests.run_research

    def test_offline_repeat_changed_bundle_comparison_and_private_counters(self):
        self.scouts=self.scouts[:1];self.bundles=self.bundles[:1]
        calls=[]
        def no_setup(cfg,selected,evidence,deadline,**kwargs):
            calls.append(selected['symbol'])
            return {'status':'none','none_reason':'no_fresh_setup'}
        override=((radar,'synthesize_candidate',{'side_effect':no_setup}),)
        self.assertEqual(self.run_research(overrides=override)['none_reason'],'no_fresh_setup')
        self.assertEqual(self.run_research(overrides=override)['none_reason'],'no_new_eligible_opportunity')
        p=self.bundles[0][1]
        self.bundles[0][1]=retain_article(p,original_text(p)+' New source facts.')
        self.assertEqual(self.run_research(overrides=override)['none_reason'],'no_fresh_setup')
        cached_calls=len(calls)
        adapter=radar.research_memory_for_bundle
        def uncached(*args,**kwargs):
            result=adapter(*args,**kwargs);return {**result,'status':'miss','reason':'research_memory_miss'}
        calls.clear()
        with patch.object(radar,'research_memory_for_bundle',side_effect=uncached):
            for _ in range(3):self.run_research(overrides=override)
        self.assertEqual((cached_calls,len(calls)),(2,3))
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root/'order_ledger.jsonl'),[])
        self.assertEqual(storage.read_jsonl_stream_readonly(self.root/'private/reviews.jsonl'),[])
        notes=storage.read_jsonl_stream_readonly(self.root/'private/research_diagnostics.jsonl')
        skipped=[r for r in notes if r.get('outcome')=='duplicate_bundle_skipped']
        self.assertEqual(len(skipped),1)
        self.assertTrue(all(r['reason']=='research_memory_hit' for r in skipped))
        for row in notes:
            self.assertFalse({'capture_refs','dossier_hash','account_id','broker_order_id','root','result'} & set(row))

    def test_real_v3_transition_with_predecessor_rollback_preserves_protection(self):
        import os
        from pathlib import Path
        import hashlib
        import test_opportunity_workflow as old
        import research_memory_transition as transition
        rollback=Path(os.environ.get('TRADEY_MEMORY_ROLLBACK_SOURCE',
            Path(__file__).resolve().parents[1]/'test_artifacts/simple_memory/rollback-source'))
        if not rollback.is_dir():self.skipTest('pinned v2 rollback source not provided')
        self.assertEqual(hashlib.sha256((rollback/'opportunity_activation.py').read_bytes()).hexdigest(),
            '1ba965220dac39d46ce9c4a9c11e2bc6ed63bddccc793e4bae2bea6dfb89e69e')
        for protective in (True,False):
            with self.subTest(protective=protective):
                root,stub=old.OpportunityWorkflowScenario.write_floor_root(self,protective=protective)
                storage.migrate_jsonl(root)
                manifest=transition.prepare_manifest(root,source_revision='f'*40,rule_version='r1')
                transition.apply(root,manifest,approved_manifest_sha256=transition.manifest_digest(manifest))
                env=dict(os.environ,TRADEY_OPPORTUNITY_FLOOR_SOURCE=str(rollback),PYTHONDONTWRITEBYTECODE='1')
                env.pop('PYTHONPATH',None)
                import subprocess,sys
                result=subprocess.run([sys.executable,'-B','-c',old._FLOOR_DRIVER,str(stub),str(root)],
                    cwd=root,env=env,capture_output=True,text=True,timeout=120)
                self.assertEqual(result.returncode,0,result.stderr)
                observed=json.loads(result.stdout.strip().splitlines()[-1])
                self.assertEqual(observed['supported_policy_version'],2)
                if protective:
                    self.assertEqual(observed['code'],0,observed)
                    self.assertIn('TRADE SELL 3',observed['output'])
                    journal=storage.read_jsonl_stream_readonly(root/'trade_journal.jsonl')
                    self.assertEqual(sum(r.get('action')=='SELL' for r in journal),1)
                else:
                    self.assertEqual(observed['code'],2,observed)
                    self.assertIn('opportunity_policy_version_unsupported',observed['output'])
                    self.assertEqual(storage.read_jsonl_stream_readonly(root/'private/reviews.jsonl'),[])

    def test_private_memory_tokens_do_not_leak_to_public_decision(self):
        radar._run_policy_context(self.root)
        radar._memory_note('research_memory_hit')
        line=radar.decision_line({'symbol':'ACME'})
        self.assertNotIn('research_memory',line)
        self.assertNotIn(str(self.root),line)
        self.assertNotIn('capture',line)


if __name__=='__main__':unittest.main()
