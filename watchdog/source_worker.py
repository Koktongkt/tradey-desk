"""Credential-free deterministic SEC/issuer/earnings worker.

Only reviewed public origins; no host config, memory, ledger or broker imports.
SEC evidence is expressly filing metadata, NOT extracted financial metrics.
Issuer RSS is machine-dated announcement text, NOT full article coverage.
Date-only next earnings and absent previous-report proof remain explicit gaps.
"""
import concurrent.futures
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import html
import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

PROFILES = {
    'BA': ('0000012927', 'investors.boeing.com'),
    'AMRX': ('0001723128', 'investors.amneal.com'),
    'XHR': ('0001616000', 'investors.xeniareit.com'),
    'ZIM': ('0001654126', 'investors.zim.com'),
    'MSFT': ('0000789019', None),
}
FORMS = {'8-K', '10-Q', '10-K', '6-K', '20-F', '8-K/A', '10-Q/A', '10-K/A', '6-K/A', '20-F/A'}
MAX_BYTES = 2_000_000


def timestamp(value):
    dt = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if dt.tzinfo is None:
        raise ValueError('source_freshness_unknown')
    return dt.astimezone(timezone.utc).isoformat()


def public_url(url, hosts):
    parts = urllib.parse.urlsplit(url)
    if (parts.scheme != 'https' or parts.hostname not in hosts or parts.username
            or parts.password or parts.port not in (None, 443)):
        raise ValueError('source_url_rejected')
    return url


class SafeRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self, hosts):
        self.hosts = hosts
        super().__init__()

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        public_url(newurl, self.hosts)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(url, hosts):
    public_url(url, hosts)
    req = urllib.request.Request(url, headers={
        'User-Agent': 'TradeyDesk InvestorMonitor research@tradey-desk.example',
        'Accept': 'application/json, application/rss+xml, text/html'})
    # Outer JSONCommand covers DNS, all redirects, parsing and process lifetime.
    with urllib.request.build_opener(SafeRedirect(hosts)).open(req, timeout=6) as response:
        public_url(response.geturl(), hosts)
        body = response.read(MAX_BYTES + 1)
        if len(body) > MAX_BYTES:
            raise ValueError('source_size_limit')
        return body.decode('utf-8')


def sec_records(payload, symbol, cik):
    if symbol not in payload.get('tickers', []):
        raise ValueError('source_symbol_binding_invalid')
    recent = payload['filings']['recent']
    keys = ('accessionNumber', 'form', 'acceptanceDateTime', 'primaryDocument', 'reportDate')
    if len({len(recent[k]) for k in keys}) != 1:
        raise ValueError('source_schema_invalid')
    rows = []
    for index, form in enumerate(recent['form']):
        if form not in FORMS:
            continue
        accession = recent['accessionNumber'][index]
        if not isinstance(accession, str) or not re.fullmatch(r'\d{10}-\d{2}-\d{6}', accession):
            raise ValueError('source_identity_invalid')
        accepted = timestamp(recent['acceptanceDateTime'][index])
        # A fragment binds the observed record to the canonical machine API.
        url = f'https://data.sec.gov/submissions/CIK{cik}.json#{accession}'
        fact = f'{symbol} SEC filing metadata: {form}, accession {accession}, accepted {accepted}, report period {recent["reportDate"][index]}. Financial contents not extracted.'
        rows.append(dict(fingerprint='sec:' + accession, source='sec', url=url,
                         fact=fact, kind='fundamental', primary=True, date_verified=True,
                         published_at=accepted, event_at=accepted, metrics={}))
    if not rows:
        raise ValueError('source_dated_listing_missing')
    return rows


def rss_records(xml, symbol, host):
    root = ET.fromstring(xml)
    if root.tag != 'rss' or root.find('channel') is None:
        raise ValueError('source_schema_invalid')
    rows = []
    for item in root.findall('./channel/item'):
        guid, title, url, raw_date = (item.findtext(k) for k in ('guid', 'title', 'link', 'pubDate'))
        if not all(isinstance(v, str) and v.strip() for v in (guid, title, url, raw_date)):
            raise ValueError('source_identity_or_date_missing')
        # Original article links are metadata only. Some official feeds use
        # HTTP; preserve them literally, never fetch or silently upgrade them.
        parts = urllib.parse.urlsplit(url)
        if (parts.scheme not in ('http', 'https') or parts.hostname != host
                or parts.username or parts.password or parts.port not in (None, 80, 443)):
            raise ValueError('source_url_rejected')
        assert isinstance(raw_date, str) and isinstance(title, str) and isinstance(guid, str)
        dt = parsedate_to_datetime(raw_date)
        if dt.tzinfo is None:
            raise ValueError('source_freshness_unknown')
        accepted = dt.astimezone(timezone.utc).isoformat()
        description = html.unescape(re.sub(r'<[^>]*>', ' ', item.findtext('description') or ''))
        fact = f'{symbol} issuer RSS announcement: {html.unescape(title)}. {description}'.strip()
        content_complete = len(fact) <= 4000
        if not content_complete:
            fact = f'{symbol} issuer RSS headline: {html.unescape(title)}. Full announcement body not extracted.'
        receipt_url = f'https://{host}/rss/pressrelease.aspx#' + urllib.parse.quote(guid, safe='')
        rows.append(dict(fingerprint=f'issuer:{symbol}:{guid}', source='issuer', url=receipt_url,
                         original_document_url=url, content_complete=content_complete,
                         fact=fact, kind='fundamental', primary=True, date_verified=True,
                         published_at=accepted, event_at=accepted, metrics={}))
    if not rows:
        raise ValueError('source_dated_listing_missing')
    return rows


def source_records(symbol, source):
    cik, host = PROFILES[symbol]
    if source == 'sec':
        url = f'https://data.sec.gov/submissions/CIK{cik}.json'
        return url, sec_records(json.loads(fetch(url, {'data.sec.gov'})), symbol, cik)
    if source == 'issuer' and host:
        url = f'https://{host}/rss/pressrelease.aspx'
        return url, rss_records(fetch(url, {host}), symbol, host)
    raise ValueError('source_profile_missing')


def gap(error):
    if isinstance(error, urllib.error.HTTPError):
        code = 'source_fetch_http_' + str(error.code)
    elif isinstance(error, (TimeoutError, urllib.error.URLError)):
        code = 'source_fetch_timeout_or_unavailable'
    elif isinstance(error, ValueError) and re.fullmatch(r'source_[a-z_]+', str(error)):
        code = str(error)
    else:
        code = 'source_schema_invalid'
    return dict(status='gap', reason=code)


def earnings_coverage(symbol):
    # Existing research policy allows this deterministic machine field only as
    # labeled secondary date-only evidence. It cannot satisfy timestamp proof.
    url = f'https://stockanalysis.com/stocks/{symbol.lower()}/'
    try:
        text = fetch(url, {'stockanalysis.com'})
        if re.search(r'earningsDate["\\]*\s*[:=]', text):
            return dict(status='gap', reason='earnings_event_time_unknown',
                        coverage_url=url, precision='date_only_or_unverified',
                        previous_report_status='not_verified')
        return dict(status='gap', reason='earnings_date_not_found', coverage_url=url,
                    previous_report_status='not_verified')
    except Exception as error:
        return gap(error)


def discover(request):
    symbol = request['symbol']
    if symbol not in PROFILES:
        return {'sources': {s: dict(status='gap', reason='source_profile_missing')
                            for s in ('sec', 'issuer', 'earnings')}}
    now = timestamp(request['now'])
    def inspect(source):
        if source == 'earnings':
            return earnings_coverage(symbol)
        try:
            listing, rows = source_records(symbol, source)
            since = timestamp(request['since'][source])
            if any(r['published_at'] > now for r in rows):
                raise ValueError('source_future_timestamp')
            urls = [r['url'] for r in rows if r['published_at'] >= since]
            return dict(status='complete', checked_through=now, coverage_url=listing, urls=urls)
        except Exception as error:
            return gap(error)
    # Fixed three workers, each bounded by process-wide 15s wall budget. No
    # model, credential or memory access; threads do not outlive worker group.
    with concurrent.futures.ThreadPoolExecutor(max_workers=3) as pool:
        sources = dict(zip(('sec', 'issuer', 'earnings'), pool.map(inspect, ('sec', 'issuer', 'earnings'))))
    return dict(sources=sources)


def retrieve(request):
    symbol, source, url = request['symbol'], request['source'], request['url']
    if symbol not in PROFILES or source not in ('sec', 'issuer'):
        raise ValueError('source_profile_missing')
    _, rows = source_records(symbol, source)
    matched = [row for row in rows if row['url'] == url]
    if len(matched) != 1:
        raise ValueError('source_record_binding_invalid')
    row = matched[0]
    row['retrieved_at'] = datetime.now(timezone.utc).isoformat()
    return dict(receipt=row)


def main():
    try:
        request = json.loads(sys.stdin.read(65537))
        if len(sys.argv) != 2 or sys.argv[1] not in ('discover', 'retrieve'):
            raise ValueError('operation_rejected')
        allowed = ({'symbol', 'since', 'source_priority', 'now'} if sys.argv[1] == 'discover'
                   else {'symbol', 'source', 'url', 'now'})
        if set(request) != allowed:
            raise ValueError('request_rejected')
        result = discover(request) if sys.argv[1] == 'discover' else retrieve(request)
        print(json.dumps(result, allow_nan=False))
        return 0
    except Exception:
        print('source_worker_failed', file=sys.stderr)
        return 3


if __name__ == '__main__':
    raise SystemExit(main())
