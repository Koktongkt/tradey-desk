"""Synchronized SPY comparator via existing configured Massive HTTPS reads.

SPY is benchmark-only. Adjusted aggregates establish split-adjusted price
return, NOT dividend-inclusive total return. Release verification is separate.
"""
from datetime import date, datetime, timezone
from decimal import Decimal
from urllib.parse import urlencode
from zoneinfo import ZoneInfo
import market_data
from .types import money
from .accounting import _drawdown

ZERO = Decimal(0)


def utc_now():
    return datetime.now(timezone.utc)


def _day(value):
    parsed = date.fromisoformat(value)
    if parsed.isoformat() != value:
        raise ValueError('date_invalid')
    return value


def _rows(payload):
    if (not isinstance(payload, dict) or payload.get('status') not in {'OK', 'DELAYED'}
            or payload.get('next_url') or payload.get('error') or payload.get('has_more')
            or not isinstance(payload.get('results'), list)):
        raise ValueError('benchmark_payload_invalid')
    rows = payload['results']
    for key in ('resultsCount', 'count'):
        if key in payload and (type(payload[key]) is not int or payload[key] != len(rows)):
            raise ValueError('benchmark_count_mismatch')
    return rows


def load_benchmark(start: str, end: str) -> dict:
    """Explicit inclusive session dates; no nearest-session fallback or secrets.

    Two bounded reads reuse market_data._massive_json/configured_massive_key.
    Dividend facts are retained with provenance, but verification of their split
    basis and reinvestment capability is reserved for the release live probe.
    """
    _day(start)
    _day(end)
    if start >= end or (date.fromisoformat(end) - date.fromisoformat(start)).days > 10000:
        raise ValueError('benchmark_interval_invalid')
    result: dict = dict(symbol='SPY', start=start, end=end, observations=[], return_kind='price_return_only',
                  adjustment='split_adjusted', expense_treatment='embedded_in_proxy_price',
                  distributions=dict(status='unverified', observations=[], reasons=['total_return_capability_not_verified']),
                  coverage=dict(status='unknown'), reasons=[])
    market_now = utc_now().astimezone(ZoneInfo('America/New_York'))
    if end > market_now.date().isoformat() or (end == market_now.date().isoformat() and (market_now.hour, market_now.minute) < (16, 15)):
        result['reasons'] = ['benchmark_session_not_completed']
        return result
    try:
        query = urlencode(dict(adjusted='true', sort='asc', limit=50000))
        payload = market_data._massive_json(f'https://api.massive.com/v2/aggs/ticker/SPY/range/1/day/{start}/{end}?{query}')
        if payload.get('adjusted') is not True:
            raise ValueError('benchmark_adjustment_unknown')
        rows, seen = _rows(payload), {}
        if not rows or len(rows) >= 50000:
            raise ValueError('benchmark_prices_missing')
        for bar in rows:
            timestamp = money(bar['t'])
            if timestamp < 0 or timestamp != timestamp.to_integral_value():
                raise ValueError('benchmark_timestamp_invalid')
            instant = datetime.fromtimestamp(int(timestamp // 1000), timezone.utc)
            session = instant.astimezone(ZoneInfo('America/New_York')).date().isoformat()
            value = money(bar['c'])
            if not start <= session <= end or value <= 0 or session in seen:
                raise ValueError('benchmark_price_invalid')
            seen[session] = dict(date=session, value=value, source_timestamp_ms=int(timestamp),
                                 provenance='Massive.v2.aggs.SPY.adjusted_daily_close')
        if start not in seen or end not in seen:
            raise ValueError('benchmark_endpoint_missing')
        result['observations'] = [seen[k] for k in sorted(seen)]
        result['coverage'] = dict(status='complete', price_samples=len(seen))
    except Exception:
        result['reasons'] = ['benchmark_prices_unavailable']
        return result
    try:
        query = urlencode({'ticker': 'SPY', 'ex_dividend_date.gte': start, 'ex_dividend_date.lte': end,
                           'sort': 'ex_dividend_date', 'order': 'asc', 'limit': 1000})
        payload = market_data._massive_json(f'https://api.massive.com/v3/reference/dividends?{query}')
        distributions, ids = [], set()
        for row in _rows(payload):
            day, amount = _day(row['ex_dividend_date']), money(row['cash_amount'])
            if (not start <= day <= end or amount < 0 or row.get('currency') != 'USD'
                    or row.get('ticker') != 'SPY' or not row.get('id') or row['id'] in ids):
                raise ValueError('benchmark_distribution_invalid')
            ids.add(row['id'])
            distributions.append(dict(date=day, amount=amount, distribution_id=row['id'],
                                      provenance='Massive.v3.reference.dividends.cash_amount'))
        result['distributions'].update(observations=distributions, source_coverage='complete_requested_range', start=start, end=end)
    except Exception:
        result['distributions']['reasons'].append('benchmark_distribution_facts_unavailable')
    return result


def _series(observations):
    series = {}
    for row in observations:
        day, value = _day(row['date']), money(row['value'])
        if value <= 0 or not isinstance(row.get('provenance'), str) or not row['provenance'] or day in series:
            raise ValueError('comparison_observation_invalid')
        series[day] = value
    return series


def _total_return_series(prices, distributions, start, end):
    """Explicitly verified split-compatible cash amounts reinvest at ex-date close."""
    if (distributions.get('status') != 'verified' or not distributions.get('provenance')
            or distributions.get('start') != start or distributions.get('end') != end
            or distributions.get('reinvestment') != 'ex_date_close'
            or distributions.get('expense_treatment') != 'embedded_in_proxy_price'):
        return None
    amounts, seen = {}, set()
    try:
        for row in distributions['observations']:
            day, amount = _day(row['date']), money(row['amount'])
            if not row.get('provenance') or day not in prices or day in seen or amount < 0:
                return None
            seen.add(day)
            amounts[day] = amount
        # Opening-date distributions precede starting close and are not earned.
        shares, values = Decimal(1), {}
        for day in sorted(prices):
            if day > start:
                shares *= 1 + amounts.get(day, ZERO) / prices[day]
            values[day] = shares * prices[day]
        return values
    except (KeyError, ValueError, TypeError):
        return None


def compare_benchmark(strategy: dict, benchmark: dict) -> dict:
    """No carried marks, no shadow/research conflation, no alpha confidence claim."""
    result: dict = dict(symbol='SPY', strategy_return=None, benchmark_return=None, benchmark_equity=None,
                       strategy_drawdown=None, benchmark_drawdown=None, excess_total_return=None,
                       excess_price_comparator=None, return_kind='price_return_only', sample_count=0,
                       observations=[], reasons=[], coverage=dict(status='unknown'),
                       inference='descriptive_observations_not_statistically_validated_alpha')
    try:
        if (strategy.get('scope') != 'actual_managed_strategy' or strategy.get('coverage', {}).get('status') != 'complete'
                or benchmark.get('coverage', {}).get('status') != 'complete' or benchmark.get('symbol') != 'SPY'):
            raise ValueError('comparison_coverage_unknown')
        if strategy.get('valuation_basis') != 'completed_session_close' or not strategy.get('valuation_provenance'):
            raise ValueError('valuation_basis_unsynchronized')
        actual, prices = _series(strategy['observations']), _series(benchmark['observations'])
        if not actual:
            raise ValueError('strategy_marks_missing')
        start, end = min(actual), max(actual)
        if (start == end or benchmark.get('start') != start or benchmark.get('end') != end
                or start not in prices or end not in prices):
            raise ValueError('benchmark_endpoint_missing')
        capital = money(strategy['initial_capital'])
        if capital != Decimal(10000) or actual[start] != capital:
            raise ValueError('comparison_capital_mismatch')
        total = _total_return_series(prices, benchmark.get('distributions', {}), start, end)
        values = total if total is not None else prices
        dates = sorted(set(actual) & set(values))
        pairs = [dict(date=day, strategy_equity=actual[day], benchmark_equity=capital * values[day] / values[start]) for day in dates]
        strategy_return = actual[end] / capital - 1
        proxy_return = values[end] / values[start] - 1
        result.update(strategy_return=strategy_return, benchmark_return=proxy_return,
                      benchmark_equity=capital * values[end] / values[start], sample_count=len(dates), observations=pairs,
                      strategy_drawdown=_drawdown([dict(value=actual[d]) for d in dates]),
                      benchmark_drawdown=_drawdown([dict(value=values[d]) for d in dates]),
                      return_kind='total_return' if total is not None else 'price_return_only',
                      coverage=dict(status='complete', missing_strategy_dates=sorted(set(prices)-set(actual)),
                                    missing_benchmark_dates=sorted(set(actual)-set(prices))))
        if total is not None and strategy.get('return_kind') == 'total_return':
            result['excess_total_return'] = strategy_return - proxy_return
        elif total is None:
            result['excess_price_comparator'] = strategy_return - proxy_return
            result['reasons'].append('benchmark_total_return_unverified')
    except (KeyError, ValueError, TypeError) as error:
        reason = str(error)
        allowed = {'comparison_coverage_unknown', 'valuation_basis_unsynchronized', 'strategy_marks_missing', 'benchmark_endpoint_missing',
                   'comparison_capital_mismatch', 'comparison_observation_invalid'}
        result['reasons'] = [reason if reason in allowed else 'comparison_input_invalid']
    return result
