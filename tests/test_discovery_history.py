import datetime as dt
import importlib.util
import json
import os
from pathlib import Path
import tempfile
import unittest

NOW=dt.datetime(2026,10,21,15,tzinfo=dt.timezone.utc)


class HistoryTests(unittest.TestCase):
    def api(self):
        self.assertIsNotNone(importlib.util.find_spec('discovery_history'),'history implementation missing')
        import discovery_history as m
        return m

    def test_history_does_not_blacklist_ticker(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'private/history.json'
            for event in ('old acceptance','new approval'):
                m.record_history(p,{'symbol':'ABC','event_date':'2026-10-21','url':'https://example.com/'+event.replace(' ','-'),'catalyst':event},now=NOW)
            h=m.read_history(p,now=NOW);self.assertEqual(len(h['entries']),2)
            self.assertNotIn('blacklist',h);self.assertNotIn('excluded_symbols',h)

    def test_history_retention_and_permissions(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'private/history.json'
            m.record_history(p,{'url':'https://example.com/old','symbol':'ABC'},now=NOW-dt.timedelta(days=8))
            m.record_history(p,{'url':'https://example.com/new','symbol':'ABC'},now=NOW)
            self.assertEqual(len(m.read_history(p,now=NOW)['entries']),1)
            self.assertEqual(p.stat().st_mode&0o777,0o600);self.assertEqual(p.parent.stat().st_mode&0o777,0o700)
            x=json.loads(p.read_text());x['entries']*=1001;p.write_text(json.dumps(x));p.chmod(0o600)
            self.assertLessEqual(len(m.read_history(p,now=NOW)['entries']),1000)

    def test_symlink_and_malformed_history_fail_closed(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'history.json';p.write_text('not json')
            with self.assertRaises(ValueError):m.read_history(p,now=NOW)
            p.unlink();target=Path(d)/'other';target.write_text('secret');p.symlink_to(target)
            with self.assertRaises((ValueError,OSError)):m.read_history(p,now=NOW)
            with self.assertRaises((ValueError,OSError)):m.record_history(p,{'url':'https://example.com'},now=NOW)
            self.assertEqual(target.read_text(),'secret')

    def test_exact_url_repeat_updates_one_entry(self):
        m=self.api()
        with tempfile.TemporaryDirectory() as d:
            p=Path(d)/'private/history.json'
            for _ in range(2):m.record_history(p,{'url':'https://example.com/new','symbol':'ABC'},now=NOW)
            self.assertEqual(len(m.read_history(p,now=NOW)['entries']),1)
