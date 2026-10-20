"""Narrow issuer article-header publication formats; no general date discovery."""
import datetime as dt
import html
from html.parser import HTMLParser
import re
from urllib.parse import unquote, urlparse


CONTRACTS = {
    'ir.tevapharm.com': (r'/news-and-events/press-releases/press-release-details/(\d{4})/([^/]+)/default\.aspx',
                        'evergreen-news-details-item', 'evergreen-news-title',
                        'evergreen-news-date-time', 'evergreen-news-date-text'),
    'investors.vir.bio': (r'/news/news-details/(\d{4})/([^/]+)/default\.aspx',
                          'module-news-details', 'module-details_title',
                          'module_date-time', 'module_date-text'),
}


def _identity(value):
    return re.sub(r'[^a-z0-9]', '', html.unescape(value).lower())


class _ArticleHeader(HTMLParser):
    """Inspect nested, exact publisher module ancestry, not a regex tag walk."""
    def __init__(self, contract):
        super().__init__(convert_charrefs=True)
        self.module_class, self.title_class, self.time_class, self.date_class = contract
        self.stack = []
        self.articles = []

    def handle_starttag(self, tag, attrs):
        classes = set((dict(attrs).get('class') or '').split())
        article = next((f['article'] for f in reversed(self.stack) if f['article'] is not None), None)
        if self.module_class in classes:
            article = {'titles': [], 'dates': []}
            self.articles.append(article)
        date_context = any(self.time_class in f['classes'] for f in self.stack)
        kind = ('title' if self.title_class in classes and tag in ('h2', 'h3') else
                'date' if self.date_class in classes and date_context else None)
        self.stack.append({'tag': tag, 'classes': classes, 'article': article, 'kind': kind, 'text': []})
        if tag in {'area', 'base', 'br', 'col', 'embed', 'hr', 'img', 'input', 'link', 'meta', 'param', 'source', 'track', 'wbr'}:
            self.handle_endtag(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if self.stack and self.stack[-1]['tag'] == tag:
            self.handle_endtag(tag)

    def handle_data(self, data):
        if any(f['tag'] in ('script', 'style', 'aside', 'footer') or
               any(re.search(r'(?:related|recommend|updated|copyright|event)', token, re.I)
                   for token in f['classes']) for f in self.stack):
            return
        for frame in self.stack:
            if frame['kind']:
                frame['text'].append(data)

    def handle_endtag(self, tag):
        index = next((i for i in range(len(self.stack)-1, -1, -1) if self.stack[i]['tag'] == tag), None)
        if index is None:
            return
        for frame in self.stack[index:]:
            article = frame['article']
            if frame['kind'] and article is not None:
                key = 'titles' if frame['kind'] == 'title' else 'dates'
                article[key].append(''.join(frame['text']).strip())
        del self.stack[index:]


def issuer_publication_date(url, body):
    """Known host + article URL/heading identity + exact publication header.

    Numeric month/day values that could instead be day/month are refused. A
    visible clock without timezone is not an authenticated instant: return day
    precision only. Duplicate/conflicting headers are not silently selected.
    """
    parsed = urlparse(url)
    contract = CONTRACTS.get((parsed.hostname or '').lower())
    if contract is None or parsed.scheme != 'https' or parsed.username or parsed.password:
        return None
    path = re.fullmatch(contract[0], unquote(parsed.path))
    if not path:
        return None
    year, slug = path.groups()
    if re.search(r'</?[a-z][^>]*>', body, re.I):
        parser = _ArticleHeader(contract[1:])
        parser.feed(body)
        if len(parser.articles) != 1:
            return None
        article = parser.articles[0]
        if len(article['titles']) != 1 or len(article['dates']) != 1:
            return None
        heading, raw = article['titles'][0], article['dates'][0]
    else:
        # Do not scan past related/update/event headings for a usable date.
        # These exact source header layouts are observed provider Markdown.
        if parsed.hostname == 'ir.tevapharm.com':
            matches = re.findall(r'(?m)^# Press Release Details\s*\n+### ([^\n]+)\n\s*\n([^\n]+)', body)
        else:
            matches = re.findall(r'(?m)^\[View all news\]\(https://investors\.vir\.bio/news/default\.aspx\)\s*\n+## ([^\n]+)\n\s*\n([^\n]+)', body)
        if len(matches) != 1:
            return None
        heading, raw = matches[0]
    if _identity(heading) != _identity(slug):
        return None
    if parsed.hostname == 'ir.tevapharm.com':
        match = re.fullmatch(r'([A-Za-z]{3,9} \d{1,2}, \d{4})(?:\s*(?:1[0-2]|0?[1-9]):[0-5]\d [AP]M)?', raw)
        if not match:
            return None
        raw = match[1]
        formats = ('%B %d, %Y', '%b %d, %Y')
    else:
        match = re.fullmatch(r'(\d{1,2})/(\d{1,2})/(\d{4})', raw)
        if not match or int(match[2]) <= 12:
            return None
        formats = ('%m/%d/%Y',)
    for fmt in formats:
        try:
            date = dt.datetime.strptime(raw, fmt).replace(tzinfo=dt.timezone.utc)
            if date.year != int(year):
                return None
            return date.isoformat().replace('+00:00', 'Z')
        except ValueError:
            pass
    return None
