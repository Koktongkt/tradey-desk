"""Deterministic, coverage-first allocation of already attested focused URLs."""
from dataclasses import dataclass
from urllib.parse import urlsplit

from alpha_radar import publisher_domain, source_profile


@dataclass(frozen=True)
class Allocation:
    by_symbol: dict[str, list[str]]
    unique_urls: list[str]
    batches: list[list[str]]
    available_counts: dict[str, int]
    uncovered: dict[str, str]


def _syntax_valid(url: str) -> bool:
    """Reject malformed identities without rewriting them or resolving hosts."""
    if not isinstance(url, str) or not url or any(ord(c) <= 32 or ord(c) == 127 or c.isspace() for c in url):
        return False
    try:
        parsed = urlsplit(url)
        return (parsed.scheme in {'http', 'https'} and bool(parsed.hostname)
                and parsed.username is None and parsed.password is None
                and parsed.port in {None, 80, 443})
    except ValueError:
        return False


def allocate_urls(candidates: list[dict], alternatives: dict[str, list[str]], *,
                  eligible_urls: set[str], unhealthy_domains: set[str]) -> Allocation:
    """Allocate at most five bindings per symbol across five coverage rounds.

    Only the first five candidate records are considered; duplicate symbols keep
    their first record. The first eligible scout seed stays first, even when its
    publisher is unhealthy. Other slots prefer unused publishers, then healthy
    publishers, then provenance rank, with stable pool order breaking ties.

    Eligibility is supplied by the caller after safety validation/attestation;
    this function performs syntax checks only, never DNS or provider lookups.
    URL identities are not normalized. A shared URL is extracted once but bound
    only to symbols that explicitly supplied it. Empty/scarce pools are normal;
    available_counts reports the full eligible pool before the five-slot cap.
    """
    pools = {}
    seeds = {}
    for candidate in candidates[:5]:
        symbol = candidate['symbol']
        if symbol in pools:
            continue
        scout = [url for url in candidate.get('urls', []) if _syntax_valid(url) and url in eligible_urls]
        focused = [url for url in alternatives.get(symbol, []) if _syntax_valid(url) and url in eligible_urls]
        pools[symbol] = list(dict.fromkeys(scout + focused))
        if scout:
            seeds[symbol] = scout[0]
    selected = {symbol: [] for symbol in pools}
    unique = []
    seen = set()
    for round_index in range(5):
        for symbol, pool in pools.items():
            remaining = [url for url in pool if url not in selected[symbol]]
            if remaining:
                domains = {publisher_domain(url) for url in selected[symbol]}
                url = seeds[symbol] if round_index == 0 and symbol in seeds else min(remaining, key=lambda url: (
                    publisher_domain(url) in domains,
                    publisher_domain(url) in unhealthy_domains,
                    -source_profile(url)['rank'],
                ))
                selected[symbol].append(url)
                if url not in seen:
                    seen.add(url)
                    unique.append(url)
    return Allocation(selected, unique, [unique[i:i + 5] for i in range(0, len(unique), 5)],
                      {symbol: len(pool) for symbol, pool in pools.items()},
                      {symbol: 'no_eligible_url' for symbol, pool in pools.items() if not pool})
