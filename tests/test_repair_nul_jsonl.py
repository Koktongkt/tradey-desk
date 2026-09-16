import importlib.util
import json
from pathlib import Path
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'scripts' / 'repair_nul_jsonl.py'

class RepairNulTests(unittest.TestCase):
    def test_only_leading_nuls_removed_and_valid_bytes_preserved(self):
        self.assertTrue(SCRIPT.exists(), 'recovery utility not implemented')
        spec = importlib.util.spec_from_file_location('repair_nul_jsonl', SCRIPT)
        assert spec is not None and spec.loader is not None
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        before = b'{"a":1}\n\x00\x00{"b":2}\n\n'
        recovered, changes = mod.recover(before)
        self.assertEqual(recovered, b'{"a":1}\n{"b":2}\n\n')
        self.assertEqual(changes, [{'line': 2, 'nul_bytes_removed': 2}])
        self.assertEqual(mod.recover(recovered), (recovered, []))
        for bad in [b'\x00garbage\n', b'{"a":"x\x00y"}\n', b'\x00\n', b'{"a":1}\ntruncated', b'[]\n', b'{"a":NaN}\n', b'{"a":1,"a":2}\n']:
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                mod.recover(bad)
