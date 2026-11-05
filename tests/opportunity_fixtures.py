"""Fictional issuer evidence only; no operational issuer or trade history."""
from pathlib import Path
from retained_article import retain_article

SYMBOL = 'ACME'
CIK = '0001999999'
URL = 'https://www.sec.gov/Archives/edgar/data/1999999/000199999926000001/report.htm'


def synthetic_capture_ref():
    """Explicitly fictional capture path; no operational evidence is referenced."""
    import hashlib
    return 'private/opportunity_evidence/' + hashlib.sha256(b'synthetic-capture').hexdigest() + '.json'


def synthetic_resolution_payload(*, period='2026-Q3', cik=CIK):
    """Valid known-binding payload per opportunity_identity._load_binding."""
    import opportunity_identity as identity
    capture = synthetic_capture_ref()
    document = {'document_id': 'sec:000199999926000001/report.htm', 'url': URL,
                'returned_url': URL, 'content_sha256': 'c' * 64,
                'publication_value': '2026-10-21', 'precision': 'day',
                'retained_ref': capture}
    issuer = {'symbol': SYMBOL, 'cik': cik,
              'legal_name': 'Fictional Acme Laboratory Inc.',
              'support_ref': capture + '#dei:current'}
    return {'version': 1, 'status': 'verified',
            'event_id': identity._event_id(cik, period), 'issuer': issuer,
            'family': 'earnings', 'period': period, 'documents': [document],
            'support_refs': [capture + '#dei:current'],
            'reason': 'current_report_cover'}


def synthetic_resolution(*, period='2026-Q3', cik=CIK):
    import opportunity_identity as identity
    return identity._load_binding(synthetic_resolution_payload(period=period, cik=cik))


def policy_row(record_type, **fields):
    import datetime as dt
    stamp = dt.datetime(2026, 11, 4, 12, 0, 0, tzinfo=dt.timezone.utc)
    return dict(record_type=record_type, schema_version=1,
                timestamp=stamp.isoformat(), **fields)


def candidate_link(dossier_hash, event_id, allowance_id):
    import datetime as dt
    stamp = dt.datetime(2026, 11, 4, 12, 0, 0, tzinfo=dt.timezone.utc)
    return {'timestamp': stamp.isoformat(), 'dossier_hash': dossier_hash,
            'event_id': event_id, 'allowance_id': allowance_id}


def review_row(dossier_hash, evidence_id, decisions, *, proposal_hash=None, **extra):
    import datetime as dt
    stamp = dt.datetime(2026, 11, 4, 12, 0, 0, tzinfo=dt.timezone.utc)
    row = {'timestamp': stamp.isoformat(), 'dossier_hash': dossier_hash,
           'evidence_id': evidence_id, 'reviews': decisions}
    if proposal_hash is not None:
        row['proposal_hash'] = proposal_hash
    row.update(extra)
    return row


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


def gap_review_row(*, with_symbol: bool, with_hint: bool, dossier_hash: str | None = None,
                   evidence_id: str | None = None, symbol: str = 'ZZZSYNA') -> dict:
    """Synthetic hashless legacy review row; never operational history.

    67-row shape: {evidence_id, reviews: [{decision, symbol?}, ...], timestamp}
    with the symbol nested inside a review entry. The 5-row hint shape carries
    a 64-hex `proposal_hash` and no `symbol` key anywhere in the row.
    """
    import datetime as dt
    if with_hint and with_symbol:
        raise ValueError('hint_rows_carry_no_symbol')
    stamp = dt.datetime(2026, 11, 4, 12, 0, 0, tzinfo=dt.timezone.utc)
    review = {'decision': 'HOLD'}
    if with_symbol:
        review['symbol'] = symbol
    row = {'evidence_id': evidence_id or 'gap-evidence', 'reviews': [review],
           'timestamp': stamp.isoformat()}
    if with_hint:
        row['proposal_hash'] = 'f' * 64
    if dossier_hash is not None:
        row['dossier_hash'] = dossier_hash
    return row


def gap_trade_row(*, action: str, status: str = 'filled',
                  symbol: str = 'ZZZSYNB') -> dict:
    """Synthetic hashless trade row; top-level symbol, no identifier fields."""
    import datetime as dt
    stamp = dt.datetime(2026, 11, 4, 12, 0, 0, tzinfo=dt.timezone.utc)
    return {'timestamp': stamp.isoformat(), 'action': action,
            'status': status, 'symbol': symbol}


def make_gap_root(path: Path, *, review_gaps: int, hint_rows: int, buy_gaps: int,
                  sell_rows: int, bound_rows: int = 0) -> Path:
    """Provision a caller-owned temporary root holding exactly these shapes."""
    import sqlite_ledger as storage
    root = make_root(path)
    reviews = [gap_review_row(with_symbol=True, with_hint=False,
                              evidence_id=f'gap-review-{index}',
                              symbol=f'ZZZSYNR{index}')
               for index in range(review_gaps)]
    reviews += [gap_review_row(with_symbol=False, with_hint=True,
                               evidence_id=f'gap-hint-{index}')
                for index in range(hint_rows)]
    reviews += [gap_review_row(with_symbol=True, with_hint=False,
                               dossier_hash='a' * 64,
                               evidence_id=f'bound-review-{index}')
                for index in range(bound_rows)]
    for row in reviews:
        storage.append_jsonl(root / 'private/reviews.jsonl', row)
    trades = [gap_trade_row(action='BUY', symbol=f'ZZZSYNB{index}')
              for index in range(buy_gaps)]
    trades += [gap_trade_row(action='SELL', symbol=f'ZZZSYNS{index}')
               for index in range(sell_rows)]
    for row in trades:
        storage.append_jsonl(root / 'trade_journal.jsonl', row)
    return root


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
