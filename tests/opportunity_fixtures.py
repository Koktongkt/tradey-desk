"""Fictional issuer evidence only; no operational issuer or trade history."""
from pathlib import Path
from retained_article import retain_article

SYMBOL = 'ACME'
CIK = '0001999999'
URL = 'https://www.sec.gov/Archives/edgar/data/1999999/000199999926000001/report.htm'


def earnings_pages(*, period='2026-Q3', representation='original'):
    year, quarter = period.split('-')
    end = {'Q1':'03-31', 'Q2':'06-30', 'Q3':'09-30', 'Q4':'12-31', 'FY':'12-31'}[quarter]
    title = 'Fictional Acme results' if representation == 'original' else 'Rewritten synthetic report'
    fields = {'TradingSymbol': SYMBOL, 'EntityCentralIndexKey': CIK,
              'EntityRegistrantName': 'Fictional Acme Laboratory Inc.',
              'DocumentType':'10-K' if quarter == 'FY' else '10-Q',
              'DocumentFiscalYearFocus':year, 'DocumentFiscalPeriodFocus':quarter,
              'DocumentPeriodEndDate':f'{year}-{end}'}
    raw = ('<html><body><xbrli:context id="current"><xbrli:entity>'
           f'<xbrli:identifier scheme="http://www.sec.gov/CIK">{CIK}</xbrli:identifier>'
           '</xbrli:entity><xbrli:period>'
           f'<xbrli:startDate>{year}-01-01</xbrli:startDate>'
           f'<xbrli:endDate>{year}-{end}</xbrli:endDate>'
           '</xbrli:period></xbrli:context>'
           + ''.join(f'<ix:nonNumeric name="dei:{name}" contextRef="current">{value}</ix:nonNumeric>'
                     for name, value in fields.items())
           + f'<p>{title}. Synthetic report prose {representation}.</p></body></html>')
    page = {'url':URL, 'returned_url':URL, 'title':title, 'text':title + ' synthetic projection',
            'published_at':'2026-10-21', 'publication_precision':'day'}
    return [retain_article(page, raw)]


def make_root(path: Path, *, active: bool = False) -> Path:
    """Provision only caller-owned temporary roots, via canonical ledger writer."""
    import json
    import sqlite_ledger as storage
    if not path.is_dir() or any(path.iterdir()):
        raise ValueError('empty_owned_temporary_root_required')
    (path / 'private').mkdir(mode=0o700)
    (path / 'autonomy_config.json').write_text(json.dumps({'enabled':False, 'broker_mode':'paper'}))
    if active:
        storage.append_jsonl(path / 'private/opportunity_policy.jsonl', {
            'record_type':'activation', 'schema_version':1, 'policy_version':1,
            'timestamp':'2026-11-04T12:00:00+00:00', 'manifest_sha256':'a'*64})
    return path
