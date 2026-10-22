"""Bounded protocol runner behind the existing Linux caller-lifetime subreaper."""
from __future__ import annotations
import json
import os
from pathlib import Path
import selectors
import signal
import subprocess
import sys
from time import monotonic

MAX_INPUT=32768
MAX_OUTPUT=2*1024*1024
MAX_STDERR=16384


def failed(reason,code=1):
    return subprocess.CompletedProcess([],code,json.dumps({'version':1,'status':'error','reason':reason}),'')


def run_process(command,input:bytes,*,deadline:float,cwd:Path,max_input_bytes:int=MAX_INPUT):
    if max_input_bytes not in (MAX_INPUT,65536,4*1024*1024) or not isinstance(input,bytes) or len(input)>max_input_bytes:return failed('input_limit')
    if monotonic()>=deadline:return failed('timeout',124)
    try:payload=input.decode('utf-8')
    except UnicodeError:return failed('invalid_request')
    fd=os.pidfd_open(os.getpid())
    request={'command':list(command),'input':payload,'deadline':deadline,'cwd':str(cwd),'caller_fd':fd}
    try:
        if monotonic()>=deadline:return failed('timeout',124)
        p=subprocess.Popen([sys.executable,'-I',str(Path(__file__).resolve()),'--guardian'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True,start_new_session=True,close_fds=True,pass_fds=(fd,))
    finally:os.close(fd)
    try:
        try:out,_=p.communicate(json.dumps(request),timeout=max(.001,deadline-monotonic())+1.2)
        except BaseException:
            p.send_signal(signal.SIGTERM)
            try:p.communicate(timeout=1)
            except subprocess.TimeoutExpired:
                from broker_supervisor import freeze_kill_tree
                freeze_kill_tree(p.pid,include_root=False);p.communicate(timeout=1)
            raise
        if p.returncode:return failed('containment_unconfirmed')
        row=json.loads(out)
        return subprocess.CompletedProcess([],row['returncode'],row.get('stdout',''),'')
    finally:
        for s in (p.stdin,p.stdout,p.stderr):
            if s and not s.closed:s.close()


def _collect(request):
    # This trusted collector is the only child whose bounded protocol the
    # guardian buffers; arbitrary worker stdout/stderr is capped here first.
    p=subprocess.Popen(request['command'],cwd=request['cwd'],stdin=subprocess.PIPE,stdout=subprocess.PIPE,stderr=subprocess.PIPE,close_fds=True)
    sel=selectors.DefaultSelector();data=request['input'].encode();buf=[bytearray(),bytearray()];reason=None
    try:
        for i,s in enumerate((p.stdout,p.stderr)):
            os.set_blocking(s.fileno(),False);sel.register(s,selectors.EVENT_READ,i)
        os.set_blocking(p.stdin.fileno(),False)
        if data:sel.register(p.stdin,selectors.EVENT_WRITE,2)
        else:p.stdin.close()
        while sel.get_map() or p.poll() is None:
            if monotonic()>=request['deadline']:reason='timeout';break
            for key,_ in sel.select(min(.02,max(0,request['deadline']-monotonic()))):
                if key.data==2:
                    try:n=os.write(key.fd,data);data=data[n:]
                    except BrokenPipeError:data=b''
                    if not data:sel.unregister(key.fileobj);key.fileobj.close()
                else:
                    chunk=os.read(key.fd,65536)
                    if not chunk:sel.unregister(key.fileobj);key.fileobj.close();continue
                    cap=MAX_OUTPUT if key.data==0 else MAX_STDERR
                    if len(buf[key.data])+len(chunk)>cap:reason='output_limit';break
                    buf[key.data].extend(chunk)
            if reason:break
        if reason:return {'returncode':124 if reason=='timeout' else 1,'stdout':json.dumps({'version':1,'status':'error','reason':reason})}
        try:text=buf[0].decode('utf-8')
        except UnicodeError:return {'returncode':1,'stdout':json.dumps({'reason':'malformed_response'})}
        row={'returncode':p.returncode,'stdout':text}
        if len(json.dumps(row,ensure_ascii=False).encode())>MAX_OUTPUT:return {'returncode':1,'stdout':json.dumps({'reason':'output_limit'})}
        return row
    finally:
        sel.close()
        for s in (p.stdin,p.stdout,p.stderr):
            if s and not s.closed:s.close()
        # The guardian kills/reaps ALL owned descendants before returning,
        # including a worker that detached or stopped reading its pipes.


def _guardian(request):
    from broker_supervisor import supervise,cleanup
    remaining=request['deadline']-monotonic()
    if remaining<=0:return {'returncode':124,'stdout':json.dumps({'reason':'timeout'})}
    try:
        result=supervise({'command':[sys.executable,'-I',str(Path(__file__).resolve()),'--collector'],'input':json.dumps(request),'timeout':remaining,'options':{}},caller_fd=request['caller_fd'])
        if result['timed_out']:return {'returncode':124,'stdout':json.dumps({'reason':'timeout'})}
        if result['returncode']:return {'returncode':1,'stdout':json.dumps({'reason':'worker_exit'})}
        return json.loads(result['stdout'])
    finally:cleanup()


def worker_command():
    from runtime_paths import hermes_runtime
    python,source=hermes_runtime();worker=Path(__file__).with_name('discovery_worker.py')
    bootstrap=('import os,sys,runpy;os.environ.pop("PYTHONHOME",None);os.environ.pop("PYTHONPATH",None);os.environ.pop("VIRTUAL_ENV",None);'
               f'sys.path.insert(0,{str(source)!r});sys._hermes_pin_default_home=True;import hermes_bootstrap;'
               f'sys.path.insert(0,{str(worker.parent)!r});runpy.run_path({str(worker)!r},run_name="__main__")')
    return [python,'-I','-c',bootstrap]


def run_collection(requests:list[dict],*,deadline:float,cwd:Path)->dict:
    body=json.dumps({'version':1,'requests':requests,'deadline':deadline},ensure_ascii=False).encode()
    result=run_process(worker_command(),body,deadline=deadline,cwd=cwd)
    from extraction_contract import strict_json_loads
    try:row=strict_json_loads(result.stdout)
    except (ValueError,TypeError):return {'version':1,'status':'error','reason':'malformed_response'}
    if result.returncode:return row if isinstance(row,dict) and row.get('status')=='error' else {'version':1,'status':'error','reason':'worker_exit'}
    return row if isinstance(row,dict) else {'version':1,'status':'error','reason':'malformed_response'}


if __name__=='__main__':
    sys.path.insert(0,str(Path(__file__).resolve().parent))
    request=json.load(sys.stdin)
    try:row=_guardian(request) if sys.argv[1:]==['--guardian'] else _collect(request)
    except BaseException:row={'returncode':1,'stdout':json.dumps({'reason':'worker_unavailable'})}
    print(json.dumps(row,ensure_ascii=False),flush=True)
