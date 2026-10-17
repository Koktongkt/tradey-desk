"""Stdlib-only validation shared by the untrusted extraction boundaries."""
import html
import json
import re


def strict_json_loads(raw):
    """Reject ambiguous objects and JavaScript constants at every nesting level."""
    def pairs(items):
        out = {}
        for key, value in items:
            if key in out:
                raise ValueError('duplicate JSON key')
            out[key] = value
        return out
    def constant(value):
        raise ValueError('nonstandard JSON constant')
    return json.loads(raw, object_pairs_hook=pairs, parse_constant=constant)


def strip_tool_footer(text):
    """Remove public web_extract scaffolding, never read its local spill path."""
    text = re.split(r'(?m)^\s*─{3,}\s*\[TRUNCATED\]', text, maxsplit=1)[0]
    text = re.sub(r'(?m)^\[\.\.\. middle omitted — see footer \.\.\.\]\s*$', '', text)
    return text


def is_error_document(text, title=''):
    """Recognize transport/error documents after HTML and Markdown normalization.

    Match document headings, not incidental reporting about access failures.
    """
    # Preserve explicit headings before flattening: a service title or provider
    # preamble must not conceal the actual error heading.
    decoded = html.unescape(text)
    headings = re.findall(r'(?is)<h[1-6]\b[^>]*>(.*?)</h[1-6]>', decoded[:1500])
    headings += re.findall(r'(?m)^\s*#{1,6}\s+(.+)$', decoded[:1500])
    # HTML head/title/script/style are not article body. Inspect only the
    # leading body after removing them, never every paragraph (which would
    # reject reporting that quotes an error later in the article).
    body = re.sub(r'(?is)<(?:head|script|style|title)\b[^>]*>.*?</(?:head|script|style|title)>', ' ', decoded)
    body = re.sub(r'(?s)<!--.*?-->', ' ', body)
    candidates = [decoded, body, *headings]
    if isinstance(title, str) and title.strip():
        # Direct fetch/cache flatten the head title into the leading text. Remove
        # only that known prefix; later body mentions are never searched.
        normalized_title = re.sub(r'\s+', ' ', html.unescape(title)).strip()
        flattened = re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', ' ', decoded)).strip()
        candidates.append(re.sub(r'^' + re.escape(normalized_title) + r'(?=\s|$)',
                                 '', flattened, count=1, flags=re.I))
    for candidate in candidates:
        normalized = re.sub(r'<[^>]+>', ' ', candidate)
        normalized = re.sub(r'(?m)^\s*[#>*_`~\-]+\s*', '', normalized)
        normalized = re.sub(r'[*_`]', '', normalized)
        normalized = re.sub(r'\s+', ' ', normalized).strip()
        if re.match(
            r'(?i)^(?:error\b|failed to (?:extract|fetch|retrieve)\b|'
            r'content (?:was |is )?(?:inaccessible|unavailable)\b|'
            r'access denied\b|forbidden\b|unauthorized\b|'
            r'(?:401|403|429|500|502|503)\s*(?:error|forbidden|unauthorized|service|too many)\b|'
            r'just a moment\b|please (?:enable javascript|verify you are human)\b)', normalized):
            return True
    return False
