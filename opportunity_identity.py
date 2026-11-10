"""Pure trusted-acquisition identity resolution (not a model-output validator).

Only acquisition-owned pages and explicitly trusted index records may enter this
API. Matching JSON shape or a local digest does not authenticate a publisher.
No resolver here fetches, initializes ledgers, or authorizes a review/BUY.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
import datetime as dt
from hashlib import sha256
from html.parser import HTMLParser
import json
import re
from pathlib import Path
import os
import secrets
import stat
from urllib.parse import urlsplit

from retained_article import MAX_CAPTURE_BYTES, original_text


@dataclass(frozen=True)
class IssuerBinding:
    symbol: str
    cik: str
    legal_name: str
    support_ref: str


@dataclass(frozen=True)
class DocumentObservation:
    document_id: str
    url: str
    returned_url: str
    content_sha256: str
    publication_value: str
    precision: str
    retained_ref: str


@dataclass(frozen=True)
class EventResolution:
    status: str
    event_id: str | None
    issuer: IssuerBinding | None
    family: str | None
    period: str | None
    documents: tuple[DocumentObservation, ...]
    support_refs: tuple[str, ...]
    reason: str

    def __post_init__(self):
        object.__setattr__(self, 'documents', tuple(self.documents))
        object.__setattr__(self, 'support_refs', tuple(self.support_refs))


def _canonical(value):
    return json.dumps(value, sort_keys=True, separators=(',', ':'), ensure_ascii=True, allow_nan=False).encode('ascii')


def _event_id(cik, period):
    return 'oe1:' + sha256(_canonical({'version':1, 'cik':cik, 'family':'earnings', 'period':period})).hexdigest()


def _capture_ref(page):
    return 'private/opportunity_evidence/' + sha256(_canonical(page['_retained_article'])).hexdigest() + '.json'


def observation_provenance(page: dict) -> dict:
    """Validated acquisition metadata only; a named capture is not yet durable."""
    if not isinstance(page, dict) or page.get('_capture_status') != 'complete' or original_text(page) is None:return {}
    capture = page['_retained_article']
    return {'returned_url':capture['returned_url'], 'retained_ref':_capture_ref(page),
            'representation_sha256':capture['sha256']}


def _sec_archive(url):
    parts = urlsplit(url)
    return parts.hostname in ('sec.gov','www.sec.gov') and parts.path.startswith('/Archives/edgar/data/')


def _locator(url):
    if not isinstance(url, str):return None
    parts = urlsplit(url)
    if parts.scheme != 'https' or parts.netloc not in ('www.sec.gov', 'sec.gov') or parts.query or parts.fragment:return None
    match = re.fullmatch(r'/Archives/edgar/data/([1-9][0-9]{0,9})/([0-9]{18})/([A-Za-z0-9][A-Za-z0-9_.-]*\.(?:htm|html))', parts.path)
    if not match:return None
    cik, accession, filename = match.groups()
    canonical_cik = cik.zfill(10)  # Only after strict lexical validation of the SEC numeric locator.
    # The accession prefix identifies the submitter (possibly a filing agent),
    # not the registrant. Identity agreement uses this directory CIK instead.
    return canonical_cik, 'sec:' + accession + '/' + filename


class _Cover(HTMLParser):
    """Collect context-bound DEI facts, never free text/date/footer guesses."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack = []
        self.context = None
        self.contexts = {}
        self.facts = {}
        self.fact = None
        self.field = None
        self.buffer = []
        self.bad_structure = False
        self.closed_html = False

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag not in ('meta','link','br','hr','img','input','wbr','source','area','base','col','embed','param','track'):
            self.stack.append(tag)
        if tag == 'xbrli:context':
            if 'html' not in self.stack or 'body' not in self.stack:self.bad_structure = True
            self.context = attrs.get('id')
            if self.context in self.contexts:self.bad_structure = True
            self.contexts.setdefault(self.context, {})
        if tag in ('xbrli:identifier', 'xbrli:startdate', 'xbrli:enddate', 'xbrli:instant') and self.context:
            if tag == 'xbrli:identifier' and attrs.get('scheme') != 'http://www.sec.gov/CIK':self.bad_structure = True
            self.field = tag
            self.buffer = []
        if tag == 'ix:nonnumeric' and not any(t in self.stack for t in ('footer', 'nav', 'aside', 'script', 'style')):
            if 'html' not in self.stack or 'body' not in self.stack:self.bad_structure = True
            self.fact = (attrs.get('contextref'), attrs.get('name'))
            self.buffer = []

    def handle_data(self, data):
        if self.fact is not None or self.field is not None:self.buffer.append(data)

    def handle_endtag(self, tag):
        if tag == 'html':self.closed_html = True
        if tag == 'ix:nonnumeric' and self.fact is not None:
            context, name = self.fact
            self.facts.setdefault(context, {}).setdefault(name, []).append(''.join(self.buffer))
            self.fact = None
        if tag == self.field:
            self.contexts[self.context].setdefault(tag, []).append(''.join(self.buffer))
            self.field = None
        if tag == 'xbrli:context':self.context = None
        if tag in self.stack:
            index = len(self.stack) - 1 - self.stack[::-1].index(tag)
            self.stack = self.stack[:index]


def _valid_legal_name(value):
    return isinstance(value, str) and 1 <= len(value) <= 512 and value.strip() == value


def _cover(raw, symbol, cik, legal_name=None):
    parser = _Cover()
    parser.feed(raw)
    parser.close()
    if parser.bad_structure or parser.stack or not parser.closed_html:return 'incomplete', []
    found = []
    complete_subjects = 0
    # Partial contradictory identity must not be hidden by a historical binding.
    for facts in parser.facts.values():
        for name, expected in (('TradingSymbol', symbol), ('EntityCentralIndexKey', cik)):
            if 'dei:' + name in facts and set(facts['dei:' + name]) != {expected}:
                return 'issuer_conflict', []
    legal_names = {value for facts in parser.facts.values()
                   for value in facts.get('dei:EntityRegistrantName', [])}
    if (any(not _valid_legal_name(value) for value in legal_names) or len(legal_names) > 1
            or (legal_name is not None and legal_names and legal_names != {legal_name})):
        return 'issuer_conflict', []
    names = ('TradingSymbol', 'EntityCentralIndexKey', 'EntityRegistrantName', 'DocumentType',
             'DocumentFiscalYearFocus', 'DocumentFiscalPeriodFocus', 'DocumentPeriodEndDate')
    for context, facts in parser.facts.items():
        if not all('dei:' + name in facts for name in names):continue
        complete_subjects += 1
        if any(len(set(facts['dei:' + name])) != 1 for name in names):return 'conflict', []
        values = [facts['dei:' + name][0] for name in names]
        ticker, issuer_cik, legal, kind, year, quarter, end = values
        if ticker != symbol or issuer_cik != cik:return 'conflict', []
        if (kind not in ('10-Q', '10-K') or not _valid_legal_name(legal)
                or not re.fullmatch(r'[0-9]{4}', year) or quarter not in ('Q1','Q2','Q3','Q4','FY')):continue
        ctx = parser.contexts.get(context, {})
        if ctx.get('xbrli:identifier') != [cik] or ctx.get('xbrli:enddate', ctx.get('xbrli:instant')) != [end]:continue
        try:
            period_end = dt.date.fromisoformat(end)
        except ValueError:continue
        if not 1 <= int(year) <= 9999 or abs(int(year) - period_end.year) > 1:continue
        if (kind == '10-K') != (quarter == 'FY'):continue
        if not isinstance(context, str) or not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_.-]{0,127}', context):continue
        found.append((legal, year + '-' + quarter, context))
    if len({(name, period) for name, period, _ in found}) > 1:return 'conflict', found
    if complete_subjects != len(found):return 'invalid', []
    return ('verified' if found else 'unknown'), found


_CAPTURE = r'private/opportunity_evidence/[0-9a-f]{64}\.json'
_RESOLUTION_KEYS = {'version','status','event_id','issuer','family','period','documents','support_refs','reason'}
_ISSUER_KEYS = {'symbol','cik','legal_name','support_ref'}
_DOCUMENT_KEYS = {'document_id','url','returned_url','content_sha256','publication_value','precision','retained_ref'}


def _public_url(value):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096 or any(ord(c) < 33 for c in value):return False
    try:
        url = urlsplit(value)
        return url.scheme == 'https' and bool(url.hostname) and not url.username and not url.password
    except ValueError:return False


def _valid_publication(value, precision):
    if not isinstance(value, str) or len(value) > 128 or precision not in ('','day','second','instant'):return False
    try:
        if precision == 'day' and re.fullmatch(r'[0-9]{4}-[0-9]{2}-[0-9]{2}', value):
            return dt.date.fromisoformat(value).isoformat() == value
        if precision:
            return dt.datetime.fromisoformat(value.replace('Z','+00:00')).utcoffset() is not None
        return True
    except ValueError:return False


def _load_binding(record):
    """Strict versioned serialization, not an authenticity/authorization check."""
    def invalid():raise ValueError('invalid_known_resolution')
    if not isinstance(record, dict) or set(record) != _RESOLUTION_KEYS:invalid()
    if type(record['version']) is not int or record['version'] != 1 or record['status'] != 'verified':invalid()
    issuer = record['issuer']
    if not isinstance(issuer, dict) or set(issuer) != _ISSUER_KEYS or not all(isinstance(v,str) for v in issuer.values()):invalid()
    if not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}', issuer['symbol']) or not re.fullmatch(r'[0-9]{10}', issuer['cik']) or int(issuer['cik']) == 0:invalid()
    if not _valid_legal_name(issuer['legal_name']):invalid()
    if record['family'] != 'earnings' or not isinstance(record['period'], str) or not re.fullmatch(r'[0-9]{4}-(?:Q[1-4]|FY)', record['period']):invalid()
    if record['event_id'] != _event_id(issuer['cik'], record['period']):invalid()
    if record['reason'] not in ('current_report_cover','explicit_binding'):invalid()
    refs = record['support_refs']
    if not isinstance(refs, list) or not 1 <= len(refs) <= 128 or any(not isinstance(s,str) or not re.fullmatch(_CAPTURE + r'#[A-Za-z0-9:_.-]{1,180}', s) for s in refs):invalid()
    if len(set(refs)) != len(refs) or issuer['support_ref'] not in refs:invalid()
    docs = record['documents']
    if not isinstance(docs, list) or not 1 <= len(docs) <= 128:invalid()
    parsed = []
    for document in docs:
        if not isinstance(document, dict) or set(document) != _DOCUMENT_KEYS or not all(isinstance(v,str) for v in document.values()):invalid()
        if not _public_url(document['url']) or not _public_url(document['returned_url']):invalid()
        loc = _locator(document['url'])
        if loc is not None:
            if document['document_id'] != loc[1] or loc[0] != issuer['cik'] or _locator(document['returned_url']) != loc:invalid()
        elif _sec_archive(document['url']) or document['document_id'] != 'url:' + document['url']:invalid()
        if not re.fullmatch(r'[0-9a-f]{64}', document['content_sha256']) or not re.fullmatch(_CAPTURE, document['retained_ref']):invalid()
        if not _valid_publication(document['publication_value'], document['precision']):invalid()
        parsed.append(DocumentObservation(**document))
    if len(set(parsed)) != len(parsed):invalid()
    if any(ref.split('#',1)[0] not in {d.retained_ref for d in parsed} for ref in refs):invalid()
    return EventResolution('verified', record['event_id'], IssuerBinding(**issuer), 'earnings', record['period'], tuple(parsed), tuple(refs), record['reason'])


def candidate_identity(resolution: EventResolution) -> dict:
    """Copy trusted lineage to JSON. Caller must never use model dictionaries here."""
    if not isinstance(resolution, EventResolution):raise ValueError('trusted_resolution_required')
    result = {'version':1, **asdict(resolution)}
    result['documents'] = list(result['documents'])
    result['support_refs'] = list(result['support_refs'])
    if resolution.status == 'verified':_load_binding(result)
    elif (resolution.status not in ('unknown','conflict') or resolution.documents or resolution.support_refs
          or any(v is not None for v in (resolution.event_id, resolution.issuer, resolution.family, resolution.period))):
        raise ValueError('invalid_unresolved_identity')
    return result


def _document(page, document_id):
    value = page.get('published_at', '')
    precision = page.get('publication_precision', '')
    if not _valid_publication(value, precision):raise ValueError('invalid_publication_observation')
    if 'publication_observation' in page:
        from publication_observation import validate_observation
        observation = page['publication_observation']
        if not validate_observation(page, observation):raise ValueError('invalid_publication_observation')
        value = page.get('published_at')
        expected_precision = 'day' if observation['precision'] == 'day' else 'second'
        if page.get('publication_precision') != expected_precision:raise ValueError('invalid_publication_observation')
        if value != observation['value']:
            # Preserve the existing receipt's aware same-civil-day compatibility.
            try:
                stamp = dt.datetime.fromisoformat(str(value).replace('Z','+00:00'))
                compatible = (observation['precision'] == 'day' and stamp.utcoffset() is not None
                              and stamp.date().isoformat() == observation['value'])
            except ValueError:compatible = False
            if not compatible:raise ValueError('invalid_publication_observation')
    return DocumentObservation(document_id, page['url'], page.get('returned_url', page['url']),
        page['_retained_article']['projection_sha256'], value, precision, _capture_ref(page))


def _binding_agreement(bindings):
    """Typed invalid state when same-identity reviewed records disagree."""
    issuers = {(r.issuer.symbol, r.issuer.cik, r.issuer.legal_name) for r in bindings}
    if len(issuers) > 1:raise ValueError('conflicting_known_bindings')
    periods = {r.period for r in bindings}
    if len(periods) > 1:raise ValueError('conflicting_known_bindings')


def _merged_binding(bindings, document):
    """Order-independent merge of agreeable reviewed bindings (provenance only)."""
    _binding_agreement(bindings)
    documents = tuple(sorted({d for r in bindings for d in r.documents}
                             | ({document} if document is not None else set()),
                             key=lambda d:(d.document_id, d.retained_ref)))
    refs = tuple(sorted({s for r in bindings for s in r.support_refs}))
    # Agreed issuer fields; support_ref is provenance, chosen deterministically.
    anchor = min(bindings, key=lambda r:r.issuer.support_ref)
    return EventResolution('verified', anchor.event_id, anchor.issuer,
                           anchor.family, anchor.period, documents, refs,
                           'explicit_binding')


def resolve_event(symbol: str, pages: list[dict], *, known_resolutions: tuple[dict, ...]) -> EventResolution:
    """Resolve only retained primary evidence. Index bindings are a trusted input."""
    def unresolved(status, reason):return EventResolution(status, None, None, None, None, (), (), reason)
    if not isinstance(known_resolutions, tuple):raise ValueError('invalid_known_resolutions')
    known = tuple(_load_binding(record) for record in known_resolutions)
    if not isinstance(symbol, str) or not re.fullmatch(r'[A-Z][A-Z0-9.-]{0,9}', symbol):return unresolved('unknown', 'invalid_symbol')
    if not isinstance(pages, list):return unresolved('unknown', 'invalid_pages')
    resolutions = []
    unresolved_primary = False
    for page in pages:
        if not isinstance(page, dict) or not _public_url(page.get('url')):continue
        locator = _locator(page['url'])
        if _sec_archive(page['url']) and locator is None:
            unresolved_primary = True
            continue
        registered = any(r.issuer.symbol == symbol and any(d.url == page['url'] for d in r.documents) for r in known)
        primary = locator is not None or registered
        raw = original_text(page)
        if raw is None or not observation_provenance(page):
            unresolved_primary |= primary
            continue
        if not _public_url(page.get('returned_url',page['url'])):
            unresolved_primary |= primary
            continue
        if locator is not None and _locator(page.get('returned_url', page['url'])) != locator:
            return unresolved('conflict', 'returned_locator_mismatch')
        document_id = locator[1] if locator else 'url:' + page['url']
        try:document = _document(page, document_id)
        except ValueError:return unresolved('unknown', 'invalid_publication_observation')
        bindings = [r for r in known if r.issuer.symbol == symbol and any(
            (d.document_id == document_id if locator else d.url == document.url and d.returned_url == document.returned_url and d.retained_ref == document.retained_ref)
            for d in r.documents)]
        if len({r.event_id for r in bindings}) > 1:return unresolved('conflict', 'alias_collision')
        if bindings:
            signature = lambda r:(r.event_id, r.period, r.issuer.symbol, r.issuer.cik, r.issuer.legal_name)
            if any(signature(r) != signature(bindings[0]) for r in bindings):
                return unresolved('conflict', 'conflicting_known_bindings')
            expected_legal = bindings[0].issuer.legal_name
        else:
            expected_legal = None
        try:
            status, matches = _cover(raw, symbol, locator[0], expected_legal) if locator else ('unknown', [])
        except ValueError:
            return unresolved('conflict', 'conflicting_known_bindings')
        if status == 'issuer_conflict':return unresolved('conflict', 'issuer_conflict')
        if status == 'conflict':
            exact = [r for r in bindings if any(d.document_id == document_id and d.retained_ref == document.retained_ref for d in r.documents)]
            if not exact:return unresolved('conflict', 'primary_support_conflict')
            bindings = exact
        if status == 'verified':
            legal, period, context = matches[0]
            cik = locator[0]
            if bindings and (bindings[0].event_id != _event_id(cik, period) or bindings[0].issuer.legal_name != legal):
                return unresolved('conflict', 'known_binding_disagrees')
            issuer = IssuerBinding(symbol, cik, legal, document.retained_ref + '#dei:' + context)
            resolutions.append(EventResolution('verified', _event_id(cik, period), issuer, 'earnings', period,
                (document,), (issuer.support_ref,), 'current_report_cover'))
        elif bindings and status not in ('incomplete','invalid'):
            resolutions.append(_merged_binding(bindings, document))
        else:unresolved_primary |= primary
    if unresolved_primary:return unresolved('unknown', 'unresolved_primary_evidence')
    if not resolutions:return unresolved('unknown', 'unsupported_or_missing_primary_support')
    if len({r.event_id for r in resolutions}) != 1 or len({r.issuer.legal_name for r in resolutions}) != 1:
        return unresolved('conflict', 'multiple_report_subjects')
    merged = _merged_binding(resolutions, None)
    merged = EventResolution('verified', merged.event_id, merged.issuer, merged.family, merged.period,
                             merged.documents, merged.support_refs,
                             'current_report_cover' if any(r.reason == 'current_report_cover' for r in resolutions) else 'explicit_binding')
    return merged


def _open_root(root):
    """Walk dirfds: neither the root nor an ancestor may be a symlink."""
    path = Path(root).absolute()
    if '..' in path.parts:raise OSError('unsafe_evidence_root')
    fd = os.open('/', os.O_RDONLY | os.O_DIRECTORY)
    try:
        for part in path.parts[1:]:
            child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            os.close(fd)
            fd = child
        if os.fstat(fd).st_uid != os.geteuid():raise OSError('foreign_evidence_root')
        return fd
    except BaseException:
        os.close(fd)
        raise


def _private_child(parent, name):
    try:
        os.mkdir(name, 0o700, dir_fd=parent)
        os.fsync(parent)
    except FileExistsError:pass
    fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
    info = os.fstat(fd)
    if info.st_uid != os.geteuid() or stat.S_IMODE(info.st_mode) != 0o700:
        os.close(fd)
        raise OSError('unsafe_evidence_directory')
    try:os.fsync(parent)
    except BaseException:
        os.close(fd)
        raise
    return fd


def _existing_capture(directory, name, expected, *, max_bytes=MAX_CAPTURE_BYTES):
    try:fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=directory)
    except FileNotFoundError:return False
    try:
        info = os.fstat(fd)
        if (not stat.S_ISREG(info.st_mode) or stat.S_IMODE(info.st_mode) != 0o600
                or info.st_uid != os.geteuid() or info.st_nlink != 1 or info.st_size > max_bytes):
            raise OSError('unsafe_evidence_capture')
        with os.fdopen(fd, 'rb', closefd=False) as handle:data = handle.read(max_bytes + 1)
        if data != expected:raise ValueError('evidence_capture_collision')
        os.fsync(fd)
        return True
    finally:os.close(fd)


def _publish_capture(directory, name, data, *, max_bytes=MAX_CAPTURE_BYTES):
    if len(data)>max_bytes:raise ValueError('capture_capacity')
    if _existing_capture(directory, name, data, max_bytes=max_bytes):
        os.fsync(directory)
        return
    stage = '.capture-' + secrets.token_hex(16)
    fd = os.open(stage, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=directory)
    try:
        with os.fdopen(fd, 'wb', closefd=False) as handle:
            handle.write(data)
            handle.flush()
            os.fsync(fd)
        try:
            # Atomic no-clobber publication; rename/replace would overwrite an incumbent.
            os.link(stage, name, src_dir_fd=directory, dst_dir_fd=directory, follow_symlinks=False)
        except FileExistsError:
            if not _existing_capture(directory, name, data, max_bytes=max_bytes):raise OSError('capture_publication_race')
    finally:
        os.close(fd)
        os.unlink(stage, dir_fd=directory)
    os.fsync(directory)


def retain_observations(root: Path, resolution: EventResolution, pages: list[dict]) -> EventResolution:
    """Explicit durable acquisition step, before publishing any ledger reference.

    All representations referenced by this resolution must be supplied by the
    trusted caller, including historical support when an explicit binding is
    used. Missing historical bytes are never reconstructed from a current page.
    No files or directories are touched until every representation is validated.
    """
    candidate_identity(resolution)
    if resolution.status != 'verified':raise ValueError('verified_resolution_required')
    captures = {}
    for page in pages:
        if observation_provenance(page):
            loc = _locator(page['url'])
            document = _document(page, loc[1] if loc else 'url:' + page['url'])
            captures[document] = _canonical(page['_retained_article'])
    if any(document not in captures for document in resolution.documents):raise ValueError('missing_validated_capture')
    payloads = {Path(document.retained_ref).name:captures[document] for document in resolution.documents}
    if any(len(data) > MAX_CAPTURE_BYTES for data in payloads.values()):raise ValueError('capture_capacity')
    root_fd = _open_root(root)
    private_fd = evidence_fd = None
    try:
        private_fd = _private_child(root_fd, 'private')
        evidence_fd = _private_child(private_fd, 'opportunity_evidence')
        for name, data in sorted(payloads.items()):_publish_capture(evidence_fd, name, data)
    finally:
        for fd in (evidence_fd, private_fd, root_fd):
            if fd is not None:os.close(fd)
    return resolution
