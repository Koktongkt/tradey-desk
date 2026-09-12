"""Deterministic, token-free earnings-calendar resolution."""
from __future__ import annotations

import datetime as dt
import html
import json
import re
import time
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable, Iterable
from zoneinfo import ZoneInfo

ESTIMATE_BUFFER_DAYS = 14
MIN_QUARTERLY_INTERVAL_DAYS = 45
MAX_QUARTERLY_INTERVAL_DAYS = 150
MAX_RELEVANT_FILINGS_SCANNED = 12
SEC_LOOKUP_BUDGET_SECONDS = 45
SEC_REQUEST_TIMEOUT_SECONDS = 8
TRUSTED_SOURCE_TIMEOUT_SECONDS = 8
NASDAQ_CALENDAR_REQUEST_DELAY_SECONDS = 1.0
SEC_USER_AGENT = "TradeyDesk/1.0 automated-research"
TRUSTED_USER_AGENT = "Mozilla/5.0 (X11; Linux x86_64) automated-research"
DEFAULT_CACHE_PATH = Path(__file__).resolve().parent / "private" / "earnings_cache.json"
MONTH_PATTERN = r"(?:January|February|March|April|May|June|July|August|September|October|November|December)\s+\d{1,2},\s+\d{4}"
SHORT_MONTH_PATTERN = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+\d{1,2},\s+\d{4}"


def extract_release_date(text: str) -> str | None:
    """Extract a date explicitly tied to issuing earnings/results."""
    document = text or ""
    verb = re.search(r"(?is)\b(?:issued|released|announced|reported)\b", document)
    if not verb:
        return None
    has_results = re.search(r"(?is)\b(?:earnings|results)\b", document[verb.start():verb.end() + 300])
    window_start = max(0, verb.start() - 300)
    window_end = verb.end()
    # 8-K cover pages: "Date of earliest event reported): <date>" — the date
    # follows the verb and the Item 2.02 results reference appears later.
    header = re.search(
        rf"(?is)\bdate\s+of\s+(?:report\s+)?\(?(?:date\s+of\s+)?earliest\s+event\s+reported\)?\s*:?\s*(?P<date>{MONTH_PATTERN})",
        document,
    )
    if header:
        return dt.datetime.strptime(header.group("date"), "%B %d, %Y").date().isoformat()
    if not has_results:
        return None
    candidates = list(re.finditer(
        rf"(?is)\b(?:on\s+)?(?P<date>{MONTH_PATTERN})\b", document[window_start:window_end],
    ))
    if not candidates:
        return None
    match = candidates[-1]
    if re.search(r"(?i)\bpreliminary\b", document[match.start():match.start() + 500]):
        return None
    return dt.datetime.strptime(match.group("date"), "%B %d, %Y").date().isoformat()


def _get_text(url: str) -> str:
    request = urllib.request.Request(url, headers={"User-Agent": SEC_USER_AGENT, "Accept": "application/json,text/html"})
    with urllib.request.urlopen(request, timeout=SEC_REQUEST_TIMEOUT_SECONDS) as response:
        return response.read(2_000_000).decode("utf-8", "replace")


def _get_json(url: str) -> Any:
    return json.loads(_get_text(url))


def _plain_text(document: str) -> str:
    return html.unescape(re.sub(r"\s+", " ", re.sub(r"(?s)<[^>]+>", " ", document or ""))).strip()


def sec_release_history(
    symbol: str,
    limit: int = 4,
    *,
    get_json: Callable[[str], Any] = _get_json,
    get_text: Callable[[str], str] = _get_text,
) -> list[dict[str, str]]:
    """Return explicitly dated SEC earnings releases, newest first."""
    deadline = time.monotonic() + SEC_LOOKUP_BUDGET_SECONDS
    normalized = str(symbol or "").upper()
    tickers = get_json("https://www.sec.gov/files/company_tickers.json")
    company = next(
        (row for row in tickers.values() if isinstance(row, dict) and str(row.get("ticker", "")).upper() == normalized),
        None,
    ) if isinstance(tickers, dict) else None
    if not company:
        return []
    cik = int(company["cik_str"])
    submissions = get_json(f"https://data.sec.gov/submissions/CIK{cik:010d}.json")
    recent = submissions.get("filings", {}).get("recent", {}) if isinstance(submissions, dict) else {}
    forms = recent.get("form", [])
    rows: list[dict[str, str]] = []
    seen_dates: set[str] = set()
    scanned = 0
    raw_items = recent.get("items")
    item_values: list[Any] = raw_items if isinstance(raw_items, list) else []
    for index, form in enumerate(forms if isinstance(forms, list) else []):
        if time.monotonic() >= deadline:
            break
        items = str(item_values[index] if index < len(item_values) else "")
        if form in {"8-K", "8-K/A"} and "2.02" not in items:
            continue
        if form not in {"8-K", "8-K/A", "6-K", "10-Q", "10-K"}:
            continue
        if scanned >= MAX_RELEVANT_FILINGS_SCANNED:
            break
        scanned += 1
        try:
            accession = str(recent["accessionNumber"][index])
            primary = str(recent["primaryDocument"][index])
            accession_path = accession.replace("-", "")
            url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{primary}"
            release_date = extract_release_date(_plain_text(get_text(url)))
            if not release_date:
                index_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/index.json"
                index_payload = get_json(index_url)
                files = index_payload.get("directory", {}).get("item", []) if isinstance(index_payload, dict) else []
                likely_names = [
                    str(item.get("name")) for item in files if isinstance(item, dict)
                    and str(item.get("name", "")) != primary
                    and re.search(r"(?i)(?:ex(?:hibit)?[-_]?99|earnings|release)", str(item.get("name", "")))
                ][:6]
                for name in likely_names:
                    if time.monotonic() >= deadline:
                        break
                    exhibit_url = f"https://www.sec.gov/Archives/edgar/data/{cik}/{accession_path}/{name}"
                    release_date = extract_release_date(_plain_text(get_text(exhibit_url)))
                    if release_date:
                        url = exhibit_url
                        break
        except (IndexError, KeyError, TypeError, ValueError, OSError):
            continue
        if not release_date or release_date in seen_dates:
            continue
        seen_dates.add(release_date)
        source_suffix = "_item_2_02" if form in {"8-K", "8-K/A"} else ""
        rows.append({
            "date": release_date,
            "form": str(form),
            "accession": accession,
            "source_url": url,
            "source_type": f"sec_{str(form).lower()}{source_suffix}",
        })
        if len(rows) >= limit:
            break
    return sorted(rows, key=lambda row: row["date"], reverse=True)


def cached_sec_release_history(
    symbol: str,
    *,
    cache_path: Path,
    now: dt.datetime | None = None,
    ttl: dt.timedelta = dt.timedelta(days=1),
    history_loader: Callable[[str], list[dict[str, str]]] = sec_release_history,
) -> list[dict[str, str]]:
    """Cache token-free SEC history and refresh it at most daily."""
    current = now or dt.datetime.now(dt.timezone.utc)
    if current.tzinfo is None:
        raise ValueError("now_must_be_timezone_aware")
    normalized = str(symbol or "").upper()
    cache: dict[str, Any] = {}
    try:
        parsed = json.loads(cache_path.read_text(encoding="utf-8"))
        if isinstance(parsed, dict):
            cache = parsed
    except (OSError, ValueError):
        pass
    entry = cache.get(normalized)
    if isinstance(entry, dict) and isinstance(entry.get("checked_at"), str) and isinstance(entry.get("rows"), list):
        try:
            checked = dt.datetime.fromisoformat(entry["checked_at"].replace("Z", "+00:00"))
            if checked.tzinfo is not None and current - checked <= ttl:
                return [row for row in entry["rows"] if isinstance(row, dict)]
        except ValueError:
            pass
    rows = history_loader(normalized)
    cache[normalized] = {
        "checked_at": current.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z"),
        "rows": rows,
    }
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    temporary = cache_path.with_suffix(cache_path.suffix + ".tmp")
    temporary.write_text(json.dumps(cache, sort_keys=True, separators=(",", ":")), encoding="utf-8")
    temporary.replace(cache_path)
    return rows


def estimate_next_window(release_dates: Iterable[str]) -> dict[str, object] | None:
    """Estimate the next window from the latest two quarterly release dates.

    Only the two most recent releases matter: if they are subsequent quarterly
    reports (45-150 days apart), the next event is estimated from that interval
    alone. Older dates are ignored.
    """
    dates = sorted({dt.date.fromisoformat(value) for value in release_dates}, reverse=True)
    if len(dates) < 2:
        return None
    interval = (dates[0] - dates[1]).days
    if not MIN_QUARTERLY_INTERVAL_DAYS <= interval <= MAX_QUARTERLY_INTERVAL_DAYS:
        return None
    earliest = dates[0] + dt.timedelta(days=max(1, interval - ESTIMATE_BUFFER_DAYS))
    latest_bound = dates[0] + dt.timedelta(days=interval + ESTIMATE_BUFFER_DAYS)
    return {
        "earliest": earliest.isoformat(),
        "latest": latest_bound.isoformat(),
        "history_count": 2,
    }


def stockanalysis_earnings_date(
    symbol: str,
    *,
    get_text: Callable[[str], str] = _get_text,
) -> tuple[str, str] | None:
    """Read the machine-published earningsDate field from StockAnalysis.com."""
    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,6}", normalized):
        return None
    url = f"https://stockanalysis.com/stocks/{normalized.lower()}/"
    try:
        text = get_text(url)
    except OSError:
        return None
    match = re.search(rf'earningsDate"?\s*:\s*"({SHORT_MONTH_PATTERN})"', text)
    if not match:
        return None
    raw = re.sub(r"\s+", " ", match.group(1))
    try:
        event_date = dt.datetime.strptime(raw, "%b %d, %Y").date()
    except ValueError:
        try:
            event_date = dt.datetime.strptime(raw, "%B %d, %Y").date()
        except ValueError:
            return None
    return event_date.isoformat(), url


def nasdaq_earnings_date(
    symbol: str,
    horizon_start: dt.date,
    horizon_end: dt.date,
    *,
    get_json: Callable[[str], Any] = _get_json,
    sleep: Callable[[float], None] = time.sleep,
) -> tuple[str, str] | None:
    """Scan the official Nasdaq earnings calendar across the holding horizon."""
    normalized = str(symbol or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{1,6}", normalized):
        return None
    if horizon_end < horizon_start:
        return None
    day = horizon_start
    while day <= horizon_end:
        if day.weekday() < 5:
            url = f"https://api.nasdaq.com/api/calendar/earnings?date={day.isoformat()}"
            try:
                payload = get_json(url)
            except (OSError, ValueError):
                day += dt.timedelta(days=1)
                continue
            rows = payload.get("data", {}).get("rows") or [] if isinstance(payload, dict) else []
            for row in rows:
                if isinstance(row, dict) and str(row.get("symbol", "")).upper() == normalized:
                    return day.isoformat(), url
            sleep(NASDAQ_CALENDAR_REQUEST_DELAY_SECONDS)
        day += dt.timedelta(days=1)
    return None


def default_trusted_date_loader(
    symbol: str,
    horizon_start: dt.date,
    horizon_end: dt.date,
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> tuple[str, str] | None:
    """Either trusted source confirming the next earnings date is sufficient."""
    from_sa = stockanalysis_earnings_date(symbol)
    if from_sa is not None:
        return from_sa
    try:
        return nasdaq_earnings_date(
            symbol, horizon_start, horizon_end,
            get_json=lambda url: json.loads(_get_text(url)),
        )
    except Exception:
        return None


def resolve_candidate_earnings(
    candidate: dict[str, Any],
    *,
    trusted_date_loader: Callable[[str], tuple[str, str] | None] | None = None,
    history_loader: Callable[[str], list[dict[str, str]]] | None = None,
    cache_path: Path = DEFAULT_CACHE_PATH,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """Replace model-authored event state with deterministic trusted-source state.

    Confirmation comes only from trusted date sources (StockAnalysis /
    Nasdaq). Arbitrary web-evidence prose never confirms a date.
    """
    resolved = dict(candidate)
    for key in (
        "previous_earnings_date", "previous_earnings_dates", "earnings_date_status",
        "earnings_history_count", "estimated_next_earnings_window", "earnings_confirmation_url",
    ):
        resolved.pop(key, None)
    current_at = now or dt.datetime.now(dt.timezone.utc)
    if current_at.tzinfo is None:
        raise ValueError("now_must_be_timezone_aware")
    current = current_at.astimezone(ZoneInfo("America/New_York")).date()
    confirmed = None
    if trusted_date_loader is not None:
        confirmed = trusted_date_loader(str(candidate.get("symbol") or ""))
    history: list[dict[str, str]] = []
    try:
        if history_loader is None:
            history = cached_sec_release_history(
                str(candidate.get("symbol") or ""), cache_path=cache_path, now=now,
                history_loader=sec_release_history,
            )
        else:
            history = history_loader(str(candidate.get("symbol") or ""))
    except Exception:
        history = []
    past_dates_set: set[str] = set()
    for row in history:
        if not isinstance(row, dict) or not isinstance(row.get("date"), str):
            continue
        value = str(row["date"])
        try:
            parsed_date = dt.date.fromisoformat(value)
        except ValueError:
            continue
        if parsed_date < current:
            past_dates_set.add(value)
    if confirmed is not None:
        confirmed_date, confirmation_url = confirmed
        if dt.date.fromisoformat(confirmed_date) >= current:
            resolved["earnings_event_at"] = confirmed_date
            resolved["earnings_confirmation_url"] = confirmation_url
            resolved["earnings_date_status"] = "confirmed"
            resolved.pop("estimated_next_earnings_window", None)
            resolved["earnings_history_count"] = len(past_dates_set)
            if past_dates_set:
                past_dates_all = sorted(past_dates_set, reverse=True)
                resolved["previous_earnings_date"] = past_dates_all[0]
                resolved["previous_earnings_dates"] = past_dates_all[:4]
            return resolved
        past_dates_set.add(confirmed_date)
    past_dates = sorted(past_dates_set, reverse=True)
    if past_dates:
        resolved["previous_earnings_date"] = past_dates[0]
        resolved["previous_earnings_dates"] = past_dates[:4]
    resolved["earnings_history_count"] = len(past_dates)
    window = estimate_next_window(past_dates[:4])
    if window is None or dt.date.fromisoformat(str(window["earliest"])) <= current:
        resolved.pop("earnings_event_at", None)
        resolved["earnings_date_status"] = "unknown"
        return resolved
    resolved["earnings_event_at"] = str(window["earliest"])
    resolved["earnings_date_status"] = "estimated"
    resolved["earnings_history_count"] = int(window["history_count"])
    resolved["estimated_next_earnings_window"] = {
        "earliest": window["earliest"], "latest": window["latest"],
    }
    return resolved
