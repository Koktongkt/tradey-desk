"""Private, bounded focused handoff probe. Never invokes a research cycle.

Run only in an isolated worktree. No intake, rescue, synthesis, review or broker
entrypoint is used. Both paths retain installed model/provider routing. The
baseline is loaded from a separately pinned checkout, never the live tree.
"""
from pathlib import Path
import datetime as dt
import json
import os
import re
import stat
import sys
from time import monotonic

ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / 'test_artifacts/focused-coverage-25'


def private_path(value):
    path = Path(value).absolute()
    root = ARTIFACTS.absolute()
    if '..' in path.parts or not path.is_relative_to(root) or path == root:
        raise ValueError('private_path')
    for item in (path, *path.parents):
        if item.is_symlink():
            raise ValueError('private_path_symlink')
    if path.exists() and (not path.is_file() or path.stat().st_nlink != 1):
        raise ValueError('private_path_type')
    return path


def write_private(path, value):
    """No replacement of existing files; no-follow dirfd walk at every hop."""
    path = private_path(path)
    ARTIFACTS.mkdir(mode=0o700, parents=True, exist_ok=True)
    fd = os.open(ARTIFACTS, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
    try:
        os.fchmod(fd, 0o700)
        relative = path.relative_to(ARTIFACTS.absolute())
        for part in relative.parts[:-1]:
            try:
                os.mkdir(part, 0o700, dir_fd=fd)
            except FileExistsError:
                pass
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
            os.fchmod(fd, 0o700)
        target = os.open(relative.name, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=fd)
        with os.fdopen(target, 'w') as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, indent=2, default=str)
    finally:
        os.close(fd)


def parse_as_of(value):
    try:
        stamp = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
        if stamp.tzinfo is None or stamp.utcoffset() != dt.timedelta(0):
            raise ValueError
        return stamp
    except (AttributeError, TypeError, ValueError) as exc:
        raise ValueError('explicit_utc_as_of_required') from exc


def validate_cohort(rows):
    from focused_search import search_prompt, valid_url
    if not isinstance(rows, list) or not 1 <= len(rows) <= 5:
        raise ValueError('cohort_size')
    seen = set()
    for row in rows:
        if (not isinstance(row, dict) or set(row) != {'symbol', 'catalyst', 'event_date', 'urls'}
                or not isinstance(row['symbol'], str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}', row['symbol'])
                or row['symbol'] in seen or not isinstance(row['catalyst'], str)
                or not 1 <= len(row['catalyst']) <= 2000 or not isinstance(row['urls'], list)
                or not 1 <= len(row['urls']) <= 1 or not all(valid_url(u) for u in row['urls'])):
            raise ValueError('invalid_cohort')
        try:
            dt.date.fromisoformat(row['event_date'])
        except (ValueError, TypeError) as exc:
            raise ValueError('invalid_event_date') from exc
        seen.add(row['symbol'])
    if len(search_prompt(rows).encode()) > 24000:
        raise ValueError('cohort_bytes')
    return rows


def account(rows, result, accepted):
    """Count actual selected identities separately from candidate bindings."""
    selected = set(result.allocation.unique_urls)
    submitted, pages = set(result.submitted_urls), set(result.pages)
    if not pages <= submitted <= selected:
        raise ValueError('accounting')
    counts, union = {}, set()
    for row in rows:
        symbol = row['symbol']
        owned = set(result.allocation.by_symbol.get(symbol, []))
        good = set(accepted.get(symbol, []))
        if not good <= (owned & pages) or not owned <= selected:
            raise ValueError('accounting')
        union.update(good)
        counts[symbol] = {'available': result.allocation.available_counts.get(symbol),
                          'selected': len(owned), 'submitted': len(owned & submitted),
                          'extracted': len(owned & pages), 'accepted': len(good)}
    return {'candidates': counts, 'unique': {'selected': len(selected), 'submitted': len(submitted),
                                           'extracted': len(pages), 'accepted': len(union)},
            'network_attempted': None, 'network_request_count': None}


def install_safety(directory):
    """Process-local fail-closed audit guard, not an OS security sandbox.

    Config and credentials may be read through existing routing. Mutation outside
    the private sink is forbidden (including auth refresh). No shared patch.
    """
    import tempfile
    sink = Path(directory).resolve()
    os.umask(0o077)
    sys.dont_write_bytecode = True
    os.environ['TMPDIR'] = str(sink)
    # Native WSP defaults next to the installed plugin, not HERMES_HOME.
    # Set its supported cache sink before registration/import; never widen guard.
    os.environ['WSP_CACHE_DIR'] = str(sink / 'wsp-cache')
    tempfile.tempdir = str(sink)
    os.environ['HERMES_HOME'] = str(sink)
    # Installed plugins are read-only inputs too. An empty private home would
    # silently omit native WSP registration while retaining search_backend=wsp.
    for name in ('config.yaml', '.env', 'auth.json', 'plugins'):
        try:
            source = Path.home()/'.hermes'/name
            if name == 'auth.json':
                source = Path('/home/hermes/.hermes/cache/scratch/probe-homes/auth.json')
            sink.joinpath(name).symlink_to(source)
        except FileExistsError:
            pass
    # The dispatcher's pure identity/date helpers import alpha_radar, which
    # imports ledger exception classes and functions. Permit those imports but
    # disable ledger entrypoints before any caller can bind their aliases.
    import durable_jsonl
    import sqlite_ledger
    def no_ledger(*args, **kwargs):
        raise PermissionError('forbidden_probe_ledger')
    for name in ('append_jsonl', 'read_jsonl'):
        setattr(durable_jsonl, name, no_ledger)
    for name in ('append_jsonl', 'read_jsonl', 'read_jsonl_readonly',
                 'migrate_jsonl', 'verify_database', 'backup_database', '_connect', 'main'):
        setattr(sqlite_ledger, name, no_ledger)
    forbidden = {'autotrader', 'execution', 'broker_bridge', 'broker_mcp_bridge',
                 'reviewer', 'intake'}
    def allowed(path):
        if isinstance(path, int) or path is None:
            return
        value = Path(os.fsdecode(path)).absolute()
        if str(value) == '/dev/null':
            return
        if not value.resolve().is_relative_to(sink):
            raise PermissionError('forbidden_probe_write')
    def audit(event, args):
        if event == 'import' and args[0].split('.')[0] in forbidden:
            raise PermissionError('forbidden_probe_module')
        if event == 'open':
            mode, flags = args[1], args[2]
            if (isinstance(mode, str) and any(c in mode for c in 'wax+')) or (isinstance(flags, int) and flags & (os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_TRUNC)):
                allowed(args[0])
        elif event == 'sqlite3.connect':
            allowed(args[0])
        elif event in {'os.mkdir', 'os.remove', 'os.rmdir', 'os.chmod', 'os.truncate'}:
            allowed(args[0])
        elif event in {'os.rename', 'os.link', 'os.symlink'}:
            allowed(args[0]); allowed(args[1])
    sys.addaudithook(audit)


def child_diagnostics(directory):
    """Private count-only first-loss instrumentation; never record provider data."""
    import research_extraction as project
    state = {'pid': os.getpid(), 'events': [], 'stdout_bytes': 0, 'stderr_bytes': 0}
    target = Path(directory) / ('boundary-counts-' + str(os.getpid()) + '.json')
    def save():
        with target.open('w') as stream:
            json.dump(state, stream)
    def event(stage, **counts):
        if len(state['events']) < 32:
            state['events'].append({'stage': stage, **counts})
        save()
    size = project._size
    def measured_size(rows):
        try:
            count = len(json.dumps({'results': rows}, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode())
            row_bytes = [len(json.dumps(row, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode()) for row in rows]
            content_chars = [len(row.get('content', '')) if isinstance(row.get('content'), str) else None for row in rows]
            event('raw_size', bytes=count, rows=len(rows), row_bytes=row_bytes, content_chars=content_chars)
        except (TypeError, ValueError, RecursionError, UnicodeError):
            return size(rows)  # The real validator owns malformed-data semantics.
        try:
            return size(rows)
        except project._Failure as exc:
            event('raw_size_refusal', output_limit=exc.reason == 'output_limit')
            raise
    project._size = measured_size
    envelope = project._envelope
    def measured_envelope(rows):
        raw = envelope(rows)
        event('projected_envelope', bytes=len(raw.encode()), rows=len(rows))
        return raw
    project._envelope = measured_envelope
    class CountStream:
        def __init__(self, original, name):
            self.original, self.name = original, name
        def write(self, text):
            key = self.name + '_bytes'
            state[key] += len(text.encode('utf-8'))
            save()
            return self.original.write(text)
        def __getattr__(self, name):
            return getattr(self.original, name)
    sys.stdout = CountStream(sys.stdout, 'stdout')
    sys.stderr = CountStream(sys.stderr, 'stderr')


def child_sinks(directory):
    """Redirect known Hermes output sinks; keep settings/auth lookup unchanged."""
    sink = Path(directory)
    install_safety(sink)
    import hermes_constants as constants
    original = constants.get_hermes_dir
    def private_dir(name, *args, **kwargs):
        if str(name).startswith(('cache', 'logs', 'sessions', 'image_cache', 'audio_cache')):
            target = sink / str(name)
            target.mkdir(parents=True, exist_ok=True, mode=0o700)
            return target
        return original(name, *args, **kwargs)
    constants.get_hermes_dir = private_dir
    import hermes_state
    hermes_state.DEFAULT_DB_PATH = sink / 'state.db'
    child_diagnostics(sink)


def guarded_command(command, sink):
    """Add sink guard before wrapper imports, retaining real bootstrap/CLI args."""
    command = list(command)
    index = command.index('-c') + 1
    marker = 'runpy.run_path('
    prefix, tail = command[index].split(marker, 1)
    command[index] = (prefix + f'runpy.run_path({str(Path(__file__).resolve())!r})["child_sinks"]({str(sink)!r}); '
                      + marker + tail)
    return command


def execute(rows, *, as_of, sink, baseline_root=None):
    from contextlib import ExitStack
    from unittest.mock import patch
    import hashlib
    import subprocess
    import focused_capture as capture
    import structured_extraction as workers
    import alpha_radar as radar
    from runtime_paths import hermes_runtime
    python, source = hermes_runtime()
    # Load old modules in a separate CLI invocation with PYTHONPATH rooted at
    # the archived checkout (the caller selects it before importing this file).
    if baseline_root is not None:
        if Path(radar.__file__).resolve().parent != Path(baseline_root).resolve():
            raise ValueError('baseline_module_root')
    from hermes_cli.config import load_config
    cfg = load_config()
    identity = radar.configured_default_model()
    details = {'model_provider': identity[0], 'model': identity[1],
               'config_sha256': hashlib.sha256(json.dumps(cfg, sort_keys=True, default=str).encode()).hexdigest(),
               'runtime_python': python, 'runtime_source': str(source),
               'runtime_sha': subprocess.check_output(['git','-C',str(source),'rev-parse','HEAD'],text=True).strip(),
               'project_module': radar.__file__, 'as_of': as_of.isoformat(),
               'mode': 'baseline' if baseline_root else 'new', 'timings': [],
               'cache': 'isolated empty sinks; remote provider caches unknown',
               'calls': [], 'network_attempted': None, 'network_request_count': None}
    original_focus, original_worker = capture.focused_command, workers.worker_command
    def focus(*args, **kwargs):
        return guarded_command(original_focus(*args, **kwargs), sink)
    def worker():
        return guarded_command(original_worker(), sink)
    def observed(stage, fn):
        def call(*args, **kwargs):
            start = monotonic()
            try:
                out = fn(*args, **kwargs)
                details['calls'].append({'stage': stage, 'urls': args[0] if args and isinstance(args[0], list) else None,
                                         'result': out if stage in {'validation','batch'} else str(out)})
                return out
            finally:
                details['timings'].append({'stage':stage,'seconds':monotonic()-start})
        return call
    start = monotonic()
    try:
        with ExitStack() as stack:
            if baseline_root:
                # The archived checkout's focused_capture predates run_private_child.
                pass
            else:
                original_private = capture.run_private_child
                def private_child(*args, **kwargs):
                    done = original_private(*args, **kwargs)
                    details.setdefault('child_outputs', []).append({'stdout': done.stdout.decode() if isinstance(done.stdout,bytes) else done.stdout,
                        'stderr': done.stderr.decode() if isinstance(done.stderr,bytes) else done.stderr, 'returncode':done.returncode})
                    return done
                stack.enter_context(patch.object(capture,'run_private_child',side_effect=private_child))
            stack.enter_context(patch.object(capture,'focused_command',side_effect=focus))
            stack.enter_context(patch.object(workers,'worker_command',side_effect=worker))
            if baseline_root:
                original_read = capture.read_capture
                def read(fd, nonce):
                    if fd is not None:
                        receipt = json.loads(os.pread(fd, capture.MAX_ARTIFACT_BYTES+1, 0))
                        details['extraction_receipt_calls'] = receipt.get('calls', [])
                    return original_read(fd,nonce)
                stack.enter_context(patch.object(capture,'read_capture',side_effect=read))
                done = capture.run_focused(radar.focused_retrieval_command(), input=radar.focused_retrieval_prompt(rows),
                                          timeout=max(0,150-(monotonic()-start)),cwd=sink,capture_output=True,text=True)
                details.update(stdout=done.stdout, stderr=done.stderr, returncode=done.returncode)
                if done.returncode:
                    raise RuntimeError('baseline_child_failed')
                choices = radar.parse_focused_retrieval(done.stdout,{r['symbol'] for r in rows},max_urls=15)
                details['choices'] = choices
                details['captured_pages'] = done.focused_pages
                # The old model decides submission; final choices are NOT actual
                # submission telemetry. Preserve receipt requests separately.
                details['status'] = 'completed'
                details['counts'] = {'candidates': {r['symbol']: {'available':None,'selected':len(choices.get(r['symbol'],[])),
                    'submitted':None,'extracted':None,'accepted':None} for r in rows}}
            else:
                import focused_pipeline as pipeline
                stack.enter_context(patch.object(pipeline,'search_alternatives',side_effect=observed('search',pipeline.search_alternatives)))
                stack.enter_context(patch.object(pipeline,'run_validation_worker',side_effect=observed('validation',pipeline.run_validation_worker)))
                stack.enter_context(patch.object(pipeline,'run_batch_worker',side_effect=observed('batch',pipeline.run_batch_worker)))
                result = pipeline.run_focused_pipeline(rows,deadline=start+150,command=radar.focused_retrieval_command(),cwd=sink,unhealthy_domains=set())
                accepted, quality = {}, {}
                for row in rows:
                    symbol = row['symbol']; good = []; rejected = []
                    for url in result.allocation.by_symbol.get(symbol,[]):
                        if url not in result.pages:
                            continue
                        failures = []
                        page = radar.validate_structured_page(url, {'version':1,'status':'ok','page':result.pages[url]}, failed=failures.append)
                        kept, reasons = radar.filter_evidence([page],now=as_of) if page else ([],[])
                        if kept: good.append(url)
                        else: rejected.append({'url':url,'failures':failures,'quality':reasons})
                    accepted[symbol] = good; quality[symbol] = rejected
                details.update(status='completed', counts=account(rows,result,accepted), quality=quality,
                               outcomes=result.outcomes, selected=result.allocation.by_symbol,
                               pages=result.pages, accepted=accepted,
                               accepted_publishers={s:len({radar.publisher_domain(u) for u in urls}) for s,urls in accepted.items()})
    except Exception as exc:
        details.update(status='blocked', error={'type':type(exc).__name__,'message':str(exc)})
    details['elapsed_seconds'] = monotonic()-start
    return details


def run_probe(rows, *, output, as_of, baseline_root=None):
    output = private_path(output)  # Must precede all imports/network execution.
    if output.exists():
        raise ValueError('output_exists')
    stamp = parse_as_of(as_of)
    rows = validate_cohort(rows)
    sink = output.parent / (output.stem+'-sinks')
    private_path(sink/'sentinel')
    sink.mkdir(parents=True,mode=0o700,exist_ok=False)
    os.chmod(sink,0o700)
    previous = os.environ.get('TMPDIR')
    import tempfile
    old_temp = tempfile.tempdir
    os.environ['TMPDIR'] = str(sink); tempfile.tempdir = str(sink)
    try:
        report = execute(rows,as_of=stamp,sink=sink,baseline_root=baseline_root)
    finally:
        tempfile.tempdir = old_temp
        if previous is None: os.environ.pop('TMPDIR',None)
        else: os.environ['TMPDIR'] = previous
    report['cohort_sha256'] = __import__('hashlib').sha256(json.dumps(rows,sort_keys=True).encode()).hexdigest()
    write_private(output,report)
    return report


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cohort',required=True)
    parser.add_argument('--output',required=True)
    parser.add_argument('--as-of',required=True)
    parser.add_argument('--baseline-root',type=Path)
    args = parser.parse_args()
    private_path(args.output)
    cohort = private_path(args.cohort)
    if cohort.stat().st_size > 24000:
        raise ValueError('cohort_bytes')
    sys.path.insert(0, str(ROOT))
    if args.baseline_root:
        baseline = private_path(args.baseline_root/'alpha_radar.py').parent
        # The baseline modules must win at import: the pinned checkout supplies
        # the old implementation, everything else stays from this worktree.
        sys.path.insert(0, str(baseline))
    else:
        sys.path.insert(0,str(ROOT))
    report = run_probe(json.loads(cohort.read_text()),output=args.output,as_of=args.as_of,baseline_root=args.baseline_root)
    print(json.dumps({'status':report['status'],'elapsed_seconds':report['elapsed_seconds']}))
    return 0 if report['status']=='completed' else 1


if __name__ == '__main__':
    sys.exit(main())
