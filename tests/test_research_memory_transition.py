"""Forward-only retirement uses real canonical writes on synthetic owned roots."""
import copy
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from offline_test_guard import install
install()
import opportunity_fixtures as f
import sqlite_ledger as storage


class MemoryTransitionTests(unittest.TestCase):
    def root(self,version=0):
        root=Path(self.enterContext(tempfile.TemporaryDirectory()))
        f.make_root(root,active=version==1)
        (root/'private/broker_baseline.json').write_text(json.dumps({'preexisting_symbols':[]}))
        if version==2:
            import opportunity_cutover as old
            manifest=old.prepare_manifest(root)
            old.activate_prospective(root,manifest,approved_manifest_sha256=old.manifest_digest(manifest))
        return root

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('research_memory_transition'),
                             'explicit memory retirement transition missing')
        import research_memory_transition as api
        return api

    def prepare(self,root):
        return self.api().prepare_manifest(root,source_revision='f'*40,rule_version='r1')

    def activate(self,root):
        api=self.api();m=self.prepare(root)
        return m,api.apply(root,m,approved_manifest_sha256=api.manifest_digest(m))

    def test_all_predecessors_transition_preserving_prefix_and_replay(self):
        api=self.api()
        import research_mode
        for version in [0,1,2]:
            with self.subTest(version=version):
                root=self.root(version);before=storage.read_stream_snapshot_readonly(root,storage.DEFAULT_STREAMS)
                m,result=self.activate(root)
                self.assertEqual(result['policy_version'],3)
                self.assertEqual(research_mode.context(root).mode,'exact_document_research_dedup')
                self.assertEqual(research_mode.context(root).transition_id,result['transition_id'])
                after=storage.read_stream_snapshot_readonly(root,storage.DEFAULT_STREAMS)
                for name,rows in before.rows.items():self.assertEqual(after.rows[name][:len(rows)],rows)
                again=api.apply(root,m,approved_manifest_sha256=api.manifest_digest(m))
                self.assertFalse(again['appended_activation'])
                self.assertEqual(storage.read_stream_snapshot_readonly(root,storage.DEFAULT_STREAMS).watermark,after.watermark)
                with self.assertRaises(Exception):self.prepare(root)

    def test_wrong_root_digest_and_stale_watermark_have_no_authority(self):
        api=self.api();root=self.root(2);m=self.prepare(root)
        before=storage.read_stream_snapshot_readonly(root,storage.DEFAULT_STREAMS)
        for target,digest in [(root,'0'*64),(self.root(),api.manifest_digest(m))]:
            with self.subTest(target=target),self.assertRaises(Exception):api.apply(target,m,approved_manifest_sha256=digest)
        self.assertEqual(storage.read_stream_snapshot_readonly(root,storage.DEFAULT_STREAMS).watermark,before.watermark)
        storage.append_jsonl(root/'decision_audit.jsonl',{'reason':'concurrent_change'})
        with self.assertRaises(Exception):api.apply(root,m,approved_manifest_sha256=api.manifest_digest(m))
        self.assertEqual(len(storage.read_jsonl_stream_readonly(root/'private/opportunity_policy.jsonl')),1)

    def test_tamper_or_divergent_replay_cannot_become_active_mode(self):
        api=self.api();root=self.root(2);m,_=self.activate(root)
        other=copy.deepcopy(m);other['rule_version']='different'
        with self.assertRaises(Exception):api.apply(root,other,approved_manifest_sha256=api.manifest_digest(other))
        path=root/'private/opportunity_policy.jsonl';path.write_text(path.read_text()+'{}\n')
        import research_mode
        with self.assertRaises(Exception):research_mode.context(root)

    def test_unsupported_predecessor_and_live_mode_are_refused(self):
        api=self.api();root=self.root()
        storage.append_jsonl(root/'private/opportunity_policy.jsonl',f.policy_row('activation',policy_version=99,manifest_sha256='a'*64))
        with self.assertRaises(Exception):self.prepare(root)
        root=self.root();(root/'autonomy_config.json').write_text(json.dumps({'broker_mode':'live'}))
        with self.assertRaises(Exception):self.prepare(root)

    def test_lost_ack_is_resolved_by_exact_readback_on_reapply(self):
        api=self.api();root=self.root(2);m=self.prepare(root);append=storage.append_jsonl
        def lost(*args,**kwargs):append(*args,**kwargs);raise OSError('lost acknowledgement')
        with patch.object(storage,'append_jsonl',side_effect=lost):
            with self.assertRaises(OSError):api.apply(root,m,approved_manifest_sha256=api.manifest_digest(m))
        result=api.apply(root,m,approved_manifest_sha256=api.manifest_digest(m))
        self.assertFalse(result['appended_activation'])
        self.assertEqual(len(storage.read_jsonl_stream_readonly(root/'private/opportunity_policy.jsonl')),2)

    def test_cache_projection_damage_is_not_a_mandatory_mode_blocker(self):
        self.api();root=self.root(2);self.activate(root)
        (root/'private/research_memory.jsonl').write_text('broken-cache\n')
        import research_mode
        self.assertEqual(research_mode.context(root).policy_version,3)

    def test_storage_writer_race_invalidates_approved_watermark(self):
        api=self.api();root=self.root(2);m=self.prepare(root);append=storage.append_jsonl
        def race(path,row,**kwargs):
            append(root/'decision_audit.jsonl',{'reason':'racing_writer'})
            return append(path,row,**kwargs)
        with patch.object(storage,'append_jsonl',side_effect=race):
            with self.assertRaises(storage.LedgerConstraintError):
                api.apply(root,m,approved_manifest_sha256=api.manifest_digest(m))
        self.assertEqual(len(storage.read_jsonl_stream_readonly(root/'private/opportunity_policy.jsonl')),1)

    def test_old_admin_cannot_reset_new_mode_and_old_reader_blocks_it(self):
        api=self.api();root=self.root(2);self.activate(root)
        import opportunity_cutover as old
        import opportunity_state
        with self.assertRaises(Exception):old.prepare_manifest(root)
        with self.assertRaises(Exception):opportunity_state.require_current_allowance(root,{'dossier_hash':'a'*64})

    def test_legacy_v2_stream_descriptor_remains_valid_when_new_stream_registered(self):
        api=self.api();root=self.root(2)
        import opportunity_cutover as old
        rows=storage.read_stream_snapshot_readonly(root,old.BASELINE_STREAMS)
        self.assertNotIn('private/research_memory.jsonl',old.active_baseline(rows)['streams'])
        m=self.prepare(root)
        self.assertIn('private/research_memory.jsonl',m['streams'])


if __name__=='__main__':unittest.main()
