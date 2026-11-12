"""Exact bytes and explicit representation, never prose/URL identity."""
import importlib.util
import unittest
from offline_test_guard import install
install()


class MemoryKeyTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('research_memory'),
                             'exact-document key implementation is missing')
        import research_memory
        return research_memory

    def doc(self, **changes):
        args=dict(issuer='CIK:0001446847', representation='provider:text:v1',
                  content=b'Full original report\nRevenue 100', rule_version='research-v1',
                  stage='document')
        args.update(changes)
        return self.api().document_key(**args)

    def test_same_complete_bytes_are_stable(self):
        self.assertRegex(self.doc(), r'^rm1:[0-9a-f]{64}$')
        self.assertEqual(self.doc(), self.doc())

    def test_complete_bytes_not_excerpt_control_identity(self):
        self.assertNotEqual(self.doc(), self.doc(content=b'Full original report\nRevenue 101'))
        self.assertNotEqual(self.doc(content=b'Original\n'), self.doc(content=b'Original'))

    def test_issuer_representation_rules_and_stage_are_separate(self):
        for changes in [dict(issuer='CIK:0001420520'),dict(representation='sec:wire:v1'),
                        dict(rule_version='research-v2'),dict(stage='publication')]:
            with self.subTest(changes=changes):
                self.assertNotEqual(self.doc(),self.doc(**changes))

    def test_bundle_is_order_independent_but_new_evidence_is_new_work(self):
        api=self.api(); a=self.doc();b=self.doc(content=b'Other source');c=self.doc(content=b'New source')
        def bundle(keys):
            return api.bundle_key(issuer='CIK:0001446847',document_keys=keys,
                                  rule_version='research-v1',stage='synthesis')
        self.assertEqual(bundle((a,b)),bundle((b,a,a)))
        self.assertNotEqual(bundle((a,b)),bundle((a,c)))
        self.assertNotEqual(bundle((a,)),bundle((a,b)))
        self.assertRegex(bundle((a,b)),r'^rb1:[0-9a-f]{64}$')

    def test_invalid_document_inputs_are_rejected(self):
        for changes in [dict(issuer=''),dict(issuer=True),dict(content=b''),dict(content='text'),
                        dict(representation=' '),dict(rule_version=''),dict(stage=None)]:
            with self.subTest(changes=changes),self.assertRaises(ValueError):self.doc(**changes)

    def test_invalid_bundle_inputs_are_rejected(self):
        api=self.api()
        for keys in [(),('rm1:bad',),('rb1:'+'a'*64,),('rm1:'+'a'*64,False),[],None]:
            with self.subTest(keys=keys),self.assertRaises(ValueError):
                api.bundle_key(issuer='CIK:0001446847',document_keys=keys,
                               rule_version='research-v1',stage='synthesis')


if __name__=='__main__':unittest.main()
