import base64
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
import asyncio
import time
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
def load():
    p=ROOT/'dashboard_mcp.py'
    assert p.exists(), 'script-only MCP adapter is missing'
    spec=importlib.util.spec_from_file_location('dashboard_mcp',p)
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

class PayloadTests(unittest.TestCase):
    def fixture(self, root, m):
        public=root/'public';public.mkdir()
        (public/'.vercel').mkdir()
        (public/'.vercel'/'project.json').write_text(json.dumps({'projectId':m.PROJECT,'orgId':m.TEAM}))
        (public/'index.html').write_text('ok');(public/'dashboard.json').write_text('{}')
        return public

    def test_rejects_symlink_wrong_project_and_size_cap(self):
        m=load()
        for kind in ('symlink','hardlink','project','size','private'):
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as temp:
                root=Path(temp);public=self.fixture(root,m)
                if kind=='symlink':(public/'alias').symlink_to(public/'index.html')
                elif kind=='hardlink':
                    import os
                    os.link(public/'index.html',root/'private_source')
                elif kind=='project':(public/'.vercel'/'project.json').write_text('{}')
                elif kind=='size':(public/'big').write_bytes(b'x'*100);m.MAX_BYTES=64
                else:(public/'private').mkdir();(public/'private'/'secret').write_text('SECRET')
                with self.assertRaises(m.Rejected):m.payload(root)
                m.MAX_BYTES=8*1024*1024

    def test_payload_only_public_inline_files(self):
        m=load()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);public=root/'public';public.mkdir()
            (public/'.vercel').mkdir();(public/'.vercel'/'project.json').write_text(json.dumps({'projectId':m.PROJECT,'orgId':m.TEAM}))
            (public/'index.html').write_text('héllo');(public/'dashboard.json').write_text('{}')
            (public/'asset.bin').write_bytes(b'\xff\x00');(public/'.env').write_text('NEVER_PUBLISH')
            args=m.payload(root)
            self.assertEqual(args['teamId'],m.TEAM)
            self.assertEqual(args['requestBody']['project'],m.PROJECT)
            self.assertEqual(args['requestBody']['target'],'production')
            rows={r['file']:r for r in args['requestBody']['files']}
            self.assertEqual(set(rows),{'index.html','dashboard.json','asset.bin'})
            self.assertEqual(rows['index.html']['data'],'héllo')
            self.assertEqual(rows['asset.bin']['encoding'],'base64')
            self.assertNotIn('gitSource',args['requestBody'])

class PublishTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_only_verification_of_created_deployment(self):
        m=load();calls=[]
        async def call(name,args):
            calls.append(name)
            if name=='list_projects':return {'projects':[{'id':m.PROJECT}]}
            if name=='get_deployment':return {'id':'dpl_fixture','project':{'id':m.PROJECT},'target':'production','readyState':'READY'}
            if name=='list_deployment_aliases':return {'aliases':[{'alias':'tradey-desk-psi.vercel.app'}]}
            self.fail('read-only verification attempted mutation')
        result=await m.publish(call,{},time.monotonic()+1,existing_id='dpl_fixture')
        self.assertEqual(result['id'],'dpl_fixture')
        self.assertEqual(calls,['list_projects','get_deployment','list_deployment_aliases'])

    async def test_rejects_cross_project_failed_state_and_poll_timeout(self):
        m=load()
        for kind in ('project','error','timeout'):
            calls=[]
            async def call(name,args):
                calls.append(name)
                if name=='list_projects':return {'projects':[{'id':m.PROJECT}]}
                if name=='create_deployment':return {'id':'dpl_fixture'}
                return {'id':'dpl_fixture','projectId':'wrong' if kind=='project' else m.PROJECT,'target':'production','readyState':'ERROR' if kind=='error' else 'BUILDING'}
            with self.subTest(kind=kind), self.assertRaises(m.Rejected) as caught:
                await m.publish(call,{},time.monotonic()+.02)
            self.assertEqual(str(caught.exception),{'project':'config','error':'build','timeout':'timeout'}[kind])
            self.assertEqual(calls.count('create_deployment'),1)

    async def test_one_create_then_ready_same_project(self):
        m=load();calls=[]
        async def call(name,args):
            calls.append((name,args))
            if name=='list_projects':return {'projects':[{'id':m.PROJECT}]}
            if name=='create_deployment':return {'id':'dpl_fixture'}
            if name=='get_deployment':return {'id':'dpl_fixture','projectId':m.PROJECT,'target':'production','readyState':'READY'}
            return {'aliases':[{'alias':'tradey-desk-psi.vercel.app'}]}
        result=await m.publish(call,{'teamId':m.TEAM,'requestBody':{}},time.monotonic()+1)
        self.assertEqual(result['id'],'dpl_fixture')
        self.assertEqual([n for n,_ in calls].count('create_deployment'),1)
        self.assertTrue(all(args['teamId']==m.TEAM for _,args in calls))

    async def test_unknown_create_never_retried(self):
        m=load();calls=[]
        async def call(name,args):
            calls.append(name)
            if name=='list_projects':return {'projects':[{'id':m.PROJECT}]}
            raise ConnectionError('SECRET_TOKEN_MUST_NOT_ESCAPE')
        with self.assertRaises(m.Rejected) as caught:
            await m.publish(call,{},time.monotonic()+1)
        self.assertEqual(str(caught.exception),'failed')
        self.assertEqual(calls,['list_projects','create_deployment'])

class NativeTests(unittest.TestCase):
    def test_native_connection_disables_interactive_callbacks(self):
        import sys
        from types import ModuleType
        m=load();seen=[]
        config={'url':'https://mcp.vercel.com','auth':'oauth','sampling':{'enabled':True},'elicitation':{'enabled':True}}
        async def connect(name,cfg):
            seen.append(name)
            self.assertEqual(cfg['sampling'],{'enabled':False})
            self.assertEqual(cfg['elicitation'],{'enabled':False})
            raise m.Rejected('config')  # No native session or approval/provider code runs.
        cfgmod=ModuleType('hermes_cli.config');cfgmod.load_config=lambda:{'mcp_servers':{'vercel':config,'other':{}}}
        discovery=ModuleType('tools.mcp_tool_discovery');discovery._connect_server=connect
        with patch.dict(sys.modules,{'hermes_cli.config':cfgmod,'tools.mcp_tool_discovery':discovery}):
            with self.assertRaises(m.Rejected):
                asyncio.run(m.native_publish(None,time.monotonic()+1))
        self.assertEqual(seen,['vercel'])
        self.assertTrue(config['sampling']['enabled'])
        self.assertTrue(config['elicitation']['enabled'])

    def test_native_wrapped_deployment_envelope(self):
        import hashlib
        import sys
        from types import ModuleType, SimpleNamespace
        from unittest.mock import AsyncMock
        import dashboard_mcp_entry as entry
        m=load()
        fixture=ROOT/'test_artifacts/dashboard-mcp/fix1-native-envelopes.json'
        raw=fixture.read_bytes()
        self.assertEqual(hashlib.sha256(raw).hexdigest(),'cd597723d18a0f2ebadfc7ec34477b8c7e9417bab96008f4e4f21272ad98c927')
        bundle=json.loads(raw);provenance=bundle['provenance']
        self.assertEqual(provenance['adapter_sha256'],'430b0d10ea77f14373806c7f0d4918f7043ba2610d0909acb9ff5cda9c92b9df')
        self.assertEqual((provenance['team'],provenance['project'],provenance['target']),(m.TEAM,m.PROJECT,'production'))
        rows=iter(bundle['responses']);calls=[]
        async def call(name,args):
            row=next(rows);self.assertEqual(row['tool'],name);calls.append((name,args))
            self.assertEqual(args['teamId'],m.TEAM)
            if name=='get_deployment':self.assertEqual(args['idOrUrl'],'dpl_DqR9dnJK9zNf2oWNC8eMVKd2cvjm')
            return SimpleNamespace(model_dump=lambda **kw:row['envelope'])
        schema={'inputSchema':{'properties':{'requestBody':{'properties':{'files':{'data':{},'encoding':{}}}}}}}
        tools=[SimpleNamespace(name=n,model_dump=lambda **kw:schema) for n in ('list_projects','create_deployment','get_deployment','list_deployment_aliases')]
        server=SimpleNamespace(_tools=tools,session=SimpleNamespace(call_tool=call),shutdown=AsyncMock())
        async def connect(name,cfg):
            self.assertEqual(name,'vercel')
            self.assertEqual(cfg['sampling'],{'enabled':False})
            self.assertEqual(cfg['elicitation'],{'enabled':False})
            return server
        cfgmod=ModuleType('hermes_cli.config');cfgmod.load_config=lambda:{'mcp_servers':{'vercel':{'url':'https://mcp.vercel.com','auth':'oauth'}}}
        discovery=ModuleType('tools.mcp_tool_discovery');discovery._connect_server=connect
        with patch.dict(sys.modules,{'hermes_cli.config':cfgmod,'tools.mcp_tool_discovery':discovery}),patch('asyncio.sleep',new=AsyncMock()):
            result=asyncio.run(m.native_publish({'teamId':m.TEAM,'requestBody':{'project':m.PROJECT,'target':'production','files':[]}},time.monotonic()+5))
        self.assertEqual([n for n,_ in calls],['list_projects','create_deployment','get_deployment','get_deployment','list_deployment_aliases'])
        self.assertEqual(result,{'id':'dpl_DqR9dnJK9zNf2oWNC8eMVKd2cvjm','projectId':m.PROJECT,'target':'production','readyState':'READY','alias':'tradey-desk-psi.vercel.app'})
        server.shutdown.assert_awaited_once()
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);entry.save_receipt(root,result)
            receipt,=(root/'private/dashboard_deploy_diagnostics').glob('mcp-receipt-*.json')
            self.assertEqual(json.loads(receipt.read_text()),result)
            self.assertEqual(receipt.stat().st_mode & 0o777,0o600)

    def test_mcp_response_json_and_auth_are_sanitized(self):
        m=load()
        self.assertEqual(m.decode_result({'content':[{'type':'text','text':'{"id":"dpl_fixture"}'}]}),{'id':'dpl_fixture'})
        with self.assertRaises(m.Rejected) as caught:
            m.decode_result({'isError':True,'content':[{'type':'text','text':'{"statusCode":403,"message":"SECRET"}'}]})
        self.assertEqual(str(caught.exception),'auth')
        with self.assertRaises(m.Rejected) as caught:
            m.decode_result({'isError':True,'content':[{'type':'text','text':'SECRET_UNKNOWN'}]})
        self.assertEqual(str(caught.exception),'failed')

class EntryTests(unittest.TestCase):
    def test_private_receipts_are_bounded_and_owner_only(self):
        import dashboard_mcp_entry as entry
        import stat
        row={'id':'dpl_fixture','projectId':load().PROJECT,'target':'production','readyState':'READY','alias':'tradey-desk-psi.vercel.app'}
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            for _ in range(32):entry.save_receipt(root,row)
            directory=root/'private/dashboard_deploy_diagnostics'
            files=list(directory.glob('mcp-receipt-*.json'))
            self.assertEqual(len(files),30)
            self.assertEqual(stat.S_IMODE(directory.stat().st_mode),0o700)
            self.assertTrue(all(stat.S_IMODE(p.stat().st_mode)==0o600 for p in files))

    def test_helper_auth_failure_alert_is_allowlisted(self):
        import dashboard_mcp_entry as entry
        import subprocess,io
        responses=[subprocess.CompletedProcess([],0,'',''),subprocess.CompletedProcess([],1,'SYSTEM_FAILURE dashboard_deploy_auth\nSECRET','')]
        output=io.StringIO()
        with tempfile.TemporaryDirectory() as temp, patch.object(entry,'run_owned',side_effect=responses), patch.object(entry,'runtime_command',return_value=['worker']),patch('sys.stdout',output):
            self.assertEqual(entry.helper(Path(temp)),1)
        self.assertEqual(output.getvalue(),'SYSTEM_FAILURE dashboard_deploy_failed\n')

    def test_real_guardian_outer_suppresses_untrusted_output(self):
        from dashboard_process import run_owned
        import sys
        result=run_owned([sys.executable,'-c',"print('SECRET');print('SYSTEM_FAILURE dashboard_deploy_auth');raise SystemExit(1)"],ROOT,3,outer=True)
        self.assertEqual(result.returncode,1)
        self.assertEqual(result.stdout,'\n')
        clean=run_owned([sys.executable,'-c',"print('SYSTEM_FAILURE dashboard_deploy_auth');raise SystemExit(1)"],ROOT,3,outer=True)
        self.assertEqual(clean.stdout,'SYSTEM_FAILURE dashboard_deploy_auth\n')

    def test_gate_skips_without_build_or_mcp(self):
        import dashboard_mcp_entry as entry
        with patch('run_cycle.in_window',return_value=False), patch.object(entry,'run_owned') as run:
            self.assertEqual(entry.main(),0)
        run.assert_not_called()

    def test_helper_build_then_one_bounded_mcp_worker(self):
        import dashboard_mcp_entry as entry
        import subprocess
        seen=[]
        receipt={'id':'dpl_fixture','projectId':load().PROJECT,'target':'production','readyState':'READY','alias':'tradey-desk-psi.vercel.app'}
        def run(cmd,root,timeout,**kwargs):
            seen.append((cmd,timeout))
            return subprocess.CompletedProcess([],0,json.dumps(receipt) if len(seen)==2 else '', '')
        with tempfile.TemporaryDirectory() as temp, patch.object(entry,'run_owned',side_effect=run), patch.object(entry,'runtime_command',return_value=['worker']):
            self.assertEqual(entry.helper(Path(temp)),0)
        self.assertEqual(len(seen),2)
        self.assertTrue(seen[0][0][-1].endswith('public_dashboard.py'))
        self.assertTrue(all(0<t<=90 for _,t in seen))
