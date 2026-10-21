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
# Time-of-day (optionally meridiem) that may extend a date-only match.
_TOD = re.compile(
    r'[ \t]+(?P<h>\d{1,2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:\.(?P<us>\d{1,6}))?)?'
    r'(?:[ \t]*(?P<ap>[AP])\.?M\.?)?', re.I)
# An explicit numeric offset or Z after a named zone contradicts the name.
_OFFSET_TAIL = re.compile(r'[ \t]*[+-]\d{2}:?\d{2}|[ \t]*Z\b', re.I)
# Recognized zone names/abbreviations with a single worldwide offset. The
# table is deliberately closed: ambiguous abbreviations (CST, IST, BST, AST,
# PST, EST, ...) and bare zone words ('Central Time') are excluded because
# they map to more than one real zone. A zone is never inferred or defaulted;
# without an explicit time plus a listed zone the date stays day-precision.
_TZ_OFFSETS = {
    'eastern daylight time': -4 * 3600, 'eastern standard time': -5 * 3600,
    'central european summer time': 2 * 3600, 'central european time': 3600,
    'mountain daylight time': -6 * 3600, 'mountain standard time': -7 * 3600,
    'atlantic daylight time': -3 * 3600, 'atlantic standard time': -4 * 3600,
    'pacific daylight time': -7 * 3600, 'pacific standard time': -8 * 3600,
    'alaska daylight time': -8 * 3600, 'alaska standard time': -9 * 3600,
    'hawaii aleutian standard time': -10 * 3600, 'hawaii standard time': -10 * 3600,
    'newfoundland daylight time': -(2 * 3600 + 1800),
    'newfoundland standard time': -(3 * 3600 + 1800),
    'coordinated universal time': 0, 'universal coordinated time': 0,
    'greenwich mean time': 0, 'british summer time': 3600,
    'irish standard time': 3600, 'western european time': 0,
    'eastern european summer time': 3 * 3600, 'eastern european time': 2 * 3600,
    'utc': 0, 'gmt': 0, 'edt': -4 * 3600, 'pdt': -7 * 3600, 'mdt': -6 * 3600,
    'akst': -9 * 3600, 'akdt': -8 * 3600, 'hst': -10 * 3600,
    'cet': 3600, 'cest': 2 * 3600, 'eet': 2 * 3600, 'eest': 3 * 3600,
}
_TZ_NAMES_SORTED = sorted(_TZ_OFFSETS.items(), key=lambda kv: -len(kv[0]))
# A date-only ISO value with a trailing zone designator ('2025-09-09Z') states
# the civil day and no time-of-day; the designator never promotes it to an
# instant, so midnight/UTC are still never invented.
_DAY_WITH_ZONE = re.compile(r'(\d{4}-\d{2}-\d{2})Z')
# Generic publication metadata names: any property/name/itemprop that contains
# a publish/date root is a candidate. Unrelated names (e.g. og:updated_time)
# are not, and a non-date content still fails the structured gate below.
_PUBLISH_ROOT = re.compile(r'publish|date\b|pubdate', re.I)
# AP-style place dateline: 'PLACE — DATE' with a digit-free place prefix. The
# date must be followed by another dash or end the line, so period labels
# ('Quarter ended - June 30, 2025, as compared...') are never datelines.
_DATELINE = re.compile(
    r"^[ \t]*[A-Z][A-Za-z .,'’-]{0,48}[.,]?[ \t]*[—–-][ \t]+(?=[A-Z0-9])")
_MAX_CANDIDATE_BUDGET = 8192
_LD_ARTICLE_KEYS = ('@type', 'url', '@id', 'mainEntityOfPage', 'headline',
                    'datePublished')


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


def _zone_at(text, pos):
    """Return (offset_seconds, end) for a recognized zone name at pos, else (None, pos)."""
    rest = text[pos:pos + 48].casefold()
    for name, offset in _TZ_NAMES_SORTED:
        candidate = ' ' + name
        if rest.startswith(candidate):
            after = text[pos + len(candidate):pos + len(candidate) + 1]
            if after and (after.isalnum() or after in '_-'):
                continue
            if not _OFFSET_TAIL.match(text, pos + len(candidate)):
                return offset, pos + len(candidate)
    return None, pos


def _instant_after(text, pos, value):
    """Extend a date-only match with an explicit time-of-day plus a named zone.

    Returns (hour, minute, second, microsecond, tzinfo, end) or (None, pos).
    Midnight/UTC are never invented: without an explicit time-of-day and a
    recognized, unambiguous zone name the date keeps day precision and its
    original span.
    """
    match = _TOD.match(text, pos)
    if match is None:
        # An ISO-shaped value may already carry its own time-of-day.
        clock = re.search(r'(?P<h>\d{1,2}):(?P<mi>\d{2})(?::(?P<s>\d{2})(?:\.(?P<us>\d{1,6}))?)?', value)
        if clock is None:
            return None, pos
        start = pos
    else:
        clock, start = match, match.end()
    offset, end = _zone_at(text, start)
    if offset is None:
        return None, pos
    hour = int(clock.group('h'))
    minute = int(clock.group('mi'))
    second = int(clock.group('s') or 0)
    micro = int((clock.group('us') or '').ljust(6, '0') or 0)
    meridiem = (clock.groupdict().get('ap') or '').lower()
    if meridiem == 'a' and hour == 12:
        hour = 0
    elif meridiem == 'p' and hour != 12:
        hour += 12
    try:
        tzinfo = dt.timezone(dt.timedelta(seconds=offset))
        dt.datetime(2000, 1, 1, hour, minute, second, micro, tzinfo)
    except ValueError:
        return None, pos
    return hour, minute, second, micro, tzinfo, end


def _dates(text):
    """Return retained spelling, parsed date/instant, and span; no inferred year/zone."""
    if not isinstance(text, str):
        return
    for match in _DATE.finditer(html.unescape(text)):
        value = match.group()
        end = match.end()
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
        # A date-only claim keeps day precision unless the retained text
        # itself states an explicit time-of-day plus a recognizable zone;
        # then the whole stated instant (and its span) is retained.
        if isinstance(parsed, dt.date) and not isinstance(parsed, dt.datetime):
            clock = _instant_after(text, end, value)
            if clock[0] is not None:
                hour, minute, second, micro, tzinfo, end = clock
                try:
                    parsed = dt.datetime(parsed.year, parsed.month, parsed.day,
                                         hour, minute, second, micro, tzinfo)
                    value = text[match.start():end]
                except ValueError:
                    end = match.end()
        yield value, parsed, (match.start(), end)


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
        self.witnesses = []
        self.script_tag = ''

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'h1' and not self.hidden:
            self.heading = []
        if tag in ('script', 'style'):
            self.hidden = tag
            self.ld = tag == 'script' and (attrs.get('type') or '').lower() == 'application/ld+json'
            self.script = []
            self.script_tag = self.get_starttag_text() if self.ld else ''
        key = (attrs.get('property') or attrs.get('name') or attrs.get('itemprop'))
        if tag == 'meta' and isinstance(key, str) and _PUBLISH_ROOT.search(key):
            self.metadata.append(attrs.get('content', ''))
            self.witnesses.append(self.get_starttag_text())
        if tag == 'time' and attrs.get('itemprop') == 'datePublished':
            self.metadata.append(attrs.get('datetime', ''))
            self.witnesses.append(self.get_starttag_text())
        if tag in ('h1', 'h2', 'p', 'div', 'br', 'article', 'header', 'time', 'li'):
            self.visible.append('\n')

    def handle_endtag(self, tag):
        if tag == 'h1' and self.heading is not None:
            self.headings.append(''.join(self.heading))
            self.heading = None
        if tag == self.hidden:
            if self.ld:
                self.witnesses.append(self.script_tag + ''.join(self.script) + '</script>')
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
            if isinstance(kinds, list) and any(
                    isinstance(k, str) and ('Article' in k or k in ('BlogPosting', 'Report'))
                    for k in kinds):
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
        if not isinstance(metadata, str):
            continue
        raw_metadata = html.unescape(metadata).strip()
        day_zone = _DAY_WITH_ZONE.fullmatch(raw_metadata)
        if day_zone:
            # A trailing zone designator on a date-only value designates the
            # civil day; retain the date portion, never an instant.
            metadata = day_zone.group(1)
        elif not _DATE.fullmatch(raw_metadata):
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
        # An AP-style place dateline ('PLACE — DATE — body' or 'PLACE — DATE')
        # is a publication header even with trailing prose: the date is
        # bounded by a dash or the end of the line, so a quarter period
        # followed by prose is never a dateline.
        dateline = _DATELINE.match(line)
        if dateline is not None:
            tail = line[dateline.end():]
            dateline_dates = list(_dates(tail))
            first = dateline_dates[0] if dateline_dates else None
            after = tail[first[2][1]:] if first else ''
            if (first is not None and not _UNSAFE_QUOTE.search(line)
                    and not _UPDATE.search(line)
                    and (not after.lstrip() or after.lstrip()[:1] in ('—', '–', '-'))):
                contexts.append(('visible_context',
                                 line[:dateline.end() + first[2][1]], first[1]))
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


def date_candidate_text(text: str, *, budget: int = _MAX_CANDIDATE_BUDGET) -> str:
    """Bounded stitched document of date-candidate contexts from a raw capture.

    Replaces the fixed first-8k header slice: the full capture is scanned
    read-only for date-like signals — JSON-LD datePublished fields (parsed,
    never whole blocks), meta tags whose property/name/itemprop generically
    contains a publish/date root, itemprop=datePublished time tags, and
    AP-style prose place datelines. Each candidate is retained verbatim
    (structured tags) or as the captured dateline prefix; identical candidates
    dedupe; total encoded size is capped at `budget`. The stitched document is
    the canonical interpretation text; the original capture remains the
    binding witness and hash basis and is never mutated. dateModified and
    other modification timestamps are deliberately not candidates: they are
    not publication dates and would create conflicts.
    """
    if not isinstance(text, str) or isinstance(text, bool):
        raise ValueError('text_must_be_str')
    if type(budget) is not int or not 1 <= budget <= _MAX_CANDIDATE_BUDGET:
        raise ValueError('budget must be within 1..8192')
    fragments: list[tuple[int, str]] = []
    ld_pattern = re.compile(
        r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', re.S | re.I)
    for match in ld_pattern.finditer(text):
        try:
            obj = json.loads(match.group(1))
        except (ValueError, RecursionError):
            continue
        for article in _ld_article_dates(obj):
            reduced = {key: article[key] for key in _LD_ARTICLE_KEYS if key in article}
            fragment = ('<script type="application/ld+json">'
                        + json.dumps(reduced, sort_keys=True) + '</script>')
            fragments.append((match.start(), fragment))
    for match in re.finditer(r'<meta\b[^>]*>', text, re.I):
        tag = match.group()
        key_match = re.search(
            r'(?:property|name|itemprop)[ \t]*=[ \t]*"([^"]*)"', tag, re.I)
        if not key_match or not _PUBLISH_ROOT.search(key_match.group(1)):
            continue
        content_match = re.search(r'\bcontent[ \t]*=[ \t]*"([^"]*)"', tag, re.I)
        if not content_match:
            continue
        raw_content = html.unescape(content_match.group(1)).strip()
        day_zone = _DAY_WITH_ZONE.fullmatch(raw_content)
        if day_zone or _DATE.fullmatch(raw_content):
            fragments.append((match.start(), tag))
    for match in re.finditer(r'<time\b[^>]*>', text, re.I):
        tag = match.group()
        if re.search(r'itemprop[ \t]*=[ \t]*"datePublished"', tag, re.I):
            fragments.append((match.start(), tag))
    parser = _RetainedHTML()
    try:
        parser.feed(text)
        parser.close()
    except (ValueError, RecursionError):
        parser.visible = []
    for line in (' '.join(part.split()) for part in ''.join(parser.visible).splitlines()):
        if len(line) > 1000 or _UNSAFE_QUOTE.search(line) or _UPDATE.search(line):
            continue
        dateline = _DATELINE.match(line)
        if dateline is None:
            continue
        tail_rest = line[dateline.end():]
        dates = list(_dates(tail_rest))
        first = dates[0] if dates else None
        after = tail_rest[first[2][1]:] if first else ''
        if (first is not None
                and (not after.lstrip() or after.lstrip()[:1] in ('—', '–', '-'))):
            fragments.append((-1, '<p>' + line[:dateline.end() + first[2][1]] + '</p>'))
    kept: list[str] = []
    used = 0
    seen = set()
    for _, fragment in sorted(fragments, key=lambda item: item[0]):
        if fragment in seen:
            continue
        cost = len(fragment.encode('utf-8')) + (1 if kept else 0)
        if used + cost > budget:
            continue
        seen.add(fragment)
        kept.append(fragment)
        used += cost
    return '\n'.join(kept)


def _ld_article_dates(obj, depth=0):
    """Yield dict objects with an Article-family type and a string datePublished."""
    if depth > 8:
        return
    if isinstance(obj, list):
        for item in obj:
            yield from _ld_article_dates(item, depth + 1)
    elif isinstance(obj, dict):
        kind = obj.get('@type', [])
        kinds = [kind] if isinstance(kind, str) else kind
        if (isinstance(kinds, list) and isinstance(obj.get('datePublished'), str)
                and any(isinstance(k, str) and ('Article' in k or k in ('BlogPosting', 'Report'))
                        for k in kinds)):
            yield obj
        yield from _ld_article_dates(obj.get('@graph'), depth + 1)


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


def prepare_publication_evidence(page: dict, *, extracted_text: str,
                                 max_chars: int = 6000) -> dict:
    """Project captured evidence without losing known conflicts or exact precision.

    The processing bound is independent of transport limits. An invalid marker
    blocks legacy fallback when captured claims cannot be faithfully projected.
    External observation/body fields are never construction authority.
    """
    if type(max_chars) is not int or not 1 <= max_chars <= 6000:
        raise ValueError('max_chars must be within 1..6000')
    result = {k: v for k, v in page.items()
              if k not in ('publication_observation', '_publication_body_text')}
    body = extracted_text[:max_chars]
    result.update(text=body, _publication_body_text=body)
    if not _page_valid(page):
        result['publication_observation'] = None
        return result
    parser = _RetainedHTML()
    parser.feed(page['text'])
    parser.close()
    contexts = _contexts(page)
    titles = {normalize_support(t) for t in [page.get('title'), *parser.headings]
              if isinstance(t, str) and t.strip()}
    applicable = bool(parser.metadata or any(
        _current_article(a, page, titles) for a in parser.articles) or contexts)
    if not applicable:
        # A legacy regex must not promote a foreign Article's exact timestamp.
        # It is present metadata, not proof for this page.
        if parser.articles:result['publication_observation'] = None
        return result
    result['publication_observation'] = None
    # Validate the proposal on ALL original contexts first, never a raw prefix.
    contexts.sort(key=lambda c: isinstance(c[2], dt.datetime), reverse=True)
    for basis, support, parsed in contexts:
        precision = 'instant' if isinstance(parsed, dt.datetime) else 'day'
        value = next((spelling for spelling, date, _ in _dates(support)
                      if _same_claim(parsed, date)), parsed.isoformat()) if precision == 'instant' else parsed.isoformat()
        original = build_observation(page, value=value, precision=precision,
                                     basis=basis, support=support, location='captured publication context')
        if original is None:
            continue
        # Visible lines are retained origin text, not new metadata derived from
        # a parsed date. Keep header proximity and separately labeled contexts.
        visible = ''.join(parser.visible)
        lines = [line for line in visible.splitlines() if line.strip()]
        visible_contexts = [c for b, c, _ in contexts if b == 'visible_context']
        header_indices = [i for i, line in enumerate(lines[:20])
                          if normalize_support(line) in titles or any(
                              normalize_support(c) in normalize_support(line)
                              for c in visible_contexts)]
        header = '\n'.join(lines[:max(header_indices) + 1]) if visible_contexts and header_indices else ''
        extras = [line for line in lines[20:]
                  if any(normalize_support(c) in normalize_support(line)
                         for b, c, _ in contexts if b == 'visible_context')]
        witness = '\n'.join([*parser.witnesses, header, *extras]).strip()
        # Reserve meaningful body; metadata never supplies the body minimum.
        if len(witness) + 1 + min(len(body), 80) > max_chars:
            return result
        retained_body = body[:max_chars - len(witness) - 1]
        projected = {**result, 'text': witness + '\n' + retained_body,
                     '_publication_body_text': retained_body}
        observation = build_observation(projected, value=value, precision=precision,
                                        basis=basis, support=support,
                                        location='retained publication context')
        if observation is not None:
            projected['publication_observation'] = observation
            legacy_day = (page.get('publication_precision') == 'day'
                          and _parse(page.get('published_at'), 'instant') is not None)
            projected['published_at'] = page['published_at'] if legacy_day else value
            projected['publication_precision'] = 'second' if precision == 'instant' else 'day'
            projected['publication_basis'] = basis
            return projected
    return result


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
