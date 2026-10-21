"""Pure, bounded grounding of publication claims in retained page content.

An observation is internal evidence, not publisher authentication. Trusted ingestion
must own its construction and reject provider-injected observations. No confidence
or location string authorizes a claim. Unsupported/ambiguous contexts fail closed.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
from html.parser import HTMLParser
import json
import re
import unicodedata
from urllib.parse import urldefrag, urljoin, urlsplit

OBSERVATION_VERSION = 1
PARSER_VERSION = 'publication-observation/1'
MAX_CONTENT_CHARS = 100_000
MAX_SUPPORT_CHARS = 2_000
_KEYS = frozenset(('version', 'value', 'precision', 'basis', 'url', 'returned_url',
                   'content_sha256', 'parser_version', 'support', 'location'))
_MONTHS = {name: i for i, names in enumerate((
    ('jan', 'january'), ('feb', 'february'), ('mar', 'march'), ('apr', 'april'),
    ('may',), ('jun', 'june'), ('jul', 'july'), ('aug', 'august'),
    ('sep', 'sept', 'september'), ('oct', 'october'), ('nov', 'november'),
    ('dec', 'december')), 1) for name in names}
_MONTH = '(?:' + '|'.join(sorted(_MONTHS, key=len, reverse=True)) + ')'
_DATE = re.compile(
    r'(?<!\w)(?:\d{4}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2}(?:\.\d{1,6})?)?(?:Z|[+-]\d{2}:\d{2})?)?'
    + rf'|{_MONTH}\.?\s+\d{{1,2}}(?:st|nd|rd|th)?,?\s+\d{{4}}'
    + rf'|\d{{1,2}}(?:st|nd|rd|th)?\s+{_MONTH}\.?[,]?\s+\d{{4}})(?!\w)', re.I)
_ROLE = re.compile(r'^(?:published(?:\s+on)?|publication date|released(?:\s+on)?|issued(?:\s+on)?|posted(?:\s+on)?)\s*[:|\-–—]?\s*', re.I)
_UNSAFE_QUOTE = re.compile(r'\b(?:copyright|crawled?|retrieved|accessed|event|meeting|conference|webcast|ignore|instructions?|system|assistant|prompt|override)\b|©', re.I)
_UPDATE = re.compile(r'\b(?:updated?|modified)\b', re.I)


def normalize_support(text: str) -> str:
    """Unescape and normalize citation typography, without semantic rewriting."""
    text = unicodedata.normalize('NFKC', html.unescape(text)).casefold()
    return ' '.join(''.join(' ' if unicodedata.category(c)[0] in 'PZ' else c
                            for c in text).split())


def _url(value):
    if not isinstance(value, str) or not value or len(value) > 8192:
        return False
    try:
        parsed = urlsplit(value)
        return parsed.scheme in ('http', 'https') and bool(parsed.netloc)
    except ValueError:
        return False


def _page_valid(page):
    valid = (isinstance(page, dict) and isinstance(page.get('text'), str)
            and 0 < len(page['text']) <= MAX_CONTENT_CHARS
            and _url(page.get('url'))
            and _url(page.get('returned_url', page.get('url'))))
    if not valid:
        return False
    try:
        page['text'].encode('utf-8')
    except UnicodeEncodeError:
        return False
    return True


def _hash(page):
    return hashlib.sha256(page['text'].encode('utf-8')).hexdigest()


def _parse(value, precision):
    if not isinstance(value, str) or len(value) > 64:
        return None
    try:
        if precision == 'day' and re.fullmatch(r'\d{4}-\d{2}-\d{2}', value):
            return dt.date.fromisoformat(value)
        if precision == 'instant':
            parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
            if parsed.tzinfo is not None:
                return parsed
    except ValueError:
        pass
    return None


def _dates(text):
    """Return retained spelling, parsed date/instant, and span; no inferred year/zone."""
    if not isinstance(text, str):
        return
    for match in _DATE.finditer(html.unescape(text)):
        value = match.group()
        parsed = _parse(value, 'instant') or _parse(value[:10], 'day')
        if parsed is None:
            words = re.sub(r'(\d)(?:st|nd|rd|th)\b', r'\1', value.lower())
            words = re.sub(r'[.,]', '', words).split()
            try:
                if words[0] in _MONTHS:
                    month, day, year = _MONTHS[words[0]], int(words[1]), int(words[2])
                else:
                    day, month, year = int(words[0]), _MONTHS[words[1]], int(words[2])
                parsed = dt.date(year, month, day)
            except (ValueError, KeyError, IndexError):
                continue
        yield value, parsed, match.span()


class _RetainedHTML(HTMLParser):
    """Extract semantic metadata and visible block boundaries, not CSS conventions."""
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.visible = []
        self.metadata = []
        self.articles = []
        self.hidden = None
        self.script = []
        self.ld = False
        self.headings = []
        self.heading = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h1' and not self.hidden:
            self.heading = []
        if tag in ('script', 'style'):
            self.hidden = tag
            self.ld = tag == 'script' and (attrs.get('type') or '').lower() == 'application/ld+json'
            self.script = []
        if tag == 'meta' and (attrs.get('property') or attrs.get('name') or attrs.get('itemprop')) in ('article:published_time', 'datePublished'):
            self.metadata.append(attrs.get('content', ''))
        if tag == 'time' and attrs.get('itemprop') == 'datePublished':
            self.metadata.append(attrs.get('datetime', ''))
        if tag in ('h1', 'h2', 'p', 'div', 'br', 'article', 'header', 'time', 'li'):
            self.visible.append('\n')

    def handle_endtag(self, tag):
        if tag == 'h1' and self.heading is not None:
            self.headings.append(''.join(self.heading))
            self.heading = None
        if tag == self.hidden:
            if self.ld:
                try:
                    obj = json.loads(''.join(self.script))
                    self._article_dates(obj)
                except (ValueError, RecursionError):
                    pass
            self.hidden = None
            self.ld = False
        if tag in ('h1', 'h2', 'p', 'div', 'article', 'header', 'time', 'li'):
            self.visible.append('\n')

    def handle_data(self, data):
        if self.hidden:
            if self.ld:
                self.script.append(data)
        else:
            self.visible.append(data)
            if self.heading is not None:
                self.heading.append(data)

    def _article_dates(self, obj, depth=0):
        if depth > 8:
            return
        if isinstance(obj, list):
            for item in obj:
                self._article_dates(item, depth + 1)
        elif isinstance(obj, dict):
            kind = obj.get('@type', [])
            kinds = [kind] if isinstance(kind, str) else kind
            if isinstance(kinds, list) and any(k in ('Article', 'NewsArticle', 'BlogPosting', 'Report') for k in kinds):
                if isinstance(obj.get('datePublished'), str):
                    self.articles.append(obj)
            self._article_dates(obj.get('@graph'), depth + 1)


def _current_article(article, page, titles):
    """Exclude explicit foreign identities, not anonymous metadata.

    This only disambiguates retained evidence; it does not authenticate origin.
    URL identity is stronger than headline spelling (which can vary on-page).
    """
    base = page.get('returned_url', page['url'])
    current = {urldefrag(page['url'])[0], urldefrag(base)[0]}
    identities = []
    for key in ('url', '@id', 'mainEntityOfPage'):
        value = article.get(key)
        if isinstance(value, dict):
            value = value.get('@id', value.get('url'))
        if isinstance(value, str) and value.strip():
            try:
                resolved = urljoin(base, value)
                if _url(resolved):
                    identities.append(urldefrag(resolved)[0])
            except ValueError:
                return False
    if identities:
        return all(identity in current for identity in identities)
    headline = article.get('headline')
    return (not isinstance(headline, str) or not headline.strip() or not titles
            or normalize_support(headline) in titles)


def _contexts(page):
    parser = _RetainedHTML()
    try:
        parser.feed(page['text'])
        parser.close()
    except (ValueError, RecursionError):
        return []
    contexts = []
    titles = {normalize_support(title) for title in [page.get('title'), *parser.headings]
              if isinstance(title, str) and title.strip()}
    metadata_values = parser.metadata + [article['datePublished'] for article in parser.articles
                                         if _current_article(article, page, titles)]
    for metadata in metadata_values:
        if not isinstance(metadata, str) or not _DATE.fullmatch(html.unescape(metadata).strip()):
            continue
        for _, parsed, _ in _dates(metadata):
            contexts.append(('structured_metadata', metadata, parsed))
    lines = [' '.join(line.split()) for line in ''.join(parser.visible).splitlines() if line.strip()]
    title = normalize_support(page.get('title', '')) if isinstance(page.get('title'), str) else ''
    if parser.headings:
        title = normalize_support(parser.headings[0])
    heading = next((i for i, line in enumerate(lines[:20])
                    if title and title in normalize_support(line)), None)
    for i, line in enumerate(lines):
        if len(line) > 1000:
            continue
        # A separate update is not a publication conflict. Never use its date.
        for segment in re.split(r'\s*[|;]\s*|(?=\b(?:updated?|modified)\b)', line, flags=re.I):
            if _UNSAFE_QUOTE.search(segment) or _UPDATE.search(segment):
                continue
            dates = list(_dates(segment))
            if not dates:
                continue
            residual = html.unescape(segment)
            for _, _, (start, end) in reversed(dates):
                residual = residual[:start] + ' ' + residual[end:]
            explicit = bool(_ROLE.match(residual))
            residual = _ROLE.sub('', residual)
            if title:
                residual_normal = normalize_support(residual).replace(title, '', 1).strip()
            else:
                residual_normal = normalize_support(residual)
            # Date-adjacent article header: a date-only row, optional byline,
            # or title plus date. Prose containing an event date is not a header.
            header = heading is not None and abs(i - heading) <= 3
            # A byline keeps "By [author]" together on one side of the date.
            # Removing the date first mistakes "By [date] ..." for an author.
            start, end = dates[0][2]
            unescaped = html.unescape(segment)
            prefix = normalize_support(_ROLE.sub('', unescaped[:start]))
            suffix = normalize_support(unescaped[end:])
            author = r'by\s+[^\W\d_]+(?:\s+[^\W\d_]+)*'
            byline = (len(dates) == 1
                      and ((bool(re.fullmatch(author, prefix, re.I)) and not suffix)
                           or (not prefix and bool(re.fullmatch(author, suffix, re.I)))))
            if (explicit or header) and (not residual_normal or byline):
                for _, parsed, _ in dates:
                    contexts.append(('visible_context', segment, parsed))
    return contexts


def _same_claim(parsed, candidate):
    if isinstance(parsed, dt.datetime):
        return isinstance(candidate, dt.datetime) and parsed == candidate
    return not isinstance(candidate, dt.datetime) and parsed == candidate


def build_observation(page: dict, *, value: str, precision: str, basis: str,
                      support: str, location: str) -> dict | None:
    """Construct only after local binding, citation and publication-role checks."""
    if not _page_valid(page):
        return None
    observation = dict(version=OBSERVATION_VERSION, value=value, precision=precision,
                       basis=basis, url=page['url'],
                       returned_url=page.get('returned_url', page['url']),
                       content_sha256=_hash(page), parser_version=PARSER_VERSION,
                       support=support, location=location)
    return observation if validate_observation(page, observation) else None


def validate_observation(page: dict, observation: object) -> bool:
    """Check schema AND retained publication evidence; not origin authenticity."""
    if not _page_valid(page) or not isinstance(observation, dict) or set(observation) != _KEYS:
        return False
    o = observation
    if (type(o['version']) is not int or o['version'] != OBSERVATION_VERSION
            or o['parser_version'] != PARSER_VERSION
            or o['basis'] not in ('structured_metadata', 'visible_context', 'llm_grounded')
            or o['precision'] not in ('day', 'instant')
            or o['url'] != page['url']
            or o['returned_url'] != page.get('returned_url', page['url'])
            or o['content_sha256'] != _hash(page)):
        return False
    for key, limit in (('support', MAX_SUPPORT_CHARS), ('location', 200)):
        if not isinstance(o[key], str) or not 0 < len(o[key].strip()) <= limit:
            return False
    parsed = _parse(o['value'], o['precision'])
    support = normalize_support(o['support'])
    if parsed is None or not support or _UNSAFE_QUOTE.search(o['support']):
        return False
    contexts = _contexts(page)
    # All retained publication roles participate in conflict detection, regardless
    # of which quote/basis was selected. Updates/events never become candidates.
    days = {candidate for _, _, candidate in contexts if not isinstance(candidate, dt.datetime)}
    instants = {candidate for _, _, candidate in contexts if isinstance(candidate, dt.datetime)}
    if len(days) > 1 or len(instants) > 1:
        return False
    civil_days = {candidate.date() for _, _, candidate in contexts if isinstance(candidate, dt.datetime)}
    if instants and days and not days <= civil_days:
        return False
    # Retained exact evidence governs precision, even if a caller selects a
    # separate day-only quote. Do not weaken strict duration freshness cutoffs.
    if instants and o['precision'] != 'instant':
        return False
    for basis, context, candidate in contexts:
        if o['basis'] not in (basis, 'llm_grounded') or not _same_claim(parsed, candidate):
            continue
        normalized = normalize_support(context)
        if support not in normalized and normalized not in support:
            continue
        # Quote must actually contain the supported date, not merely the heading.
        if (support in normalize_support(page['text'])
                and any(_same_claim(parsed, date) for _, date, _ in _dates(o['support']))):
            return True
    return False


def evaluate_publication(page: dict, *, now: dt.datetime,
                         max_age_days: int = 180) -> tuple[bool, str | None]:
    """Use UTC calendar days for grounded days; preserve legacy instant cutoffs.

    now must be timezone-aware; max_age_days must be a nonnegative integer.
    Invalid caller policy raises ValueError; invalid source claims return unknown.
    """
    if not isinstance(now, dt.datetime) or now.tzinfo is None or now.utcoffset() is None:
        raise ValueError('now must be timezone-aware')
    if type(max_age_days) is not int or max_age_days < 0:
        raise ValueError('max_age_days must be a nonnegative integer')
    if not isinstance(page, dict):
        return False, 'source_freshness_unknown'
    if 'publication_observation' in page:
        observation = page['publication_observation']
        if not validate_observation(page, observation):
            return False, 'source_freshness_unknown'
        precision, value = observation['precision'], observation['value']
    else:
        precision, value = 'instant', page.get('published_at')
    parsed = _parse(value, precision)
    if parsed is None:
        return False, 'source_freshness_unknown'
    if isinstance(parsed, dt.datetime):
        if parsed - now > dt.timedelta(days=1):
            return False, 'source_freshness_unknown'
        if now - parsed > dt.timedelta(days=max_age_days):
            return False, 'stale_source'
    else:
        age = (now.astimezone(dt.timezone.utc).date() - parsed).days
        if age < -1:
            return False, 'source_freshness_unknown'
        if age > max_age_days:
            return False, 'stale_source'
    return True, None
