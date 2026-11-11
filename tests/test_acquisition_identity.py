"""Acquisition event identity: authentic original bundles and continuity negatives."""
import copy
import hashlib
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import opportunity_identity as identity
from earnings_identity_evidence import capture_identity_source

FIXTURES = Path(__file__).resolve().parents[1] / 'test_artifacts' / 'stage2_acquisitions'
SOURCES = {
    'acquisition_original': ('https://www.sec.gov/Archives/edgar/data/718877/000110465922005154/tm223212d3_8k.htm', '2850273c0e53db8e48fcbbb648b0012580acef499d19d04066ed9735df75f56a'),
    'acquisition_agreement': ('https://www.sec.gov/Archives/edgar/data/718877/000110465922005154/tm223212d3_ex2-1.htm', '346e26ddd959587fcf3636ee753a3f34c4000a3395ed52141d1640941a2b278f'),
    'acquisition_update': ('https://www.sec.gov/Archives/edgar/data/718877/000110465923108985/tm2328253d1_8k.htm', 'bf1b89838da823fd6fc26dff9bb92d37b8666f6a65b5ab2962a2b314fb4c0590'),
    'acquisition_letter': ('https://www.sec.gov/Archives/edgar/data/718877/000110465923082205/tm2321522d1_ex10-1.htm', 'ec387614a7fbdacf8ba6b9f18fb5142540abd04bf3447dda8001edc295eb93de'),
}


def captures(*labels, change=None):
    result=[]
    for label in labels:
        url, expected = SOURCES[label]
        path=FIXTURES/(label+'.response.raw')
        if not path.is_file():
            raise unittest.SkipTest('authentic acquisition fixture not provisioned: '+label)
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=expected:
            raise AssertionError('authentic acquisition fixture digest mismatch: '+label)
        if change is not None:
            url,raw=change(label,url,raw)
        result.append(capture_identity_source(url,raw,returned_url=url,content_type='text/html'))
    return tuple(result)


def resolve(bundle, known=()):
    return identity.resolve_event('ATVI',[],known_resolutions=known,identity_captures=bundle)


class AcquisitionIdentityTests(unittest.TestCase):
    def test_authentic_original_agreement_is_verified_not_earnings(self):
        result=resolve(captures('acquisition_original','acquisition_agreement'))
        self.assertEqual((result.status,result.family,result.period,result.version),('verified','acquisition',None,3))
        wire=identity.candidate_identity(result)
        self.assertEqual(wire['agreement']['root'],{
            'kind':'sec_original_agreement','issuer_cik':'0000718877',
            'original_report_document_id':'sec:000110465922005154/tm223212d3_8k.htm',
            'original_agreement_document_id':'sec:000110465922005154/tm223212d3_ex2-1.htm'})
        self.assertEqual(wire['agreement']['executed_on'],'2022-01-18')
        self.assertEqual(identity.candidate_identity(identity._load_binding(wire)),wire)

    def test_closing_and_modification_resolve_original_event_without_known_binding(self):
        original=resolve(captures('acquisition_original','acquisition_agreement'))
        updated=resolve(captures(*SOURCES))
        self.assertEqual(updated.status,'verified')
        self.assertEqual(updated.event_id,original.event_id)
        self.assertEqual(len(updated.documents),4)

    def test_update_first_without_original_cannot_create_event(self):
        self.assertNotEqual(resolve(captures('acquisition_update','acquisition_letter')).status,'verified')

    def test_original_missing_agreement_and_orphan_exhibit_fail_closed(self):
        for labels in [('acquisition_original',),('acquisition_agreement',)]:
            with self.subTest(labels=labels):
                self.assertNotEqual(resolve(captures(*labels)).status,'verified')

    def test_mismatched_issuer_and_execution_date_fail_closed(self):
        changes=[('acquisition_original',b'>ATVI<',b'>OTHER<'),
                 ('acquisition_agreement',b'18, 2022',b'19, 2022')]
        for target,old,new in changes:
            def change(label,url,raw):
                if label==target:
                    self.assertIn(old,raw)
                    raw=raw.replace(old,new)
                return url,raw
            with self.subTest(target=target):
                self.assertNotEqual(resolve(captures('acquisition_original','acquisition_agreement',change=change)).status,'verified')

    def test_republication_never_silently_creates_another_allowance(self):
        original=resolve(captures('acquisition_original','acquisition_agreement'))
        self.assertEqual(original.status,'verified')
        def renamed(label,url,raw):
            return url.replace('000110465922005154','000110465922005155'),raw
        result=resolve(captures('acquisition_original','acquisition_agreement',change=renamed),
                       (identity.candidate_identity(original),))
        self.assertNotEqual(result.status,'verified')

    def test_unrelated_commercial_report_cannot_hide_in_original_bundle(self):
        url='https://www.sec.gov/Archives/edgar/data/718877/000110465922005155/unresolved.htm'
        extra=capture_identity_source(url,b'<html><body>Another agreement</body></html>',returned_url=url,content_type='text/html')
        self.assertNotEqual(resolve(captures('acquisition_original','acquisition_agreement')+(extra,)).status,'verified')

    def test_explicit_predecessor_outside_opening_cannot_mint_original(self):
        def amendment(label,url,raw):
            if label=='acquisition_agreement':
                import re
                statement=b'<p>This Agreement amends and restates that certain Agreement and Plan of Merger dated as of January 17, 2022.</p>'
                raw=re.sub(b'</body>',lambda m:statement+m[0],raw,flags=re.I)
            return url,raw
        self.assertNotEqual(resolve(captures('acquisition_original','acquisition_agreement',change=amendment)).status,'verified')

    def test_partial_contradictory_issuer_fact_cannot_be_hidden(self):
        def contradicted(label,url,raw):
            if label=='acquisition_original':
                extra=b'<ix:nonNumeric name="dei:EntityRegistrantName" contextRef="contradictory">Other Issuer Inc.</ix:nonNumeric>'
                self.assertIn(b'</body>',raw.lower())
                import re
                raw=re.sub(b'</body>',lambda m:extra+m[0],raw,flags=re.I)
            return url,raw
        self.assertEqual(resolve(captures('acquisition_original','acquisition_agreement',change=contradicted)).status,'conflict')

    def test_model_dictionary_cannot_become_capture(self):
        bundle=captures('acquisition_original','acquisition_agreement')
        self.assertNotEqual(resolve(tuple(json.loads(c.canonical) for c in bundle)).status,'verified')

    def test_original_agreement_can_be_durably_retained(self):
        bundle=captures('acquisition_original','acquisition_agreement')
        result=resolve(bundle)
        self.assertEqual(result.status,'verified')
        with tempfile.TemporaryDirectory() as tmp:
            identity.retain_observations(Path(tmp),result,[],identity_captures=bundle)
            for capture in bundle:
                self.assertEqual((Path(tmp)/capture.retained_ref).read_bytes(),capture.canonical)

    def test_strict_wire_rejects_forged_root_and_reason(self):
        result=resolve(captures('acquisition_original','acquisition_agreement'))
        self.assertEqual(result.status,'verified')
        wire=identity.candidate_identity(result)
        for field,value in [('event_id','oe3:'+'0'*64),('reason','model_claim'),('period','2022-Q1')]:
            bad=copy.deepcopy(wire);bad[field]=value
            with self.subTest(field=field),self.assertRaises(ValueError):identity._load_binding(bad)
        bad=copy.deepcopy(wire);bad['agreement']['root']['original_report_document_id']='sec:000110465922005155/other.htm'
        with self.assertRaises(ValueError):identity._load_binding(bad)

    def test_earnings_serialization_keeps_existing_closed_schema(self):
        from opportunity_fixtures import synthetic_resolution
        wire=identity.candidate_identity(synthetic_resolution())
        self.assertNotIn('agreement',wire)
        self.assertEqual(identity.candidate_identity(identity._load_binding(wire)),wire)

    def test_original_transport_follows_literal_exhibit_and_policy_admits(self):
        import time
        import earnings_identity_acquisition as acquisition
        import opportunity_state as state
        import opportunity_fixtures as fixtures
        from test_earnings_identity_evidence import IdentityAcquisitionTests
        bundle=captures('acquisition_original','acquisition_agreement')
        sources={c.url:__import__('earnings_identity_evidence').identity_source_bytes(c) for c in bundle}
        helper=IdentityAcquisitionTests();calls=[]
        def opened(request,timeout):
            calls.append(request.full_url)
            return helper.response(sources[request.full_url],url=request.full_url)
        with acquisition.identity_acquisition():
            acquired=acquisition.acquire_identity_captures('ATVI',[{'url':bundle[0].url}],
                deadline=time.monotonic()+20,opener=opened)
        result=resolve(acquired)
        self.assertEqual(result.status,'verified')
        self.assertEqual(calls,[c.url for c in bundle])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixtures.make_root(root,active=True)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            decision=state.candidate_policy(state.load_policy_context(root),result,symbol='ATVI')
            self.assertEqual((decision.outcome,decision.reason),('eligible','allowance_available'))

    def test_registered_acquisition_spending_survives_closing_and_state_reload(self):
        import opportunity_state as state
        import opportunity_fixtures as fixtures
        import sqlite_ledger as storage
        bundle=captures('acquisition_original','acquisition_agreement')
        result=resolve(bundle)
        updated=resolve(captures(*SOURCES),(identity.candidate_identity(result),))
        self.assertEqual(updated.status,'verified')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixtures.make_root(root,active=True)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            identity.retain_observations(root,result,[],identity_captures=bundle)
            storage.append_jsonl(root/state.POLICY_STREAM,fixtures.policy_row('identity_resolution',resolution=identity.candidate_identity(result)))
            storage.append_jsonl(root/state.CANDIDATES_STREAM,fixtures.candidate_link('a'*64,result.event_id,state.allowance_identifier(result.event_id,0)))
            storage.append_jsonl(root/state.REVIEWS_STREAM,fixtures.review_row('a'*64,'synthetic-review',[{'decision':'HOLD'}]))
            decision=state.candidate_policy(state.load_policy_context(root),updated,symbol='ATVI')
            self.assertEqual((decision.outcome,decision.reason),('skip','unchanged_opportunity'))

    def test_radar_real_acquisition_to_durable_dossier_handoff(self):
        import alpha_radar as radar
        import opportunity_state as state
        import opportunity_fixtures as fixtures
        import subprocess
        from contextlib import ExitStack
        from test_earnings_identity_evidence import IdentityAcquisitionTests
        helper=IdentityAcquisitionTests()
        bundle=captures('acquisition_original','acquisition_agreement')
        sources={c.url:__import__('earnings_identity_evidence').identity_source_bytes(c) for c in bundle}
        scouts=[{'symbol':'ATVI','urls':[bundle[0].url,'https://news.example/replay'],
                 'event_date':'2026-11-04','catalyst':'Synthetic replay of historical original agreement'}]
        pages=[{'url':bundle[0].url,'title':'Agreement','text':'Readable primary'},
               {'url':'https://news.example/replay','title':'News','text':'Readable corroboration'}]
        synthesized=[]
        def opened(request,timeout):return helper.response(sources[request.full_url],url=request.full_url)
        def synthesize(cfg,selected,evidence,deadline,**kwargs):
            synthesized.append(selected['symbol']);return {'symbol':'ATVI'}
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            root=Path(tmp);fixtures.make_root(root,active=True)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            for name,options in [('ROOT',{'new':root}),('safe_urlopen',{'side_effect':opened}),
                ('scout_parse_result',{'return_value':(copy.deepcopy(scouts),{'reason':'ok'})}),
                ('discovery_command',{'return_value':['synthetic']}),
                ('gather_evidence',{'return_value':copy.deepcopy(pages)}),
                ('sec_filing_date_for_url',{'return_value':None}),
                ('filter_evidence',{'side_effect':lambda p:(p,[])}),
                ('recover_publications',{'side_effect':lambda c,p,*a,**k:(p,[])}),
                ('synthesize_candidate',{'side_effect':synthesize})]:
                stack.enter_context(patch.object(radar,name,**options))
            stack.enter_context(patch.object(radar.subprocess,'run',return_value=subprocess.CompletedProcess([],0,'{}','')))
            result=radar.live_research({'focused_retrieval_enabled':False},intake=lambda c:c)
            self.assertEqual(result['opportunity_identity']['family'],'acquisition')
            self.assertEqual(result['allowance_id'],state.allowance_identifier(result['event_id'],0))
            self.assertIn(result['event_id'],state.load_index(root).resolutions)
            for doc in result['opportunity_identity']['documents']:
                self.assertTrue((root/doc['retained_ref']).is_file())
        self.assertEqual(synthesized,['ATVI'])

    def test_deserialized_shape_is_not_prospective_source_authority(self):
        import opportunity_state as state
        import opportunity_fixtures as fixtures
        acquired=resolve(captures('acquisition_original','acquisition_agreement'))
        shape=identity._load_binding(identity.candidate_identity(acquired))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixtures.make_root(root,active=True)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            decision=state.candidate_policy(state.load_policy_context(root),shape,symbol='ATVI')
            self.assertEqual((decision.outcome,decision.reason),('unknown','opportunity_identity_unknown'))

    def test_new_acquisition_prospective_policy(self):
        import opportunity_state as state
        import opportunity_fixtures as fixtures
        result=resolve(captures('acquisition_original','acquisition_agreement'))
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);fixtures.make_root(root,active=True)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            decision=state.candidate_policy(state.load_policy_context(root),result,symbol='ATVI')
            self.assertEqual((decision.outcome,decision.reason),('eligible','allowance_available'))

    def test_explicit_same_party_same_day_independence_is_order_independent(self):
        original_bundle=captures('acquisition_original','acquisition_agreement')
        original=resolve(original_bundle)
        original_url=original_bundle[1].url
        def independent(label,url,raw):
            url=url.replace('000110465922005154','000110465922005157')
            if label=='acquisition_agreement':
                paragraph=('<p>This Agreement is separate from and independent of the agreement incorporated by reference at '
                           '<a href="'+original_url+'">'+original_url+'</a>.</p>').encode()
                import re
                raw=re.sub(b'</body>',lambda m:paragraph+m[0],raw,flags=re.I)
            return url,raw
        independent_bundle=captures('acquisition_original','acquisition_agreement',change=independent)
        newer=resolve(independent_bundle,(identity.candidate_identity(original),))
        self.assertEqual(newer.status,'verified')
        self.assertNotEqual(newer.event_id,original.event_id)
        reverse=resolve(original_bundle,(identity.candidate_identity(newer),))
        self.assertEqual(reverse.status,'verified')
        self.assertEqual(reverse.event_id,original.event_id)

    def test_pre_baseline_original_blocks_new_accession_allowance(self):
        """Dropping pre-baseline known roots must not pass this test."""
        import opportunity_cutover as cutover
        import opportunity_state as state
        import sqlite_ledger as storage
        original=resolve(captures('acquisition_original','acquisition_agreement'))
        def accession(label,url,raw):
            return url.replace('000110465922005154','000110465924009999'),raw.replace(b'000110465922005154',b'000110465924009999')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            from tests import opportunity_fixtures as fixtures
            fixtures.make_root(root,active=False)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            storage.append_jsonl(root/state.POLICY_STREAM,fixtures.policy_row('identity_resolution',resolution=identity.candidate_identity(original)))
            manifest=cutover.prepare_manifest(root)
            cutover.activate_prospective(root,manifest,approved_manifest_sha256=cutover.manifest_digest(manifest))
            context=state.load_policy_context(root)
            replay=resolve(captures('acquisition_original','acquisition_agreement',change=accession),
                           tuple(identity.candidate_identity(value) for value in (*context.index.resolutions.values(),*context.index.historical_resolutions)))
            decision=state.candidate_policy(context,replay,symbol='ATVI')
            self.assertNotEqual(replay.status,'verified')
            self.assertNotEqual((decision.outcome,decision.reason),('eligible','allowance_available'))

    def test_registered_shape_without_retained_source_cannot_enter(self):
        """A stored identity shape must not authorize entry by itself."""
        import opportunity_cutover as cutover
        import opportunity_state as state
        import sqlite_ledger as storage
        acquired=resolve(captures('acquisition_original','acquisition_agreement'))
        wire=identity.candidate_identity(acquired)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            from tests import opportunity_fixtures as fixtures
            fixtures.make_root(root,active=False)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            manifest=cutover.prepare_manifest(root)
            cutover.activate_prospective(root,manifest,approved_manifest_sha256=cutover.manifest_digest(manifest))
            storage.append_jsonl(root/state.POLICY_STREAM,fixtures.policy_row('identity_resolution',resolution=wire))
            loaded=identity._load_binding(wire)
            research=state.candidate_policy(state.load_policy_context(root),loaded,symbol='ATVI')
            context=state.load_policy_context(root)
            entry=state.require_current_allowance(root,{
                'symbol':'ATVI','opportunity_identity':wire,'event_id':loaded.event_id,
                'allowance_id':state.allowance_identifier(loaded.event_id,0),
                'opportunity_baseline_id':context.index.prospective_baseline['baseline_id']})
            self.assertEqual((research.outcome,entry.outcome),('unknown','unknown'))

    def test_retained_source_proof_survives_reload_and_authorizes_once(self):
        import opportunity_cutover as cutover
        import opportunity_state as state
        import sqlite_ledger as storage
        bundle=captures('acquisition_original','acquisition_agreement')
        acquired=resolve(bundle)
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            from tests import opportunity_fixtures as fixtures
            fixtures.make_root(root,active=False)
            (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
            identity.retain_observations(root,acquired,[],identity_captures=bundle)
            manifest=cutover.prepare_manifest(root)
            cutover.activate_prospective(root,manifest,approved_manifest_sha256=cutover.manifest_digest(manifest))
            storage.append_jsonl(root/state.POLICY_STREAM,fixtures.policy_row('identity_resolution',resolution=identity.candidate_identity(acquired)))
            context=state.load_policy_context(root)
            loaded=context.index.resolutions[acquired.event_id]
            decision=state.candidate_policy(context,loaded,symbol='ATVI')
            self.assertEqual((decision.outcome,decision.reason),('eligible','allowance_available'))

    def test_different_independent_agreement_can_pass_without_reopening_original(self):
        original=resolve(captures('acquisition_original','acquisition_agreement'))
        def separate(label,url,raw):
            # Synthetic independent buyer/vehicle/date; never a historical claim.
            return (url.replace('000110465922005154','000110465922005156'),
                    raw.replace(b'Microsoft',b'Example Buyer').replace(b'MICROSOFT',b'EXAMPLE BUYER')
                    .replace(b'Anchorage',b'Example Vehicle').replace(b'ANCHORAGE',b'EXAMPLE VEHICLE')
                    .replace(b'18, 2022',b'20, 2022'))
        result=resolve(captures('acquisition_original','acquisition_agreement',change=separate),
                       (identity.candidate_identity(original),))
        self.assertEqual(result.status,'verified')
        self.assertNotEqual(result.event_id,original.event_id)
