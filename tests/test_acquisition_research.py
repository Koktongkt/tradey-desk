"""Acquisition observations are inert research, never event/entry authority."""
import copy
import datetime as dt
import hashlib
import importlib
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from earnings_identity_evidence import capture_identity_source

FIXTURES=Path(__file__).resolve().parents[1]/'test_artifacts/stage2_acquisitions'
SOURCES={
 'acquisition_original':('https://www.sec.gov/Archives/edgar/data/718877/000110465922005154/tm223212d3_8k.htm','2850273c0e53db8e48fcbbb648b0012580acef499d19d04066ed9735df75f56a'),
 'acquisition_agreement':('https://www.sec.gov/Archives/edgar/data/718877/000110465922005154/tm223212d3_ex2-1.htm','346e26ddd959587fcf3636ee753a3f34c4000a3395ed52141d1640941a2b278f'),
 'acquisition_update':('https://www.sec.gov/Archives/edgar/data/718877/000110465923108985/tm2328253d1_8k.htm','bf1b89838da823fd6fc26dff9bb92d37b8666f6a65b5ab2962a2b314fb4c0590'),
 'acquisition_letter':('https://www.sec.gov/Archives/edgar/data/718877/000110465923082205/tm2321522d1_ex10-1.htm','ec387614a7fbdacf8ba6b9f18fb5142540abd04bf3447dda8001edc295eb93de')}
STAMP='2026-11-11T07:00:00+00:00'
KEYS={'record_type','schema_version','observed_at','lead_id','symbol','issuer_cik','status','evidence_status','capture_refs','reason'}


def bundle(*names):
 result=[]
 for name in names or SOURCES:
  url,digest=SOURCES[name];raw=(FIXTURES/(name+'.response.raw')).read_bytes()
  assert hashlib.sha256(raw).hexdigest()==digest
  result.append(capture_identity_source(url,raw,returned_url=url,content_type='text/html'))
 return tuple(result)


class AcquisitionResearchTests(unittest.TestCase):
 def module(self):
  self.assertIsNotNone(importlib.util.find_spec('acquisition_research'),'research-only observation module is missing')
  return importlib.import_module('acquisition_research')

 def root(self):
  return Path(self.enterContext(tempfile.TemporaryDirectory()))

 def publish(self,root,captures=None,status='retained'):
  return self.module().publish_lead(root,symbol='ATVI',captures=bundle() if captures is None else captures,
                                    evidence_status=status,observed_at=STAMP)

 def test_authentic_chain_publishes_closed_private_observation_only(self):
  mod=self.module();root=self.root();caps=bundle();record=self.publish(root,caps)
  self.assertEqual(set(record),KEYS)
  self.assertEqual((record['status'],record['reason'],record['issuer_cik']),('research_only','explicit_binding_required','0000718877'))
  self.assertEqual(record['capture_refs'],sorted(c.retained_ref for c in caps))
  self.assertRegex(record['lead_id'],r'^al1:[0-9a-f]{64}$')
  self.assertEqual(mod.read_lead(root,record['lead_id']),record)
  self.assertEqual(self.publish(root,caps),record)
  self.assertEqual(len(list((root/'private/acquisition_research').glob('*.json'))),1)
  self.assertEqual(os.stat(root/'private/acquisition_research').st_mode&0o777,0o700)
  for c in caps:self.assertEqual((root/c.retained_ref).read_bytes(),c.canonical)
  for p in (root/'private').rglob('*.json'):self.assertEqual(p.stat().st_mode&0o777,0o600)
  self.assertFalse((root/'private/opportunity_policy.jsonl').exists())

 def test_partial_and_unavailable_are_honest_and_invalid_capture_is_not_coerced(self):
  root=self.root();mod=self.module()
  for caps,status in [((), 'unavailable'),(bundle('acquisition_original'),'partial')]:
   record=self.publish(root,caps,status);self.assertEqual(mod.read_lead(root,record['lead_id'])['evidence_status'],status)
  for caps,status in [((),'retained'),(bundle(),'unavailable'),(({},),'partial')]:
   with self.subTest(status=status),self.assertRaises(ValueError):self.publish(root,caps,status)

 def test_record_and_referenced_capture_tampering_are_rejected(self):
  mod=self.module();root=self.root();record=self.publish(root)
  path=root/'private/acquisition_research'/(record['lead_id'][4:]+'.json')
  raw=path.read_bytes();bad=copy.deepcopy(record);bad['event_id']='oe3:'+'a'*64
  path.write_text(json.dumps(bad))
  with self.assertRaises((ValueError,OSError)):mod.read_lead(root,record['lead_id'])
  path.write_bytes(raw)
  capture=root/record['capture_refs'][0];before=capture.read_bytes();capture.write_bytes(before+b' ')
  with self.assertRaises((ValueError,OSError)):mod.read_lead(root,record['lead_id'])

 def test_unsafe_files_and_ancestors_never_restore_a_research_record(self):
  mod=self.module()
  for attack in ['mode','hardlink','symlink','directory','ancestor','missing','oversize']:
   with self.subTest(attack=attack):
    root=self.root();record=self.publish(root);p=root/record['capture_refs'][0]
    if attack=='mode':p.chmod(0o644)
    elif attack=='hardlink':os.link(p,root/'extra')
    elif attack=='symlink':p.rename(root/'extra');p.symlink_to(root/'extra')
    elif attack=='directory':p.parent.chmod(0o755)
    elif attack=='ancestor':
     (root/'private').rename(root/'moved');(root/'private').symlink_to(root/'moved',target_is_directory=True)
    elif attack=='missing':p.unlink()
    else:p.write_bytes(b'x'*3_000_001)
    with self.assertRaises((ValueError,OSError)):mod.read_lead(root,record['lead_id'])

 def test_routing_is_not_legal_classification_and_ordinary_earnings_stays_earnings(self):
  mod=self.module();caps=bundle()
  self.assertTrue(mod.acquisition_hint({'catalyst':'Acquisition announced'},[],()))
  self.assertTrue(mod.acquisition_hint({'event_family':'earnings'},[],caps))
  self.assertFalse(mod.acquisition_hint({'catalyst':'Quarterly results'},[{'title':'Q3 results','text':'Acquisition expenses increased'}],()))
  self.assertEqual(mod.literal_acquisition_links((FIXTURES/'acquisition_original.response.raw').read_bytes(),caps[0].url),(caps[1].url,))

 def test_foreign_or_guessed_exhibits_are_not_followed(self):
  mod=self.module();base=SOURCES['acquisition_original'][0]
  raw=b'<html><body><a href="https://evil.example/ex2.htm">Agreement and Plan of Merger</a><a href="https://www.sec.gov/Archives/edgar/data/123/000110465922005154/ex2.htm">Agreement and Plan of Merger</a></body></html>'
  self.assertEqual(mod.literal_acquisition_links(raw,base),())

 def test_persistence_failure_does_not_publish_a_success_record(self):
  mod=self.module();root=self.root()
  with patch.object(mod,'retain_identity_captures',side_effect=OSError('disk failure')):
   with self.assertRaises(OSError):self.publish(root)
  self.assertFalse((root/'private/acquisition_research').exists())

 def test_all_authority_boundaries_refuse_leads_even_on_inactive_roots(self):
  mod=self.module()
  import opportunity_state as state, opportunity_identity as identity, alpha_radar as radar, autotrader
  import opportunity_fixtures as fixtures
  for active in [False,True]:
   root=self.root();fixtures.make_root(root,active=active)
   (root/'private/broker_baseline.json').write_text('{"preexisting_symbols":[]}')
   record=self.publish(root)
   fake={'symbol':'ATVI','opportunity_identity':{'version':3,'family':'acquisition','status':'verified'},'record_type':'acquisition_research_lead'}
   for value in [record,fake]:
    with self.subTest(active=active,value=value.get('record_type')):
     self.assertTrue(mod.is_research_only_input(value))
     try:decision=state.require_current_allowance(root,value)
     except state.OpportunityStateError:pass
     else:self.assertEqual(decision.outcome,'unknown')
     self.assertFalse(autotrader.research_acceptable(value,{'max_research_age_minutes':60},0))
     with patch.object(radar,'ROOT',root):
      with self.assertRaises((radar.CandidateRejection,state.OpportunityStateError)):radar._final_policy_check(copy.deepcopy(value))
   context=state.load_policy_context(root)
   acq=identity.EventResolution('verified','oe3:'+'b'*64,identity.IssuerBinding('ATVI','0000718877','Activision Blizzard, Inc.','x'),'acquisition',None,(),(),'explicit_binding',version=3)
   self.assertEqual(state.candidate_policy(context,acq,symbol='ATVI').outcome,'unknown')
   self.assertEqual(state.event_decision(context.index,acq).outcome,'unknown')

 def test_live_research_retains_leads_without_synthesis_on_active_or_legacy_paths(self):
  self.module()
  from test_opportunity_radar import RadarPolicyTests
  from test_earnings_identity_evidence import IdentityAcquisitionTests
  import alpha_radar as radar, earnings_identity_acquisition as transport
  from earnings_identity_evidence import identity_source_bytes
  for legacy in [False,True]:
   for available in [False,True]:
    with self.subTest(legacy=legacy,available=available):
     fixture=RadarPolicyTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
     caps=bundle('acquisition_original','acquisition_agreement')
     fixture.scouts=[{'symbol':'ATVI','urls':[caps[0].url,'https://news.example/deal'],
                      'event_date':'2026-11-04','catalyst':'Acquisition announcement'}]
     fixture.bundles=[[{'url':caps[0].url,'title':'Merger agreement','text':'Primary acquisition'},
                       {'url':'https://news.example/deal','title':'Merger','text':'Secondary'}]] if available else [[]]
     raw={c.url:identity_source_bytes(c) for c in caps};calls=[]
     def opened(request,timeout):
      calls.append(request.full_url)
      if not available:raise OSError('source unavailable')
      return IdentityAcquisitionTests().response(raw[request.full_url],url=request.full_url)
     before=(fixture.root/'private/opportunity_policy.jsonl').read_bytes()
     result=fixture.run_research(legacy=legacy,intake=lambda c:self.fail('research-only reached intake'),overrides=[
      (radar,'acquire_identity_captures',{'side_effect':transport.acquire_identity_captures}),
      (radar,'safe_urlopen',{'side_effect':opened}),
      (radar,'post_fetch_rescue_candidate',{'return_value':[]})])
     self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
     self.assertEqual(fixture.synthesized,[])
     self.assertEqual((fixture.root/'private/opportunity_policy.jsonl').read_bytes(),before)
     records=list((fixture.root/'private/acquisition_research').glob('*.json'))
     self.assertEqual(len(records),1)
     record=json.loads(records[0].read_bytes())
     self.assertEqual(record['evidence_status'],'retained' if available else 'unavailable')
     self.assertEqual(calls,[caps[0].url,caps[1].url] if available else [caps[0].url])

 def test_lead_publication_failure_cannot_fall_through_to_model(self):
  mod=self.module()
  from test_opportunity_radar import RadarPolicyTests
  import alpha_radar as radar
  fixture=RadarPolicyTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  fixture.scouts[0]['catalyst']='Acquisition announcement';fixture.scouts=fixture.scouts[:1]
  with patch.object(mod,'publish_lead',side_effect=OSError('disk failed')):
   with self.assertRaisesRegex(radar.ResearchFailure,'research_persistence_failure'):
    fixture.run_research(legacy=True)
  self.assertEqual(fixture.synthesized,[])

 def test_unhashable_symbol_is_a_bounded_validation_error(self):
  mod=self.module();root=self.root()
  with self.assertRaises(ValueError):
   mod.publish_lead(root,symbol={},captures=bundle('acquisition_original'),evidence_status='partial',observed_at=STAMP)

 def test_legal_language_variants_are_observations_not_admission_claims(self):
  mod=self.module();root=self.root()
  from earnings_identity_evidence import identity_source_bytes
  import re
  clauses=[
   'This Agreement supersedes and replaces the prior Agreement and Plan of Merger.',
   'This Agreement constitutes an amendment to the prior Agreement and Plan of Merger.',
   '“Company” means Activision Blizzard, Inc. and Microsoft Corporation jointly.',
   'If this Agreement is amended, any amendment must be in writing and signed by all parties.'
  ]
  for clause in clauses:
   for name in ['acquisition_original','acquisition_agreement','acquisition_update','acquisition_letter']:
    with self.subTest(name=name,clause=clause):
     cap=bundle(name)[0]
     raw=re.sub(b'</body>',lambda m:('<p>'+clause+'</p>').encode()+m[0],identity_source_bytes(cap),flags=re.I)
     changed=capture_identity_source(cap.url,raw,returned_url=cap.url,content_type='text/html')
     record=self.publish(root,(changed,),'partial')
     self.assertEqual(mod.read_lead(root,record['lead_id'])['status'],'research_only')
     self.assertNotIn('event_id',record)
     self.assertNotIn('allowance_id',record)

 def test_raw_acquisition_markers_survive_metadata_stripping_refusal(self):
  self.module()
  import alpha_radar as radar,opportunity_state as state,opportunity_fixtures as fixtures
  root=self.root();fixtures.make_root(root,active=False)
  for value in [{'version':3,'family':'acquisition'}, {'opportunity_identity':{'version':3,'family':'acquisition'}},
                {'lead_id':'al1:'+'f'*64,'event_family':'earnings'}, {'version':99},
                {'symbol':'ATVI','catalyst':'Acquisition announcement'}, {'symbol':'ATVI','event_type':'merger'}]:
   with self.subTest(value=value):
    self.assertEqual(state.require_current_allowance(root,value).outcome,'unknown')
    with self.assertRaises(radar.CandidateRejection):radar._strip_policy_metadata(value)

 def test_recognized_discovery_binds_before_model_output_can_drop_the_marker(self):
  self.module()
  import alpha_radar as radar
  from pathlib import Path
  import tempfile
  selected={'symbol':'ATVI','catalyst':'Acquisition announcement'}
  with tempfile.TemporaryDirectory() as temporary:
   token=radar._research_leads.set({});root=radar.ROOT;radar.ROOT=Path(temporary)
   try:
    self.assertTrue(radar._retain_acquisition_research(selected,[],deadline=0))
    with self.assertRaisesRegex(radar.CandidateRejection,'opportunity_identity_unknown'):
     radar._strip_policy_metadata({'symbol':'ATVI','sources':[{'url':'https://news.example/deal'}]})
    self.assertEqual(len(list((Path(temporary)/'private/acquisition_research').glob('*.json'))),1)
   finally:
    radar.ROOT=root;radar._research_leads.reset(token)

 def test_model_omission_cannot_bypass_inactive_root_after_recognized_discovery(self):
  self.module()
  from test_opportunity_radar import RadarPolicyTests
  import alpha_radar as radar
  fixture=RadarPolicyTests();fixture.setUp();self.addCleanup(fixture.doCleanups)
  fixture.scouts=[{'symbol':'ATVI','urls':['https://news.example/deal'],'event_date':'2026-11-04','catalyst':'Acquisition announcement'}]
  fixture.bundles=[[{'url':'https://news.example/deal','title':'Deal','text':'Secondary'}]]
  def synthesis(cfg,selected,evidence,deadline,**kwargs):
   fixture.synthesized.append(selected['symbol'])
   return {'symbol':'ATVI','sources':[{'url':p['url']} for p in evidence]}
  # Original first-RED demanded CandidateRejection, but the approved successful
  # observation contract is normalized none. Exact original and its failed
  # assertion are archived in shared-invariant-c1-original-red, not hidden.
  result=fixture.run_research(legacy=True,overrides=[(radar,'synthesize_candidate',{'side_effect':synthesis})])
  self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
  self.assertEqual(fixture.synthesized,[])
  records=list((fixture.root/'private/acquisition_research').glob('*.json'))
  self.assertEqual(len(records),1)
  self.assertEqual(json.loads(records[0].read_bytes())['evidence_status'],'unavailable')

 def test_recovery_omission_never_produces_a_candidate_on_either_policy_root(self):
  import alpha_radar as radar, opportunity_fixtures as fixtures, opportunity_state as state, autotrader
  from test_opportunity_radar import RadarPolicyTests
  for active in (False,True):
   with self.subTest(active=active):
    f=RadarPolicyTests();f.setUp()
    try:
     if not active:
      f.root=self.root();fixtures.make_root(f.root,active=False)
      f.enterContext(patch.object(radar,'ROOT',f.root))
     f.scouts=f.scouts[:1];f.bundles=f.bundles[:1];intaken=[]
     streams=(state.POLICY_STREAM,state.CANDIDATES_STREAM,state.REVIEWS_STREAM,'order_ledger.jsonl')
     before={p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams}
     def recovered(c,p,*a,**kw):
      return ([{**page,'title':'Agreement and Plan of Merger','text':'Agreement and Plan of Merger'}
               if page['url']==f.scouts[0]['urls'][0] else page for page in p],[])
     result=f.run_research(intake=lambda c:intaken.append(c) or c,overrides=[
      (radar,'recover_publications',{'side_effect':recovered})])
     self.assertEqual(f.synthesized,[])
     self.assertEqual(intaken,[])
     self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
     self.assertIsNone(radar._research_leads.get())
     records=list((f.root/'private/acquisition_research').glob('*.json'))
     self.assertEqual(len(records),1)
     lead=self.module().read_lead(f.root,json.loads(records[0].read_bytes())['lead_id'])
     # After run-context reset the only produced object remains inert at real durable gates.
     self.assertFalse(autotrader.research_acceptable(lead,{'max_research_age_minutes':60},0))
     self.assertEqual(state.require_current_allowance(f.root,lead).outcome,'unknown')
     with self.assertRaises(radar.CandidateRejection):radar._final_policy_check(copy.deepcopy(lead))
     self.assertEqual(before,{p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams})
     # Same symbol, independently supported earnings is NOT permanently banned by the lead.
     f.synthesized.clear()
     positive=f.run_research()
     self.assertEqual(positive['symbol'],'ACME')
     self.assertEqual(f.synthesized,['ACME'])
     radar._final_policy_check(dict(positive))
     positive={k:v for k,v in positive.items() if not k.startswith('_')}
     positive['sources_verified_at']=dt.datetime.now(dt.timezone.utc).isoformat()
     positive['dossier_hash']=hashlib.sha256(json.dumps(positive,sort_keys=True,separators=(',',':')).encode()).hexdigest()
     self.assertTrue(autotrader.research_acceptable(positive,{'max_research_age_minutes':60},0))
     if active:
      import sqlite_ledger as storage
      storage.append_jsonl(f.root/state.CANDIDATES_STREAM,positive)
     self.assertEqual(state.require_current_allowance(f.root,positive).outcome,'eligible')
    finally:f.doCleanups()

 def test_recovery_and_rescue_paths_share_observation_before_synthesis(self):
  import alpha_radar as radar, opportunity_fixtures as fixtures, opportunity_state as state
  from test_opportunity_radar import RadarPolicyTests
  for active in (False,True):
   for route in ('model_recovery','initial_rescue','deferred_rescue'):
    with self.subTest(active=active,route=route):
     f=RadarPolicyTests();f.setUp()
     try:
      if not active:
       f.root=self.root();fixtures.make_root(f.root,active=False)
       f.enterContext(patch.object(radar,'ROOT',f.root))
      if route!='deferred_rescue':f.scouts=f.scouts[:1];f.bundles=f.bundles[:1]
      target=f.scouts[-1]['symbol'];target_url=f.scouts[-1]['urls'][0]
      if route!='model_recovery':f.bundles[-1]=f.bundles[-1][:1]
      streams=(state.POLICY_STREAM,state.CANDIDATES_STREAM,state.REVIEWS_STREAM,'order_ledger.jsonl')
      before={p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams}
      def recovered(c,p,*a,**kw):
       return ([{**page,'title':'Agreement and Plan of Merger','text':'Agreement and Plan of Merger'}
         if route=='model_recovery' and kw['allow_model'] and page['url']==target_url else page for page in p],[])
      def rescued(selected,accepted,**kw):
       self.assertEqual(selected['symbol'],target)
       return [{**f.bundles[-1][0],'title':'Agreement and Plan of Merger','text':'Agreement and Plan of Merger'},
          {'url':selected['urls'][1],'title':'News','text':'Secondary'}]
      def synth(cfg,selected,evidence,deadline,**kw):
       f.synthesized.append(selected['symbol'])
       self.assertNotEqual(selected['symbol'],target,'acquisition reached synthesis')
       return {'status':'none','none_reason':'no_fresh_setup'}
      f.run_research(intake=lambda c:self.fail('acquisition reached intake'),overrides=[
       (radar,'recover_publications',{'side_effect':recovered}),
       (radar,'post_fetch_rescue_candidate',{'side_effect':rescued}),
       (radar,'synthesize_candidate',{'side_effect':synth})])
      self.assertEqual(f.synthesized,['ACME'] if route=='deferred_rescue' else [])
      self.assertEqual(len(list((f.root/'private/acquisition_research').glob('*.json'))),1)
      self.assertEqual(before,{p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams})
     finally:f.doCleanups()

 def test_native_rescue_observation_outcome_survives_real_quality_drop(self):
  import alpha_radar as radar, opportunity_fixtures as fixtures, opportunity_state as state
  from test_opportunity_radar import RadarPolicyTests
  real_filter=radar.filter_evidence
  for active in (False,True):
   for dropped in (False,True):
    with self.subTest(active=active,dropped=dropped):
     f=RadarPolicyTests();f.setUp()
     try:
      if not active:
       f.root=self.root();fixtures.make_root(f.root,active=False)
       f.enterContext(patch.object(radar,'ROOT',f.root))
      f.scouts=f.scouts[:1];f.bundles=[f.bundles[0][:1]]
      fresh='https://independent.example/deal';calls=[];quality=[]
      page={'url':fresh,'title':'Agreement and Plan of Merger','text':'Agreement and Plan of Merger','published_at':'2026-11-04T12:00:00Z'}
      def gather(urls,**kw):
       calls.append(list(urls));return [dict(page)] if urls==[fresh] else f.bundles[0]
      def filtered(pages):
       if dropped and any(p.get('url')==fresh for p in pages):
        accepted,notes=real_filter(pages);quality.extend(notes);return accepted,notes
       return pages,[]
      streams=(state.POLICY_STREAM,state.CANDIDATES_STREAM,state.REVIEWS_STREAM,'order_ledger.jsonl')
      snapshot=lambda:{p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams}
      before=snapshot()
      result=f.run_research(intake=lambda c:self.fail('acquisition reached intake'),overrides=[
       (radar,'gather_evidence',{'side_effect':gather}),
       (radar,'filter_evidence',{'side_effect':filtered}),
       (radar,'gateway_rescue_url',{'return_value':fresh}),
       (radar,'sec_edgar_filing_url',{'return_value':None})])
      self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
      self.assertIn([fresh],calls)
      self.assertEqual(f.synthesized,[])
      records=list((f.root/'private/acquisition_research').glob('*.json'))
      self.assertEqual(len(records),1)
      lead=self.module().read_lead(f.root,json.loads(records[0].read_bytes())['lead_id'])
      self.assertEqual(lead['evidence_status'],'unavailable')
      diagnostics=[json.loads(line) for line in (f.root/'private/research_diagnostics.jsonl').read_text().splitlines()]
      if dropped:
       self.assertIn('article_body_missing',{n['reason'] for n in quality})
       self.assertIn('bundle_rescue_unavailable',{n['reason'] for n in diagnostics})
      self.assertEqual(before,snapshot())
      self.assertIsNone(radar._research_leads.get())
      # The observation must not ban independently supported earnings for this symbol.
      f.bundles=[f.pages[:1]+[{'url':f.scouts[0]['urls'][1],'title':'Results','text':'Reported results'}]]
      self.assertEqual(f.run_research()['symbol'],'ACME')
      self.assertEqual(f.synthesized,['ACME'])
     finally:f.doCleanups()

 def test_recovered_unranked_observation_normalizes_companion_fetch_failure(self):
  import alpha_radar as radar, opportunity_fixtures as fixtures, opportunity_state as state
  from test_opportunity_radar import RadarPolicyTests
  real_filter=radar.filter_evidence
  for active in (False,True):
   for failed_secondary in (False,True):
    with self.subTest(active=active,failed_secondary=failed_secondary):
     f=RadarPolicyTests();f.setUp()
     try:
      if not active:
       f.root=self.root();fixtures.make_root(f.root,active=False)
       f.enterContext(patch.object(radar,'ROOT',f.root))
      f.scouts=f.scouts[:1]
      pages=[{'url':f.scouts[0]['urls'][0],'title':'Quarterly results','text':'Ordinary reported results '*100}]
      self.assertIn('source_freshness_unknown',{n['reason'] for n in real_filter(pages)[1]})
      def gather(urls,**kw):
       if failed_secondary:kw['diagnostics'].append({'url':f.scouts[0]['urls'][1],'reason':'source_fetch_failed'})
       return pages
      def recovered(c,p,*a,**kw):return ([{**q,'title':'Agreement and Plan of Merger'} for q in p],[])
      streams=(state.POLICY_STREAM,state.CANDIDATES_STREAM,state.REVIEWS_STREAM,'order_ledger.jsonl')
      snapshot=lambda:{p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams}
      before=snapshot()
      result=f.run_research(intake=lambda c:self.fail('acquisition reached intake'),overrides=[
       (radar,'gather_evidence',{'side_effect':gather}),
       (radar,'recover_publications',{'side_effect':recovered}),
       (radar,'filter_evidence',{'side_effect':real_filter}),
       (radar,'post_fetch_rescue_candidate',{'return_value':[]})])
      self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
      records=list((f.root/'private/acquisition_research').glob('*.json'))
      self.assertEqual(len(records),1)
      self.assertEqual(self.module().read_lead(f.root,json.loads(records[0].read_bytes())['lead_id'])['evidence_status'],'unavailable')
      self.assertEqual(f.synthesized,[]);self.assertEqual(before,snapshot())
      self.assertIsNone(radar._research_leads.get())
     finally:f.doCleanups()

 def test_completed_observation_does_not_hide_unobserved_or_persistence_failure(self):
  import alpha_radar as radar, opportunity_fixtures as fixtures, opportunity_state as state
  from test_opportunity_radar import RadarPolicyTests
  for active in (False,True):
   for failure in ('unrelated','persistence','ordinary_policy_skip'):
    with self.subTest(active=active,failure=failure):
     f=RadarPolicyTests();f.setUp()
     try:
      if not active:
       f.root=self.root();fixtures.make_root(f.root,active=False)
       f.enterContext(patch.object(radar,'ROOT',f.root))
      if failure!='unrelated':f.scouts=f.scouts[:1]
      pages=[{'url':f.scouts[0]['urls'][0],'title':'Quarterly results','text':'Ordinary reported results '*100}]
      def gather(urls,**kw):
       kw['diagnostics'].append({'url':f.scouts[-1]['urls'][1],'reason':'source_fetch_failed'});return pages
      def recovered(c,p,*a,**kw):
       return ([{**q,'title':'Agreement and Plan of Merger'} for q in p],[]) if failure!='ordinary_policy_skip' else (p,[])
      overrides=[(radar,'gather_evidence',{'side_effect':gather}),
       (radar,'recover_publications',{'side_effect':recovered}),
       (radar,'filter_evidence',{'side_effect':radar.filter_evidence}),
       (radar,'post_fetch_rescue_candidate',{'return_value':[]})]
      if failure=='persistence':overrides.append((self.module(),'publish_lead',{'side_effect':OSError('disk failure')}))
      if failure=='ordinary_policy_skip':
       # Only rescue admission refuses; discovery remains unskipped. No observation succeeded.
       overrides.append((radar,'_policy_reason',{'side_effect':lambda context,selected,pages=None:'unchanged_opportunity' if pages is not None else None}))
      streams=(state.POLICY_STREAM,state.CANDIDATES_STREAM,state.REVIEWS_STREAM,'order_ledger.jsonl')
      before={p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams}
      expected='research_persistence_failure' if failure=='persistence' else 'research_source_'
      with self.assertRaisesRegex(radar.ResearchFailure,expected):
       f.run_research(intake=lambda c:self.fail('unexpected intake'),overrides=overrides)
      self.assertEqual(f.synthesized,[])
      records=list((f.root/'private/acquisition_research').glob('*.json'))
      self.assertEqual(len(records),1 if failure=='unrelated' else 0)
      if records:self.module().read_lead(f.root,json.loads(records[0].read_bytes())['lead_id'])
      self.assertEqual(before,{p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams})
      self.assertIsNone(radar._research_leads.get())
     finally:f.doCleanups()

 def test_late_authenticated_acquisition_is_observed_but_not_admitted(self):
  import time
  import alpha_radar as radar, earnings_identity_acquisition as transport, opportunity_state as state
  from test_opportunity_radar import RadarPolicyTests
  from test_earnings_identity_evidence import IdentityAcquisitionTests
  from earnings_identity_evidence import identity_source_bytes
  f=RadarPolicyTests();f.setUp();self.addCleanup(f.doCleanups)
  caps=bundle('acquisition_original','acquisition_agreement');raw={c.url:identity_source_bytes(c) for c in caps}
  f.scouts=[{'symbol':'ATVI','urls':[caps[0].url,'https://news.example/deal'],
             'event_date':'2026-11-04','catalyst':'Quarterly results'}]
  f.bundles=[[{'url':caps[0].url,'title':'Quarterly results','text':'Acquisition expenses increased'},
              {'url':'https://news.example/deal','title':'News','text':'Ordinary news'}]]
  calls=[];notes=[];handoffs=[];deadlines=[]
  streams=(state.POLICY_STREAM,state.CANDIDATES_STREAM,state.REVIEWS_STREAM,'order_ledger.jsonl')
  before={p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams}
  def opened(request,timeout):
   calls.append(request.full_url)
   return IdentityAcquisitionTests().response(raw[request.full_url],url=request.full_url)
  original_links=transport.earnings_exhibit_links
  def acquire(symbol,pages,*,deadline,opener):
   clock=[time.monotonic()];deadlines.append(deadline)
   def links(raw,url):
    result=original_links(raw,url);clock[0]=deadline+1;return result
   with patch.object(transport,'monotonic',side_effect=lambda:clock[0]),patch.object(
      transport,'earnings_exhibit_links',side_effect=links):
    result=transport.acquire_identity_captures(symbol,pages,deadline=deadline,opener=opener)
    handoffs.append(result)
    notes.extend(transport.acquisition_notes([p['url'] for p in pages]));return result
  result=f.run_research(intake=lambda c:self.fail('late acquisition reached intake'),overrides=[
   (radar,'safe_urlopen',{'side_effect':opened}),
   (radar,'acquire_identity_captures',{'side_effect':acquire})])
  self.assertEqual(result,{'status':'none','none_reason':'no_new_eligible_opportunity'})
  self.assertEqual(handoffs,[()])
  self.assertEqual(len(deadlines),1)
  self.assertEqual(calls,[caps[0].url])
  self.assertIn('identity_handoff_deadline',{n['reason'] for n in notes})
  self.assertEqual(f.synthesized,[])
  records=list((f.root/'private/acquisition_research').glob('*.json'))
  self.assertEqual(len(records),1)
  lead=self.module().read_lead(f.root,json.loads(records[0].read_bytes())['lead_id'])
  self.assertEqual(lead['evidence_status'],'partial')
  self.assertEqual(len(lead['capture_refs']),1)
  self.assertEqual(before,{p:(f.root/p).read_bytes() if (f.root/p).exists() else None for p in streams})
  self.assertIsNone(radar._identity_captures.get())

 def test_schema_and_identifier_validation_are_closed(self):
  mod=self.module();root=self.root()
  for symbol,stamp in [('bad symbol',STAMP),('ATVI','2026-11-11'),('ATVI',{})]:
   with self.subTest(symbol=symbol,stamp=stamp),self.assertRaises(ValueError):
    mod.publish_lead(root,symbol=symbol,captures=(),evidence_status='unavailable',observed_at=stamp)
  for lead in ['../escape',{},'al1:'+'A'*64]:
   with self.assertRaises(ValueError):mod.read_lead(root,lead)
