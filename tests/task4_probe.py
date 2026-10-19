"""Offline child scripts for Task 4's real process/executor boundary tests."""
import json
import time
from pathlib import Path


def blocked_probe(pidfile, mode, focused=False):
    setup = r'''
import asyncio, json, os, socket, subprocess, sys, time
from pathlib import Path
from unittest.mock import patch, AsyncMock
from contextlib import ExitStack
import extraction_compat as compat
import extraction_worker as worker

def blocked(*args, **kwargs):
    child = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(30)'],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    Path(PIDFILE).write_text(json.dumps([os.getpid(), child.pid]))
    time.sleep(30)
    return []
class Provider:
    name='fixture'
    def extract(self, urls, format=None): return blocked()
with ExitStack() as stack:
    stack.enter_context(patch.object(compat, 'resolve', return_value=Provider()))
    stack.enter_context(patch.object(compat, 'uses_keyless', return_value=False))
    if MODE == 'dns':
        stack.enter_context(patch.object(socket, 'getaddrinfo', blocked))
    else:
        stack.enter_context(patch.object(compat, 'check_url', AsyncMock(side_effect=lambda u:u)))
    # Await cancellation expires first; asyncio.run must then wait for the
    # still-blocked default executor, which only the real parent can terminate.
    async def short_dispatch(urls, format=None, char_limit=None):
        from research_extraction import extract_tool
        return await extract_tool(urls, format, char_limit, deadline=time.monotonic()+.1)
'''.replace('PIDFILE', repr(str(pidfile))).replace('MODE', repr(mode))
    if focused:
        return setup + r'''
    import hermes_cli.main as cli
    from tools.registry import registry
    import tools.web_tools
    import focused_wrapper as wrapper
    import research_extraction as project
    async def short(urls, format=None, char_limit=None):
        return await original(urls, format, char_limit, deadline=time.monotonic()+.1)
    original = project.extract_tool
    stack.enter_context(patch.object(project, 'extract_tool', short))
    def main():
        registry.dispatch('web_extract', {'urls':['https://news.example/story'], 'char_limit':6000})
    stack.enter_context(patch.object(cli, 'main', main))
    wrapper.main()
'''
    return setup + r'''
    asyncio.run(worker.extract({'version':1,'url':'https://news.example/story'}, short_dispatch))
'''


def assert_dead(test, pidfile):
    pids = json.loads(Path(pidfile).read_text())
    for pid in pids:
        for _ in range(100):
            path = Path(f'/proc/{pid}/stat')
            try:
                if not path.exists() or path.read_text().split()[2] == 'Z':
                    break
            except (FileNotFoundError, ProcessLookupError):
                break  # It disappeared between existence and state observation.
            time.sleep(.01)
        else:
            test.fail(f'owned process {pid} survived hard deadline')
    return pids
