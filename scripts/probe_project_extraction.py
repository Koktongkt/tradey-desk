"""Bounded network-only extraction acceptance probe; never a research cycle."""
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'test_artifacts/project-extraction'


def validate_cohort(value):
    if not isinstance(value, list) or not 1 <= len(value) <= 12:
        raise ValueError('cohort_size')
    for url in value:
        if not isinstance(url, str) or not 1 <= len(url) <= 4096:
            raise ValueError('invalid_url')
        parsed = urlsplit(url)
        if parsed.scheme not in ('http', 'https') or not parsed.hostname or parsed.username or parsed.password:
            raise ValueError('invalid_url')
    if len(set(value)) != len(value):
        raise ValueError('duplicate_url')
    return value


def write_private(path, value):
    import json
    import os
    path = Path(path).absolute()
    if not path.resolve().is_relative_to(ARTIFACTS.resolve()) or path.is_symlink():
        raise ValueError('private_output_required')
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ARTIFACTS, 0o700)
    os.chmod(path.parent, 0o700)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2)


def run_probe(urls, mode, runner=None, *, now=None):
    import datetime as dt
    from time import monotonic
    from alpha_radar import validate_structured_page, filter_evidence
    urls = validate_cohort(urls)
    if mode not in ('worker', 'focused'):
        raise ValueError('invalid_mode')
    now = now or dt.datetime.now(dt.timezone.utc)
    runner = runner or run_source
    rows = []
    for url in urls:
        start = monotonic()
        result, detail = runner(url, mode)
        failures = []
        page = validate_structured_page(url, result, failed=lambda reason: failures.append(reason))
        accepted, rejected = filter_evidence([page], now=now) if page else ([], [])
        reason = 'accepted' if accepted else (rejected[0]['reason'] if rejected else (failures or ['provider_error'])[0])
        rows.append({'requested_url': url, 'returned_url': (result.get('page') or {}).get('url'),
                     'transport_status': result.get('status'), 'accepted': bool(accepted), 'reason': reason,
                     'publication_basis': 'article_evidence' if page and page.get('published_at') else 'unknown',
                     'published_at': page.get('published_at') if page else None,
                     'elapsed_seconds': monotonic() - start, **detail,
                     'request_count_complete': bool(detail.get('attempts'))})
    count = sum(row['accepted'] for row in rows)
    return {'mode': mode, 'as_of': now.isoformat(), 'total': len(urls), 'accepted': count,
            'rejected': len(rows) - count, 'elapsed_seconds': sum(r['elapsed_seconds'] for r in rows),
            'request_count': sum(len(r.get('attempts', [])) for r in rows)
                if all(r['request_count_complete'] for r in rows) else None, 'rows': rows}


def run_source(url, mode):
    """Use the real hard-boundary owners; only their launch command is adapted."""
    import json
    import os
    import subprocess
    import tempfile
    from unittest.mock import patch
    import structured_extraction as worker
    import focused_capture as capture
    from runtime_paths import hermes_runtime
    python, source = hermes_runtime()
    project = Path(os.environ.get('TRADEY_PROBE_PROJECT_ROOT', ROOT)).resolve()
    ARTIFACTS.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(ARTIFACTS, 0o700)
    with tempfile.TemporaryDirectory(prefix='probe-', dir=ARTIFACTS) as directory:
        telemetry = Path(directory) / 'telemetry.json'
        bootstrap = (
            'import os,sys,runpy; '
            "os.environ.pop('PYTHONHOME',None); os.environ.pop('PYTHONPATH',None); os.environ.pop('VIRTUAL_ENV',None); "
            f'sys.path.insert(0,{str(source)!r}); sys._hermes_pin_default_home=True; import hermes_bootstrap; '
            f'sys.path.insert(0,{str(project)!r}); '
            f'runpy.run_path({str(Path(__file__).resolve())!r},run_name="__main__")'
        )
        command = [python, '-I', '-c', bootstrap, '--child', mode, url, str(telemetry), str(source), str(project)]
        if mode == 'worker':
            with patch.object(worker, 'worker_command', return_value=command):
                result = worker.run_worker(url, 30)
        else:
            try:
                with patch.object(capture, 'focused_command', return_value=command):
                    completed = capture.run_focused(['hermes'], input='', capture_output=True,
                        text=True, timeout=30, cwd=project)
                result = json.loads(completed.stdout) if completed.returncode == 0 else worker.failure('worker_exit')
                # Success requires the parent's authenticated, completed receipt.
                if result.get('status') == 'ok':
                    result = completed.focused_pages.get(url, worker.failure('malformed_response'))
            except subprocess.TimeoutExpired:
                result = worker.failure('timeout')
            except (OSError, ValueError):
                result = worker.failure('worker_unavailable')
        detail = json.loads(telemetry.read_text()) if telemetry.exists() else {'attempts': [], 'harness_failure': 'no_telemetry'}
        return result, detail


def child(mode, url, telemetry, source, project):
    """Deterministic network tool driver, not an agent/model invocation.

    Providers, routing, validators and extraction functions are NOT replaced.
    Profiling observes calls; the only CLI substitution removes model selection.
    """
    import asyncio
    from contextlib import redirect_stdout
    import hashlib
    import json
    import os
    import subprocess
    import sys
    import threading
    import time
    source, project = Path(source).resolve(), Path(project).resolve()
    baseline = project != ROOT.resolve()
    os.umask(0o077)
    os.environ['WEB_TOOLS_DEBUG'] = 'false'
    import hermes_constants
    # Sink redirection only: retain real HERMES_HOME/config/provider selection.
    # Includes legacy cache reads/writes and full-text spill in baseline children.
    original_dir = hermes_constants.get_hermes_dir
    sink = Path(telemetry).parent / 'sinks'
    sink.mkdir(mode=0o700)
    def private_dir(name, *args, **kwargs):
        if str(name).startswith(('cache/', 'logs')):
            target = sink / str(name)
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            return target
        return original_dir(name, *args, **kwargs)
    hermes_constants.get_hermes_dir = private_dir
    import hermes_cli.main as cli
    from tools import web_tools
    from tools.registry import registry
    import plugins.web.keyless_mcp as ring
    # Align process-local random rotation; never persist/change global settings.
    ring._ring_cursor = 0
    from hermes_cli.config import load_config
    config = load_config()
    import extraction_worker
    paths = {name: str(Path(sys.modules[name].__file__).resolve()) for name in
             ('hermes_cli.main', 'tools.web_tools', 'tools.registry', 'plugins.web.keyless_mcp', 'tools.url_safety')}
    assert all(Path(path).is_relative_to(source) for path in paths.values()), 'wrong Hermes module root'
    detail = {'entrypoint': mode, 'source_root': str(source), 'project_root': str(project),
              'source_sha': subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'], text=True).strip(),
              'project_sha': subprocess.check_output(['git','-C',str(project),'rev-parse','HEAD'], text=True).strip(),
              'module_paths': paths, 'patched_publication_module': (source/'tools/web_publication.py').exists(),
              'config_sha256': hashlib.sha256(json.dumps(config, sort_keys=True, default=str).encode()).hexdigest(),
              'ring_cursor_initial': 0, 'ring_origin': str(Path(ring.__file__).resolve()),
              'attempts': [], 'provider_calls': [], 'cache_calls': 0, 'baseline': baseline}
    if not baseline:
        assert not detail['patched_publication_module'], 'unpatched compatibility root required'
    write_private(telemetry, detail)
    started = time.monotonic()
    def profile(frame, event, arg):
        if event == 'return' and frame.f_globals.get('__name__') == 'http.client' and frame.f_code.co_name == 'getresponse':
            detail.setdefault('http_statuses', []).append(getattr(arg, 'status', None))
        if event != 'call':
            return
        module = frame.f_globals.get('__name__', '')
        name = frame.f_code.co_name
        if module.startswith('plugins.web.') and (name == 'extract' or name.endswith('_extract_keyless') or name == 'mcp_call'):
            detail['provider_calls'].append({'module': module, 'function': name})
            write_private(telemetry, detail)
        if module in ('autotrader', 'execution', 'broker_bridge', 'broker_mcp_bridge') or (
            module == 'alpha_radar' and name in ('run_cycle','record_source_verification_diagnostic','gather_evidence')):
            raise RuntimeError('forbidden_probe_path')
        if module == 'tools.web_result_cache' and name in ('extract_cache_get','extract_cache_put'):
            detail['cache_calls'] += 1
            if not baseline:
                raise RuntimeError('shared_cache_forbidden')
        # Actual HTTP request starts (not successful response claims); thread-safe
        # under the GIL. Persist immediately so killed attempts remain visible.
        if (module == 'httpx._client' and name == '_send_single_request') or (
            module == 'requests.sessions' and name == 'send') or (
            module == 'http.client' and name == 'request'):
            request = frame.f_locals.get('request')
            endpoint = str(getattr(request, 'url', '')) if request is not None else (
                str(getattr(frame.f_locals.get('self'), 'host', '')) + str(frame.f_locals.get('url', '')))
            detail['attempts'].append({'transport': module, 'url': endpoint,
                                       'started_seconds': time.monotonic() - started})
            write_private(telemetry, detail)
    sys.setprofile(profile)
    threading.setprofile_all_threads(profile)
    try:
        if mode == 'worker':
            extraction_worker.main()
        else:
            import focused_wrapper
            result = None
            def tool_driver():
                nonlocal result
                raw = registry.dispatch('web_extract', {'urls': [url], 'char_limit': 6000})
                rows, reason = extraction_worker.provider_rows(raw)
                result = extraction_worker.error(reason) if reason else extraction_worker.project_row(rows[0])
                return 0
            cli.main = tool_driver
            with redirect_stdout(sys.stderr):
                focused_wrapper.main()
            print(json.dumps(result))
    finally:
        sys.setprofile(None)
        threading.setprofile_all_threads(None)
        write_private(telemetry, detail)


def main():
    import argparse
    import datetime as dt
    import json
    import os
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == '--child':
        child(*sys.argv[2:])
        return
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--mode', choices=('worker','focused'), required=True)
    parser.add_argument('--as-of', help='freeze evidence clock (ISO UTC); not provider time')
    parser.add_argument('--project-root', type=Path, default=ROOT, help='baseline checkout (child only)')
    args = parser.parse_args()
    # Validate output before any network action, including symlink escapes.
    target = Path(args.output).absolute()
    if not target.resolve().is_relative_to(ARTIFACTS.resolve()) or target.is_symlink():
        parser.error('private output required')
    os.environ['TRADEY_PROBE_PROJECT_ROOT'] = str(args.project_root.resolve())
    sys.path.insert(0, str(args.project_root.resolve()))
    now = dt.datetime.fromisoformat(args.as_of) if args.as_of else None
    report = run_probe(json.loads(Path(args.cohort).read_text()), args.mode, now=now)
    write_private(target, report)
    print(json.dumps({key: report[key] for key in ('mode','total','accepted','rejected','elapsed_seconds','request_count')}))


if __name__ == '__main__':
    main()
