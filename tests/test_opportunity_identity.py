"""Synthetic deterministic opportunity identity contracts."""
import copy
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import tempfile
from unittest.mock import patch
import unittest
from retained_article import retain_article
import opportunity_identity as identity
from opportunity_fixtures import URL, make_root


def edited(pages, old, new):
    page = pages[0]
    return [retain_article(page, page['_retained_article']['text'].replace(old, new))]

from opportunity_fixtures import earnings_pages
from opportunity_identity import resolve_event


class IdentityTests(unittest.TestCase):
    def test_changed_representation_does_not_change_report_identity(self):
        a = resolve_event('ACME', earnings_pages(), known_resolutions=())
        b = resolve_event('ACME', earnings_pages(representation='changed'), known_resolutions=())
        self.assertEqual((a.status, b.status), ('verified', 'verified'))
        self.assertEqual(a.event_id, b.event_id)
        c = resolve_event('ACME', earnings_pages(period='2026-Q2'), known_resolutions=())
        self.assertEqual(c.status, 'verified')
        self.assertNotEqual(a.event_id, c.event_id)

    def test_identifier_and_cover_fail_closed_matrix(self):
        pages = earnings_pages()
        invalid = [
            edited(pages, '>ACME<', '>OTHER<'),
            edited(pages, '>0001999999<', '>1999999<'),
            edited(pages, '>0001999999<', '> 0001999999 <'),
            edited(pages, '>ACME<', '> ACME <'),
            edited(pages, '>Q3<', '> Q3 <'),
            edited(pages, '>Fictional Acme Laboratory Inc.<', '> Fictional Acme Laboratory Inc. <'),
            edited(pages, '>2026-09-30<', '>2026-02-31<'),
            edited(pages, 'http://www.sec.gov/CIK', 'https://untrusted.test/CIK'),
            edited(pages, '</body></html>', ''),
            edited(pages, 'contextRef="current"', 'contextRef="comparative"'),
            edited(pages, 'dei:DocumentType', 'untrusted:DocumentType'),
            edited(pages, '<ix:nonNumeric', '<footer><ix:nonNumeric'),
        ]
        for index, rows in enumerate(invalid):
            with self.subTest(index=index):
                self.assertNotEqual(resolve_event('ACME', rows, known_resolutions=()).status, 'verified')
        for symbol in ('acme', ' ACME', 'ACME ', '', None):
            self.assertEqual(resolve_event(symbol, pages, known_resolutions=()).status, 'unknown')
        for url in (URL.replace('/1999999/', '/01999999/'), URL + '?changed=1', URL.replace('https:', 'http:'),
                    URL.replace('000199999926000001', '000188888826000001')):
            page = {**pages[0], 'url':url, 'returned_url':url}
            page = retain_article(page, pages[0]['_retained_article']['text'])
            self.assertNotEqual(resolve_event('ACME', [page], known_resolutions=()).status, 'verified')

    def test_models_dates_and_unsupported_captures_cannot_bind(self):
        page = {'url':'https://issuer.test/results', 'text':'Next earnings 2026-Q3; exit 2026-10-21',
                'title':'2026-Q3 results', 'published_at':'2026-10-21',
                'event_id':'oe1:' + 'a'*64, 'cik':'0001999999', 'period':'2026-Q3'}
        for rows in ([page], [retain_article(page, page['text'])], [{**earnings_pages()[0], '_retained_article':{}}]):
            self.assertEqual(resolve_event('ACME', rows, known_resolutions=()).status, 'unknown')
        unsupported = edited(earnings_pages(), '>10-Q<', '>8-K<')
        self.assertEqual(resolve_event('ACME', unsupported, known_resolutions=()).status, 'unknown')

    def test_comparative_footer_and_next_period_do_not_supply_current_support(self):
        pages = earnings_pages()
        raw = pages[0]['_retained_article']['text']
        for closing in ('<footer>2027-Q1 next earnings; 2025-Q3 comparative</footer></body></html>',
                        '<p>Prior year 2025-Q3; planned exit 2027-01-01</p></body></html>'):
            rows = edited(pages, '</body></html>', closing)
            self.assertEqual(resolve_event('ACME', rows, known_resolutions=()).period, '2026-Q3')
        only_period = edited(pages, 'dei:DocumentFiscalPeriodFocus', 'not:DocumentFiscalPeriodFocus')
        self.assertEqual(resolve_event('ACME', only_period, known_resolutions=()).status, 'unknown')

    def test_same_filing_multiple_subjects_conflict(self):
        rows = earnings_pages() + earnings_pages(period='2026-Q2')
        self.assertEqual(resolve_event('ACME', rows, known_resolutions=()).status, 'conflict')
        original = earnings_pages()[0]
        second_raw = earnings_pages(period='2026-Q2')[0]['_retained_article']['text']
        multi = retain_article(original, original['_retained_article']['text'].replace('</body></html>',
                               second_raw.replace('current', 'other').removeprefix('<html><body>').removesuffix('</body></html>') + '</body></html>'))
        self.assertEqual(resolve_event('ACME', [multi], known_resolutions=()).status, 'conflict')

    def test_source_order_secondary_membership_and_new_primary_locator_do_not_reset(self):
        pages = earnings_pages()
        expected = resolve_event('ACME', pages, known_resolutions=()).event_id
        secondary = retain_article({'url':'https://secondary.test/new', 'title':'Other title',
                                    'text':'Secondary synthetic prose'}, 'Secondary synthetic prose')
        other = {**pages[0], 'url':URL.replace('000001/', '000002/'), 'returned_url':URL.replace('000001/', '000002/')}
        other = retain_article(other, pages[0]['_retained_article']['text'])
        for rows in (pages + [secondary], [secondary] + pages, [other]):
            self.assertEqual(resolve_event('ACME', rows, known_resolutions=()).event_id, expected)

    def test_mixed_unresolved_primary_never_becomes_old_verified_event(self):
        good = earnings_pages()
        missing = {**earnings_pages(period='2026-Q2')[0]}
        missing.pop('_retained_article')
        for rows in (good + [missing], [missing] + good,
                     good + edited(earnings_pages(), '>10-Q<', '>8-K<')):
            self.assertEqual(resolve_event('ACME', rows, known_resolutions=()).status, 'unknown')

    def test_changed_registered_mutable_alias_cannot_be_hidden_by_old_filing(self):
        pages = earnings_pages()
        known = identity.candidate_identity(resolve_event('ACME', pages, known_resolutions=()))
        mutable = retain_article({'url':'https://issuer.test/release', 'title':'Release', 'text':'Release'}, 'Release')
        known['documents'].append(dict(known['documents'][0], document_id='url:' + mutable['url'],
            url=mutable['url'], returned_url=mutable['url'], content_sha256=mutable['_retained_article']['projection_sha256'],
            publication_value='', precision='', retained_ref=identity._capture_ref(mutable)))
        changed = retain_article(mutable, 'Changed release')
        self.assertEqual(resolve_event('ACME', pages + [changed], known_resolutions=(known,)).status, 'unknown')

    def test_foreign_context_scheme_and_outside_html_facts_cannot_bind(self):
        pages = earnings_pages()
        for rows in (edited(pages, '<html><body>', ''),
                     edited(pages, 'dei:DocumentFiscalYearFocus" contextRef="current">2026',
                            'dei:DocumentFiscalYearFocus" contextRef="current">0000')):
            self.assertNotEqual(resolve_event('ACME', rows, known_resolutions=()).status, 'verified')

    def test_known_binding_alias_collision_is_not_first_record_wins(self):
        first = identity.candidate_identity(resolve_event('ACME', earnings_pages(), known_resolutions=()))
        second = identity.candidate_identity(resolve_event('ACME', earnings_pages(period='2026-Q2'), known_resolutions=()))
        unknown = edited(earnings_pages(), 'dei:DocumentFiscalPeriodFocus', 'other:Period')
        for records in ((first,second), (second,first)):
            self.assertEqual(resolve_event('ACME', unknown, known_resolutions=records).status, 'conflict')

    def test_unknown_serialization_is_bounded_and_contains_no_model_text(self):
        result = resolve_event('ACME', [], known_resolutions=())
        data = identity.candidate_identity(result)
        self.assertEqual((data['event_id'],data['issuer'],data['documents']), (None,None,[]))
        with self.assertRaises(ValueError):identity.candidate_identity({'status':'verified'})

    def test_malformed_sec_locator_cannot_be_a_secondary_alias(self):
        pages = earnings_pages()
        malformed = {**pages[0], 'url':URL + '?unvalidated=1', 'returned_url':URL + '?unvalidated=1'}
        malformed = retain_article(malformed, pages[0]['_retained_article']['text'])
        self.assertEqual(resolve_event('ACME', pages + [malformed], known_resolutions=()).status, 'unknown')

    def test_publication_metadata_must_agree_with_validated_observation(self):
        from publication_observation import build_observation
        pages = earnings_pages()
        page = pages[0]
        raw = page['_retained_article']['text'].replace('<html>', '<html><meta property="article:published_time" content="2026-10-21T10:00:00+00:00">')
        page = retain_article({**page, 'published_at':'2026-10-21T10:00:00+00:00', 'publication_precision':'second'}, raw)
        observation = build_observation(page, value=page['published_at'], precision='instant', basis='structured_metadata',
                                        support=page['published_at'], location='article metadata')
        self.assertIsNotNone(observation)
        page['publication_observation'] = observation
        self.assertEqual(resolve_event('ACME', [page], known_resolutions=()).status, 'verified')
        page['published_at'] = '2026-10-20T10:00:00+00:00'
        self.assertEqual(resolve_event('ACME', [page], known_resolutions=()).status, 'unknown')

    def test_legacy_publication_day_keeps_original_midnight_spelling(self):
        from publication_observation import build_observation
        page = earnings_pages()[0]
        raw = page['_retained_article']['text'].replace('<html>', '<html><meta property="article:published_time" content="2026-10-21">')
        page = retain_article({**page, 'published_at':'2026-10-21T00:00:00Z'}, raw)
        page['publication_observation'] = build_observation(page, value='2026-10-21', precision='day',
            basis='structured_metadata', support='2026-10-21', location='article metadata')
        self.assertIsNotNone(page['publication_observation'])
        result = resolve_event('ACME', [page], known_resolutions=())
        self.assertEqual(result.status, 'verified')
        self.assertEqual(identity.candidate_identity(result)['documents'][0]['publication_value'], '2026-10-21T00:00:00Z')
        for value,precision in ((True,'day'), ('not-a-date','day'), ('2026-10-21','year')):
            bad = dict(earnings_pages()[0], published_at=value, publication_precision=precision)
            self.assertEqual(resolve_event('ACME', [bad], known_resolutions=()).status, 'unknown')

    def test_serialized_bindings_reject_nested_unknown_keys_and_nonfinite_shapes(self):
        record = identity.candidate_identity(resolve_event('ACME', earnings_pages(), known_resolutions=()))
        bad_records = []
        for field in record:
            bad_records.append({k:v for k,v in record.items() if k != field})
        for key,value in [('retained_ref','../../escape'), ('content_sha256','A'*64), ('precision','year'),
                          ('publication_value','not-a-day'), ('document_id','sec:repaired'), ('extra','field')]:
            bad = copy.deepcopy(record)
            bad['documents'][0][key] = value
            bad_records.append(bad)
        for value in (None, {}, 'not-documents', [None]):
            bad_records.append({**record, 'documents':value})
        for bad in bad_records:
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):resolve_event('ACME', [], known_resolutions=(bad,))

    def test_reviewed_binding_only_fills_absent_support_not_invalid_current_facts(self):
        pages = earnings_pages()
        known = identity.candidate_identity(resolve_event('ACME', pages, known_resolutions=()))
        for rows in (edited(pages, '>Q3<', '>QQ<'), edited(pages, '>10-Q<', '>8-K<'),
                     edited(pages, '>2026-09-30<', '>2026-02-31<')):
            with self.subTest(raw=rows[0]['_retained_article']['sha256']):
                self.assertEqual(resolve_event('ACME', rows, known_resolutions=(known,)).status, 'unknown')

    def test_resolution_collections_are_defensive_and_unresolved_cannot_carry_documents(self):
        result = resolve_event('ACME', earnings_pages(), known_resolutions=())
        docs, refs = list(result.documents), list(result.support_refs)
        copied = replace(result, documents=docs, support_refs=refs)
        docs.clear()
        refs.clear()
        self.assertEqual(copied, result)
        unknown = resolve_event('ACME', [], known_resolutions=())
        with self.assertRaises(ValueError):identity.candidate_identity(replace(unknown, documents=result.documents))

    def test_explicit_binding_serialization_and_historical_missing_markup(self):
        resolved = resolve_event('ACME', earnings_pages(), known_resolutions=())
        binding = identity.candidate_identity(resolved)
        self.assertEqual(set(binding), {'version','status','event_id','issuer','family','period','documents','support_refs','reason'})
        self.assertEqual(binding['version'], 1)
        historical = edited(earnings_pages(), 'dei:DocumentFiscalPeriodFocus', 'not:DocumentFiscalPeriodFocus')
        self.assertEqual(resolve_event('ACME', historical, known_resolutions=(binding,)).event_id, resolved.event_id)
        self.assertEqual(identity.candidate_identity(resolved), binding)
        binding['documents'][0]['url'] = 'mutated'
        self.assertNotEqual(identity.candidate_identity(resolved), binding)

    def test_bad_known_records_raise_instead_of_becoming_empty(self):
        record = identity.candidate_identity(resolve_event('ACME', earnings_pages(), known_resolutions=()))
        for bad in ({}, {**record, 'version':True}, {**record, 'event_id':'invented'},
                    {**record, 'unexpected':True}, {**record, 'family':'merger'},
                    {**record, 'issuer':{**record['issuer'], 'cik':'1999999'}}):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError):resolve_event('ACME', earnings_pages(), known_resolutions=(bad,))
        with self.assertRaises(ValueError):resolve_event('ACME', earnings_pages(), known_resolutions=[])

    def test_mutable_alias_requires_exact_capture_and_cannot_hide_new_period(self):
        pages = earnings_pages()
        known = identity.candidate_identity(resolve_event('ACME', pages, known_resolutions=()))
        mutable = {'url':'https://issuer.test/results?exact=1', 'returned_url':'https://issuer.test/results?exact=1',
                   'title':'Synthetic earnings release', 'text':'Synthetic issuer release'}
        mutable = retain_article(mutable, '<article>Synthetic issuer release</article>')
        alias = dict(known['documents'][0], document_id='url:' + mutable['url'], url=mutable['url'],
                     returned_url=mutable['url'], content_sha256=mutable['_retained_article']['projection_sha256'],
                     retained_ref=identity._capture_ref(mutable))
        known['documents'].append(alias)
        self.assertEqual(resolve_event('ACME', [mutable], known_resolutions=(known,)).event_id, known['event_id'])
        changed = retain_article(mutable, '<article>Changed issuer release</article>')
        self.assertEqual(resolve_event('ACME', [changed], known_resolutions=(known,)).status, 'unknown')
        self.assertEqual(resolve_event('ACME', earnings_pages(period='2026-Q2'), known_resolutions=(known,)).status, 'conflict')

    def test_known_capture_can_explicitly_disambiguate_period_but_not_wrong_issuer(self):
        pages = earnings_pages()
        raw = pages[0]['_retained_article']['text']
        multi = retain_article(pages[0], raw.replace('</body></html>', raw.replace('current', 'prior').replace('>Q3<', '>Q2<').removeprefix('<html><body>').removesuffix('</body></html>') + '</body></html>'))
        known = identity.candidate_identity(resolve_event('ACME', pages, known_resolutions=()))
        previous = known['documents'][0]['retained_ref']
        known['documents'][0]['retained_ref'] = identity._capture_ref(multi)
        known['issuer']['support_ref'] = known['issuer']['support_ref'].replace(previous, identity._capture_ref(multi))
        known['support_refs'] = [known['issuer']['support_ref']]
        result = resolve_event('ACME', [multi], known_resolutions=(known,))
        self.assertEqual(result.event_id, known['event_id'])
        wrong = edited([multi], '>ACME<', '>OTHER<')
        known['issuer']['support_ref'] = known['issuer']['support_ref'].replace(identity._capture_ref(multi), identity._capture_ref(wrong[0]))
        known['support_refs'] = [known['issuer']['support_ref']]
        known['documents'][0]['retained_ref'] = identity._capture_ref(wrong[0])
        self.assertEqual(resolve_event('ACME', wrong, known_resolutions=(known,)).status, 'conflict')


class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = make_root(Path(self.temporary.name))
        self.pages = earnings_pages()
        self.resolution = resolve_event('ACME', self.pages, known_resolutions=())

    def test_explicit_retention_is_private_atomic_and_idempotent(self):
        self.assertFalse((self.root / 'private/opportunity_evidence').exists())
        result = identity.retain_observations(self.root, self.resolution, self.pages)
        self.assertEqual(result, self.resolution)
        document = result.documents[0]
        target = self.root / document.retained_ref
        raw = target.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(), target.stem)
        self.assertEqual(json.loads(raw), self.pages[0]['_retained_article'])
        self.assertEqual(target.stat().st_mode & 0o777, 0o600)
        self.assertEqual(target.parent.stat().st_mode & 0o777, 0o700)
        self.assertEqual(target.stat().st_nlink, 1)
        before = (target.stat().st_ino, target.stat().st_mtime_ns)
        identity.retain_observations(self.root, result, self.pages)
        self.assertEqual((target.stat().st_ino, target.stat().st_mtime_ns), before)
        self.assertEqual(list(target.parent.iterdir()), [target])
        self.assertNotEqual(document.content_sha256, self.pages[0]['_retained_article']['sha256'])

    def test_lookup_and_serialization_are_read_only(self):
        with patch('builtins.open', side_effect=AssertionError('no I/O')), patch('os.open', side_effect=AssertionError('no I/O')):
            result = resolve_event('ACME', self.pages, known_resolutions=())
            identity.candidate_identity(result)
        self.assertFalse((self.root / 'private/opportunity_evidence').exists())

    def test_retention_rejects_tamper_and_missing_or_oversized_capture(self):
        changed = copy.deepcopy(self.pages)
        changed[0]['_retained_article']['text'] += 'tampered'
        oversized = retain_article(self.pages[0], 'x' * 85001)
        for rows in ([], changed, [oversized]):
            with self.subTest(rows=len(rows)):
                with self.assertRaises((ValueError, OSError)):
                    identity.retain_observations(self.root, self.resolution, rows)
        self.assertFalse((self.root / 'private/opportunity_evidence').exists())
        forged = replace(self.resolution, documents=(replace(self.resolution.documents[0], retained_ref='../outside'),))
        with self.assertRaises(ValueError):identity.retain_observations(self.root, forged, self.pages)

    def test_symlinks_hardlinks_permissions_and_collisions_fail_closed(self):
        import os
        evidence = self.root / 'private/opportunity_evidence'
        outside = self.root / 'outside'
        outside.mkdir(mode=0o700)
        evidence.symlink_to(outside, target_is_directory=True)
        with self.assertRaises(OSError):identity.retain_observations(self.root, self.resolution, self.pages)
        evidence.unlink()
        identity.retain_observations(self.root, self.resolution, self.pages)
        target = self.root / self.resolution.documents[0].retained_ref
        original = target.read_bytes()
        for mode in ('symlink','hardlink','collision','permissions'):
            with self.subTest(mode=mode):
                target.unlink()
                if mode == 'symlink':target.symlink_to(self.root / 'autonomy_config.json')
                elif mode == 'hardlink':os.link(self.root / 'autonomy_config.json', target)
                else:
                    target.write_bytes(original if mode == 'permissions' else b'collision')
                    target.chmod(0o644 if mode == 'permissions' else 0o600)
                with self.assertRaises((ValueError,OSError)):
                    identity.retain_observations(self.root, self.resolution, self.pages)
        target.unlink()
        evidence.chmod(0o755)
        with self.assertRaises(OSError):identity.retain_observations(self.root, self.resolution, self.pages)

    def test_fsync_failure_never_returns_receipts_and_cleans_staging(self):
        with patch('os.fsync', side_effect=OSError('synthetic durability failure')):
            with self.assertRaises(OSError):identity.retain_observations(self.root, self.resolution, self.pages)
        evidence = self.root / 'private/opportunity_evidence'
        if evidence.exists():self.assertEqual(list(evidence.iterdir()), [])

    def test_root_and_private_symlinks_are_not_followed(self):
        with tempfile.TemporaryDirectory() as parent:
            link = Path(parent) / 'link'
            link.symlink_to(self.root, target_is_directory=True)
            with self.assertRaises(OSError):identity.retain_observations(link, self.resolution, self.pages)
            self.assertFalse((self.root / 'private/opportunity_evidence').exists())

    def test_staging_file_and_directory_fsync_failures_never_acknowledge(self):
        import os
        evidence = self.root / 'private/opportunity_evidence'
        evidence.mkdir(mode=0o700)
        real_fsync = os.fsync
        for phase in ('file','directory'):
            def fail(fd):
                import stat
                if ((stat.S_ISREG(os.fstat(fd).st_mode) and phase == 'file')
                    or (phase == 'directory' and os.fstat(fd).st_ino == evidence.stat().st_ino)):
                    raise OSError('synthetic ' + phase + ' fsync failure')
                return real_fsync(fd)
            with self.subTest(phase=phase), patch('os.fsync', side_effect=fail):
                with self.assertRaises(OSError):identity.retain_observations(self.root, self.resolution, self.pages)
            self.assertFalse(any(p.name.startswith('.capture-') for p in evidence.iterdir()))
            for p in evidence.iterdir():p.unlink()

    def test_retry_after_directory_fsync_failure_reestablishes_durability(self):
        import os
        evidence = self.root / 'private/opportunity_evidence'
        evidence.mkdir(mode=0o700)
        real_fsync = os.fsync
        calls = []
        def fail_directory(fd):
            import stat
            if os.fstat(fd).st_ino == evidence.stat().st_ino:raise OSError('directory failure')
            return real_fsync(fd)
        with patch('os.fsync', side_effect=fail_directory):
            with self.assertRaises(OSError):identity.retain_observations(self.root, self.resolution, self.pages)
        def record_fsync(fd):
            import stat
            calls.append('directory' if stat.S_ISDIR(os.fstat(fd).st_mode) else 'file')
            return real_fsync(fd)
        with patch('os.fsync', side_effect=record_fsync):
            identity.retain_observations(self.root, self.resolution, self.pages)
        self.assertIn('directory', calls)
        self.assertIn('file', calls)

    def test_partial_directory_creation_failure_is_fsynced_on_retry(self):
        import os
        real_fsync = os.fsync
        private_inode = (self.root / 'private').stat().st_ino
        def fail(fd):
            if os.fstat(fd).st_ino == private_inode:raise OSError('parent fsync failure')
            return real_fsync(fd)
        # The first mkdir becomes visible, but its parent fsync fails.
        with patch('os.fsync', side_effect=fail):
            with self.assertRaises(OSError):identity.retain_observations(self.root, self.resolution, self.pages)
        evidence = self.root / 'private/opportunity_evidence'
        self.assertTrue(evidence.exists())
        calls = []
        def fsync(fd):
            calls.append(os.fstat(fd).st_ino)
            return real_fsync(fd)
        with patch('os.fsync', side_effect=fsync):
            identity.retain_observations(self.root, self.resolution, self.pages)
        self.assertIn(private_inode, calls)

    def test_fixture_root_activation_uses_canonical_floor(self):
        from opportunity_activation import activation_version
        self.assertEqual(activation_version(self.root), 0)
        self.assertEqual(json.loads((self.root / 'autonomy_config.json').read_text()), {'enabled':False, 'broker_mode':'paper'})
        with tempfile.TemporaryDirectory() as path:
            active = make_root(Path(path), active=True)
            self.assertEqual(activation_version(active), 1)


class ReceiptProvenanceTests(unittest.TestCase):
    def test_receipt_preserves_raw_and_projection_digests_without_article_copy(self):
        from alpha_radar import build_source_receipts
        page = earnings_pages()[0]
        receipt = build_source_receipts([page])[0]
        self.assertEqual(receipt['content_sha256'], page['_retained_article']['projection_sha256'])
        self.assertEqual(receipt['representation_sha256'], page['_retained_article']['sha256'])
        self.assertEqual(receipt['returned_url'], page['returned_url'])
        self.assertEqual(receipt['retained_ref'], identity._capture_ref(page))
        self.assertNotIn('text', receipt)
        self.assertNotIn('_retained_article', receipt)
        broken = copy.deepcopy(page)
        broken['_retained_article']['text'] += 'tampered'
        self.assertNotIn('retained_ref', build_source_receipts([broken])[0])
