"""Tradey-owned post-update URL-admission check; no research or broker actions.

Uses the exact installed extraction-worker bootstrap, validation-only operation.
May perform DNS/config reads. Never fetches articles, calls models or writes
application ledgers. This is not an end-to-end research/provider health check.
"""
from pathlib import Path
import json
import sys

ROOT = Path(__file__).resolve().parents[1]

# Fixed synthetic negative controls; never accept operator-supplied credentials.
CASES = (
    ('sec_public', 'https://www.sec.gov/Archives/edgar/', True, 'success'),
    ('issuer_public', 'https://newsroom.cisco.com/', True, 'success'),
    ('credential_query', 'https://example.org/article?access_token=synthetic-check', False, 'unsafe_url'),
    ('encoded_credential', 'https://example.org/article?%2570assword=synthetic-check', False, 'unsafe_url'),
    ('private_address', 'http://127.0.0.1/article', False, 'unsafe_url'),
)


def check(runner=None):
    if runner is None:
        from structured_extraction import run_validation_worker
        runner = run_validation_worker
    urls = [case[1] for case in CASES]
    try:
        result = runner(urls, timeout_seconds=20)
        from structured_extraction import _valid_validation_response
        if not _valid_validation_response(result, urls) or result.get('status') != 'ok':
            return {'passed': False, 'scope': 'url_safety_only', 'reason': 'validation_worker_failed', 'checks': []}
        by_url = {row['requested_url']: row for row in result['results']}
        checks = []
        for name, url, eligible, reason in CASES:
            row = by_url[url]
            checks.append({'name': name, 'passed': row['eligible'] is eligible and row['reason'] == reason,
                           'reason': row['reason']})
        return {'passed': all(row['passed'] for row in checks), 'scope': 'url_safety_only', 'checks': checks}
    except Exception:
        # Upstream exceptions can contain URLs or credential/config text.
        return {'passed': False, 'scope': 'url_safety_only', 'reason': 'compatibility_check_failed', 'checks': []}


def main():
    if str(ROOT) not in sys.path:
        sys.path.insert(0, str(ROOT))
    result = check()
    print(json.dumps(result, sort_keys=True))
    return 0 if result['passed'] else 1


if __name__ == '__main__':
    raise SystemExit(main())
