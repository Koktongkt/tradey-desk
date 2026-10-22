"""Explicitly opt-in, supervised, count-only real-source extraction probe.

Never run by tests without mocked provider acquisition. No model/search/broker
calls. One configured dispatcher acquisition per selected original URL; existing
primary/rescue routes and their deadlines are unchanged. Reports no raw content.
"""
from pathlib import Path
import json
import os
import sys

ROOT = Path(__file__).resolve().parents[1]


def size(value):
    try:
        return len(json.dumps(value, ensure_ascii=True, allow_nan=False, separators=(',', ':')).encode())
    except (TypeError, ValueError, RecursionError, UnicodeError):
        return None


def private_write(path, value):
    # All paths are parent-owned fixed telemetry targets, never provider fields.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'w') as stream:
        os.fchmod(stream.fileno(), 0o600)
        json.dump(value, stream, indent=2, allow_nan=False)


def failed_urls(cohort):
    """Join exact original scout URLs to failed attempt IDs, not domain guesses."""
    import hashlib
    shared = json.loads((cohort / 'shared-discovery.json').read_text())
    attempts = []
    for arm in ('prior', 'v2'):
        attempts.extend(json.loads(line) for line in
                        (cohort / arm / 'test_artifacts/private/source_attempts.jsonl').read_text().splitlines())
    urls = []
    for candidate in shared['candidates']:
        for url in candidate['urls']:
            if any(row.get('fallback_result') == 'output_limit' and
                   row.get('url_id') == hashlib.sha256((row['run_id'] + url).encode()).hexdigest()
                   for row in attempts):
                if url not in urls:
                    urls.append(url)
    if not 1 <= len(urls) <= 3:
        raise ValueError('expected_one_to_three_original_failed_urls')
    return urls


def observe(request, target):
    """Observe actual configured provider rows and real worker/filter boundaries."""
    import asyncio
    import datetime as dt
    from time import monotonic
    from unittest.mock import patch
    import extraction_compat as compat
    import research_extraction as dispatch
    import extraction_worker as worker
    import alpha_radar as radar

    counts = {'routes': [], 'size_checks': [], 'projections': [], 'completed': False}
    started = monotonic()
    timeout = min(30, request.get('timeout_seconds', 30))
    deadline = started + timeout
    seen = set()

    def save():
        private_write(target, counts)

    def summarize(rows):
        if not isinstance(rows, list):
            return []
        return [{'serialized_bytes': size(row),
                 'content_characters': len(row['content']) if isinstance(row, dict) and isinstance(row.get('content'), str) else None,
                 'raw_content_characters': len(row['raw_content']) if isinstance(row, dict) and isinstance(row.get('raw_content'), str) else None,
                 'exact_content_duplicate': isinstance(row, dict) and type(row.get('content')) is str
                    and type(row.get('raw_content')) is str and row['content'] == row['raw_content'],
                 'metadata_bytes': size(row.get('metadata')) if isinstance(row, dict) and 'metadata' in row else None}
                for row in rows]

    primary, keyless = compat.primary, compat.keyless
    original_size, original_project = dispatch._size, dispatch._project

    async def route(kind, name, function, *args, **kwargs):
        token = (kind, name)
        if token in seen:
            raise RuntimeError('probe_duplicate_route_refused')
        seen.add(token)
        record = {'kind': kind, 'ordinal': len(counts['routes']) + 1,
                  'started': True, 'completed': False}
        counts['routes'].append(record)
        save()
        try:
            rows = await function(*args, **kwargs)
            record.update(raw_envelope_bytes=size({'results': rows}), rows=summarize(rows), completed=True)
            # Exercise the unchanged pre-repair raw-cap operation on the same
            # in-memory acquisition, never refetch or save the original rows.
            try:
                original_size(rows)
                record['prechange_raw_cap_outcome'] = 'ok'
            except dispatch._Failure as exc:
                record['prechange_raw_cap_outcome'] = exc.reason
            return rows
        finally:
            save()

    async def wrapped_primary(provider, urls, **kwargs):
        return await route('primary', getattr(provider, 'name', ''), primary, provider, urls, **kwargs)

    async def wrapped_keyless(vendor, urls, **kwargs):
        return await route('keyless', vendor, keyless, vendor, urls, **kwargs)

    def wrapped_size(rows, **kwargs):
        record = {'raw_envelope_bytes': size({'results': rows}),
                  'boundary': ('original_json_validation' if kwargs.get('validation_only') else
                               'validated_duplicate_accounting' if 'fold_duplicates' in kwargs else
                               'projected_envelope'),
                  'validation_only': bool(kwargs.get('validation_only')),
                  'folded_row_indices': sorted(kwargs.get('fold_duplicates', ())),
                  'outcome': 'ok'}
        if 'fold_duplicates' in kwargs:
            eligible = kwargs['fold_duplicates']
            folded = [{k: value for k, value in row.items()
                       if not (index in eligible and k == 'raw_content' and type(value) is str
                               and type(row.get('content')) is str and value == row['content'])}
                      for index, row in enumerate(rows)]
            record['accounted_envelope_bytes'] = size({'results': folded})
        counts['size_checks'].append(record)
        try:
            return original_size(rows, **kwargs)
        except dispatch._Failure as exc:
            record['outcome'] = exc.reason
            raise
        finally:
            save()

    def wrapped_project(*args, **kwargs):
        result = original_project(*args, **kwargs)
        if not kwargs.get('validation_only'):
            counts['projections'].append({'serialized_bytes': size(result),
                'capture_status': result.get('_capture_status'),
                'capture_record_bytes': size(result['_retained_article']) if '_retained_article' in result else None,
                'reason': result.get('reason')})
            save()
        return result

    save()
    with patch.object(compat, 'primary', wrapped_primary), patch.object(compat, 'keyless', wrapped_keyless), \
         patch.object(dispatch, '_size', wrapped_size), patch.object(dispatch, '_project', wrapped_project):
        result = asyncio.run(worker.extract(request))
    counts['worker_status'] = result.get('status')
    counts['worker_reason'] = result.get('reason')
    result_size = size(result)
    counts['worker_serialized_stdout_bytes_including_newline'] = result_size + 1 if result_size is not None else None
    counts['first_output_limit_boundary'] = next((r['boundary'] for r in counts['size_checks']
                                                  if r['outcome'] == 'output_limit'), None)
    counts['capture_status'] = (result.get('page') or {}).get('_capture_status')
    counts['source_accepted'] = False
    counts['acceptance_as_of'] = dt.datetime.now(dt.timezone.utc).isoformat()
    if monotonic() >= deadline:
        counts['source_reason'] = 'timeout'
    else:
        failures = []
        page = radar.validate_structured_page(request['url'], result, deadline=deadline,
                                              failed=failures.append)
        accepted, rejected = radar.filter_evidence([page], now=dt.datetime.fromisoformat(counts['acceptance_as_of'])) if page else ([], [])
        counts['source_accepted'] = bool(accepted)
        counts['source_reason'] = 'accepted' if accepted else (rejected[0]['reason'] if rejected else (failures or ['provider_error'])[0])
    counts['elapsed_seconds'] = monotonic() - started
    counts['completed'] = True
    save()
    return result


def run_live(cohort, output):
    """Use existing native bootstrap and production hard-boundary supervisor."""
    from time import monotonic
    from unittest.mock import patch
    import structured_extraction as supervisor
    from runtime_paths import hermes_runtime
    urls = failed_urls(cohort)
    # Fresh owned directory only. Never overwrite a previous evidence run.
    output.mkdir(mode=0o700, parents=False, exist_ok=False)
    os.umask(0o077)
    python, source = hermes_runtime()
    script = Path(__file__).resolve()
    all_results = []
    total_deadline = monotonic() + 90
    for index, url in enumerate(urls):
        target = output / ('source-' + str(index + 1) + '.json')
        bootstrap = (
            'import os,sys,runpy; '
            "os.environ.pop('PYTHONHOME',None);os.environ.pop('PYTHONPATH',None);os.environ.pop('VIRTUAL_ENV',None);"
            f'sys.path.insert(0,{str(source)!r});sys._hermes_pin_default_home=True;import hermes_bootstrap;'
            f'sys.path.insert(0,{str(ROOT)!r});runpy.run_path({str(script)!r},run_name="__main__")'
        )
        command = [python, '-I', '-c', bootstrap, '--child', str(target)]
        remaining = min(30, total_deadline - monotonic())
        if remaining <= 0:
            all_results.append({'source_index': index + 1, 'supervisor_reason': 'timeout', 'telemetry_complete': False})
            continue
        with patch.object(supervisor, 'worker_command', return_value=command):
            result = supervisor.run_worker(url, remaining)
        try:
            telemetry = json.loads(target.read_text())
        except (OSError, ValueError):
            telemetry = {}
        # Parent never persists worker pages or original URLs/body/auth values.
        all_results.append({'source_index': index + 1, 'supervisor_status': result.get('status'),
            'supervisor_reason': result.get('reason'), 'telemetry_complete': telemetry.get('completed') is True,
            'counts': telemetry})
    private_write(output / 'summary.json', {'source_count': len(urls), 'results': all_results,
        'historical_raw_responses_available': False,
        'limitation': 'Prospective same-configured-route observation, not replay of historical provider bytes; source acceptance is not candidate qualification.'})
    return {'sources': len(urls), 'completed': sum(r.get('telemetry_complete', False) for r in all_results)}


def main():
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--run-live', action='store_true')
    parser.add_argument('--cohort', type=Path, default=ROOT / 'test_artifacts/evidence-bundle-live-20261022T075500Z')
    parser.add_argument('--output', type=Path)
    parser.add_argument('--child', type=Path)
    args = parser.parse_args()
    if args.child:
        from contextlib import redirect_stdout
        from extraction_contract import strict_json_loads
        import extraction_worker as worker
        raw = sys.stdin.buffer.read(worker.MAX_INPUT + 1)
        if len(raw) > worker.MAX_INPUT:
            result = worker.error('invalid_request')
        else:
            with redirect_stdout(sys.stderr):
                result = observe(strict_json_loads(raw), args.child)
        sys.stdout.write(json.dumps(result, ensure_ascii=True, separators=(',', ':')) + '\n')
    else:
        if not args.run_live or args.output is None:
            parser.error('network requires explicit --run-live and fresh --output directory')
        print(json.dumps(run_live(args.cohort, args.output)))


if __name__ == '__main__':
    sys.path.insert(0, str(ROOT))
    main()
