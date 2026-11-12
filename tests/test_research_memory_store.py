"""Real private capture/store behavior, with no provider or broker I/O."""
import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from offline_test_guard import install
install()
from retained_article import retain_article
import sqlite_ledger as storage

STAMP='2026-11-12T00:00:00+00:00'


class MemoryStoreTests(unittest.TestCase):
    def setUp(self):
        self.root=Path(self.enterContext(tempfile.TemporaryDirectory()))

    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('evidence_capture_store'),
                             'event-independent capture store missing')
        import evidence_capture_store as captures
        import research_memory as memory
        return captures,memory

    def page(self):
        return retain_article(dict(url='https://issuer.example/report',title='Results',text='excerpt'),
                              'Complete original results, revenue 100')

    def completed(self, **changes):
        captures,memory=self.api();ref=captures.retain_page(self.root,self.page())
        key=memory.document_key(issuer='CIK:0001446847',representation=ref['representation'],
                               content=captures.read_capture(self.root,ref),rule_version='r1',stage='document')
        args=dict(key=key,stage='document',rule_version='r1',capture_refs=(ref,),
                  result={'publication_validated':True},disposition='document_processed',completed_at=STAMP)
        args.update(changes)
        return memory.complete(self.root,**args)

    def lookup(self,key,now=STAMP,check=lambda record,result:True):
        return self.api()[1].lookup(self.root,key=key,now=now,freshness_check=check)

    def test_repeated_completion_with_later_clock_does_not_refresh_ttl(self):
        row=self.completed()
        again=self.completed(completed_at='2026-11-12T12:00:00+00:00')
        self.assertEqual(again,row)
        self.assertEqual(len(storage.read_jsonl_stream_readonly(self.root/'private/research_memory.jsonl')),1)

    def test_missing_result_and_freshness_exception_are_not_hits(self):
        _,mem=self.api();row=self.completed()
        def broken(record,result):raise RuntimeError('unavailable freshness')
        self.assertEqual(self.lookup(row['key'],check=broken)['status'],'unusable')
        (self.root/row['result_ref']['path']).unlink()
        self.assertEqual(self.lookup(row['key'])['status'],'unusable')

    def test_retained_complete_content_and_private_readback(self):
        cap,_=self.api();ref=cap.retain_page(self.root,self.page())
        self.assertEqual(cap.read_capture(self.root,ref),b'Complete original results, revenue 100')
        self.assertEqual((self.root/ref['path']).stat().st_mode&0o777,0o600)
        self.assertEqual((self.root/ref['path']).parent.stat().st_mode&0o777,0o700)

    def test_completion_replay_does_not_append_or_renew_time(self):
        row=self.completed();self.assertEqual(self.completed(),row)
        rows=storage.read_jsonl_stream_readonly(self.root/'private/research_memory.jsonl')
        self.assertEqual(len(rows),1)
        hit=self.lookup(row['key'],now='2026-11-12T12:00:00+00:00')
        self.assertEqual(hit['status'],'hit');self.assertEqual(hit['record']['completed_at'],STAMP)

    def test_expiry_and_stricter_freshness_never_become_hit(self):
        row=self.completed()
        self.assertNotEqual(self.lookup(row['key'],now='2026-11-13T00:00:00+00:00')['status'],'hit')
        self.assertNotEqual(self.lookup(row['key'],check=lambda r,v:False)['status'],'hit')
        self.assertNotEqual(self.lookup(row['key'],now='2026-11-11T23:59:59+00:00')['status'],'hit')

    def test_failed_partial_or_unproven_work_cannot_complete(self):
        for disposition in ['failed','partial','http_ok','lead_saved','timeout']:
            with self.subTest(disposition=disposition),self.assertRaises(ValueError):
                self.completed(disposition=disposition)
        self.assertFalse((self.root/'private/research_memory.jsonl').exists())

    def test_capture_tamper_and_missing_result_are_unusable(self):
        cap,mem=self.api();row=self.completed()
        (self.root/row['capture_refs'][0]['path']).write_bytes(b'corrupted')
        self.assertEqual(self.lookup(row['key'])['status'],'unusable')

    def test_result_write_failure_cannot_publish_completion(self):
        cap,_=self.api()
        with patch.object(cap,'retain_result',side_effect=OSError('disk failed')):
            with self.assertRaises(OSError):self.completed()
        self.assertFalse((self.root/'private/research_memory.jsonl').exists())

    def test_unsafe_ref_paths_and_files_are_rejected(self):
        cap,_=self.api();ref=cap.retain_page(self.root,self.page());p=self.root/ref['path']
        for path in ['../escape','/absolute', 'private/research_evidence/../../outside']:
            with self.subTest(path=path),self.assertRaises((ValueError,OSError)):
                cap.read_capture(self.root,{**ref,'path':path})
        p.chmod(0o644)
        with self.assertRaises((ValueError,OSError)):cap.read_capture(self.root,ref)
        p.chmod(0o600);os.link(p,self.root/'other')
        with self.assertRaises((ValueError,OSError)):cap.read_capture(self.root,ref)

    def test_redirect_incomplete_and_projection_tamper_are_not_retained(self):
        cap,_=self.api()
        variants=[{'url':'https://issuer.example/report','text':'no capture'},
                  {**self.page(),'text':'forged projection'},
                  {**self.page(),'returned_url':'https://other.example/report'}]
        for page in variants:
            with self.subTest(page=page),self.assertRaises(ValueError):cap.retain_page(self.root,page)

    def test_symlink_ancestor_cannot_publish(self):
        cap,_=self.api();outside=self.root/'elsewhere';outside.mkdir(mode=0o700)
        (self.root/'private').symlink_to(outside,target_is_directory=True)
        with self.assertRaises(OSError):cap.retain_page(self.root,self.page())
        self.assertEqual(list(outside.iterdir()),[])

    def test_cache_integrity_failure_is_unusable_not_success(self):
        _,mem=self.api();row=self.completed()
        with patch.object(storage,'read_jsonl_stream_readonly',side_effect=storage.LedgerIntegrityError('damage')):
            self.assertEqual(self.lookup(row['key'])['status'],'unusable')
            self.assertTrue(mem.retry_allowed(self.root,issuer='CIK:1',url='https://one.example/a',
                                             reason='source_fetch_timeout',now=STAMP))

    def test_exact_resource_cooldown_expires_at_twenty_minutes(self):
        _,mem=self.api();args=dict(issuer='CIK:1',url='https://one.example/a',reason='source_fetch_timeout')
        mem.note_failure(self.root,**args,failed_at=STAMP)
        self.assertFalse(mem.retry_allowed(self.root,**args,now='2026-11-12T00:19:00+00:00'))
        self.assertTrue(mem.retry_allowed(self.root,**args,now='2026-11-12T00:20:00+00:00'))
        for changed in [dict(issuer='CIK:2'),dict(url='https://one.example/b'),dict(reason='source_http_forbidden')]:
            self.assertTrue(mem.retry_allowed(self.root,**{**args,**changed},now=STAMP))

    def test_concurrent_identical_completions_are_idempotent(self):
        # Build references once; concurrent writers exercise actual entry/storage locks.
        self.completed()
        with ThreadPoolExecutor(max_workers=2) as pool:
            rows=list(pool.map(lambda _:self.completed(),range(2)))
        self.assertEqual(rows[0],rows[1])
        self.assertEqual(len(storage.read_jsonl_stream_readonly(self.root/'private/research_memory.jsonl')),1)


if __name__=='__main__':unittest.main()
