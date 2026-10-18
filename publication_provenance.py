"""Versioned bounded publication reports, never publisher authentication.

v1 supports Keenable integer-second reports only. A report is retained for
provenance/diagnosis; it cannot supply published_at without article evidence.
Unknown domains continue through the existing visible-date evidence paths.
"""
from datetime import datetime, timezone


def provider_publication(epoch: object) -> dict | None:
    """Convert only documented Unix integer seconds to an unverified report."""
    if type(epoch) is not int or not 946684800 <= epoch <= 4102444799:
        return None
    return {'version': 1, 'basis': 'provider_reported', 'provider': 'keenable',
            'field': 'published_at',
            'value': datetime.fromtimestamp(epoch, timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
            'precision': 'second'}


def publication_record(value):
    if not isinstance(value, dict) or set(value) != {'version', 'basis', 'provider', 'field', 'value', 'precision'}:
        return None
    expected = {'basis': 'provider_reported', 'provider': 'keenable', 'field': 'published_at', 'precision': 'second'}
    if type(value['version']) is not int or value['version'] != 1 or any(value[k] != v for k, v in expected.items()):
        return None
    text = value['value']
    if not isinstance(text, str) or len(text) != 20:
        return None
    try:
        instant = datetime.strptime(text, '%Y-%m-%dT%H:%M:%SZ').replace(tzinfo=timezone.utc)
        if not 946684800 <= instant.timestamp() <= 4102444799 or instant.strftime('%Y-%m-%dT%H:%M:%SZ') != text:
            return None
    except (ValueError, OverflowError):
        return None
    return dict(value)


def extraction_extensions(row, returned, requested=None):
    """Return validated extensions, or None on a malformed/conflicting claim."""
    out = {}
    if 'extraction_location' in row:
        loc = row['extraction_location']
        if (not isinstance(loc, dict) or set(loc) != {'version', 'requested_url', 'returned_url'}
                or type(loc['version']) is not int or loc['version'] != 1
                or not all(isinstance(loc[k], str) and 1 <= len(loc[k]) <= 4096 for k in ('requested_url', 'returned_url'))
                or loc['returned_url'] != returned
                or (requested is not None and loc['requested_url'] != requested)):
            return None
        out['extraction_location'] = dict(loc)
    if 'publication' in row:
        publication = publication_record(row['publication'])
        if publication is None or 'extraction_location' not in out:
            return None
        out['publication'] = publication
    return out


def publication_conflicts(report, published, *, day_only=False):
    """A provider report never overrides a contradictory visible date/instant.

    Day-only parser outputs are UTC-midnight conventions, not exact instants.
    Comparison is deliberately conservative across timezone/day boundaries.
    """
    if not report or not published:
        return False
    try:
        visible = datetime.fromisoformat(published.replace('Z', '+00:00'))
        stated = datetime.fromisoformat(report['value'].replace('Z', '+00:00'))
        if visible.tzinfo is None:
            return True
        if day_only:
            return visible.date() != stated.date()
        return visible != stated
    except (ValueError, TypeError):
        return True
