import unittest
from decimal import Decimal as D
from unittest.mock import patch
from watchdog import benchmark


class BenchmarkTests(unittest.TestCase):
    def setUp(self):
        from datetime import datetime, timezone
        clock = patch('watchdog.benchmark.utc_now', return_value=datetime(2026, 10, 8, 22, 0, tzinfo=timezone.utc))
        clock.start()
        self.addCleanup(clock.stop)

    def test_real_loader_uses_existing_massive_helper_price_only(self):
        self.assertIsNotNone(benchmark, 'benchmark module not implemented')
        payload = dict(status='OK', adjusted=True, resultsCount=2, results=[dict(t=1790884800000, c='100'), dict(t=1791316800000, c='102')])
        with patch('market_data._massive_json', return_value=payload) as read:
            result = benchmark.load_benchmark('2026-10-01', '2026-10-06')
        self.assertIn('/ticker/SPY/range/1/day/2026-10-01/2026-10-06', read.call_args_list[0].args[0])
        self.assertIn('adjusted=true', read.call_args_list[0].args[0])
        self.assertEqual(result['return_kind'], 'price_return_only')
        self.assertEqual(result['observations'][0]['value'], D(100))
        self.assertEqual(result['coverage']['status'], 'complete')
        self.assertEqual(result['distributions']['status'], 'unverified')

    def test_loader_rejects_stale_dates_pagination_and_bad_prices(self):
        for payload in [dict(status='OK', adjusted=True, results=[dict(t=1790884800000, c='100')]),
                        dict(status='OK', adjusted=True, next_url='https://evil.invalid', results=[]),
                        dict(status='OK', adjusted=False, results=[]),
                        dict(status='OK', adjusted=True, results=[dict(t=1790884800000, c='NaN')])]:
            with self.subTest(payload=payload), patch('market_data._massive_json', return_value=payload):
                result = benchmark.load_benchmark('2026-10-01', '2026-10-06')
            self.assertEqual(result['coverage']['status'], 'unknown')
            self.assertEqual(result['observations'], [])

    def test_loader_network_failure_is_sanitized_and_bad_range_never_reads(self):
        with patch('market_data._massive_json', side_effect=RuntimeError('secret')):
            result = benchmark.load_benchmark('2026-10-01', '2026-10-06')
        self.assertNotIn('secret', str(result))
        self.assertEqual(result['coverage']['status'], 'unknown')
        with patch('market_data._massive_json') as read:
            with self.assertRaises(ValueError):
                benchmark.load_benchmark('2026-10-06', '2026-10-01')
            read.assert_not_called()

    def test_loader_reads_distribution_facts_but_does_not_invent_capability(self):
        prices = dict(status='OK', adjusted=True, results=[dict(t=1790884800000, c='100'), dict(t=1791316800000, c='102')])
        dividends = dict(status='OK', results=[dict(id='dist', ex_dividend_date='2026-10-06', cash_amount='1', currency='USD', ticker='SPY')])
        with patch('market_data._massive_json', side_effect=[prices, dividends]) as read:
            result = benchmark.load_benchmark('2026-10-01', '2026-10-06')
        self.assertIn('/v3/reference/dividends?', read.call_args_list[1].args[0])
        self.assertEqual(result['distributions']['observations'][0]['amount'], D(1))
        self.assertEqual(result['return_kind'], 'price_return_only')
        self.assertEqual(result['distributions']['status'], 'unverified')

    def comparison_fixture(self):
        strategy = dict(scope='actual_managed_strategy', valuation_basis='completed_session_close', valuation_provenance='verified_synchronized_session_marks', initial_capital=D(10000), return_kind='total_return', coverage=dict(status='complete'),
                        observations=[dict(date='2026-10-01', value=D(10000), provenance='valid_close'), dict(date='2026-10-02', value=D(9900), provenance='valid_close'), dict(date='2026-10-06', value=D(10015), provenance='valid_close')])
        proxy = dict(symbol='SPY', start='2026-10-01', end='2026-10-06', return_kind='price_return_only', coverage=dict(status='complete'), distributions=dict(status='unverified'),
                     observations=[dict(date='2026-10-01', value=D(100), provenance='Massive'), dict(date='2026-10-02', value=D(99), provenance='Massive'), dict(date='2026-10-06', value=D(102), provenance='Massive')])
        return strategy, proxy

    def test_synchronized_price_comparison_withholds_total_excess(self):
        self.assertTrue(callable(getattr(benchmark, 'compare_benchmark', None)), 'comparison missing')
        strategy, proxy = self.comparison_fixture()
        result = benchmark.compare_benchmark(strategy, proxy)
        self.assertEqual(result['strategy_return'], D('.0015'))
        self.assertEqual(result['benchmark_return'], D('.02'))
        self.assertEqual(result['benchmark_equity'], D(10200))
        self.assertEqual(result['strategy_drawdown'], D('-.01'))
        self.assertEqual(result['excess_price_comparator'], D('-.0185'))
        self.assertIsNone(result['excess_total_return'])
        self.assertEqual(result['sample_count'], 3)
        self.assertEqual(result['inference'], 'descriptive_observations_not_statistically_validated_alpha')

    def test_date_gaps_and_stale_endpoint_are_not_interpolated(self):
        self.assertTrue(callable(getattr(benchmark, 'compare_benchmark', None)), 'comparison missing')
        strategy, proxy = self.comparison_fixture()
        strategy['observations'].pop(1)
        result = benchmark.compare_benchmark(strategy, proxy)
        self.assertEqual(result['sample_count'], 2)
        self.assertEqual(result['strategy_drawdown'], D(0))
        self.assertEqual(result['coverage']['missing_strategy_dates'], ['2026-10-02'])
        proxy['observations'].pop()
        result = benchmark.compare_benchmark(strategy, proxy)
        self.assertIsNone(result['benchmark_return'])
        self.assertIn('benchmark_endpoint_missing', result['reasons'])

    def test_verified_distribution_reinvestment_enables_total_excess(self):
        self.assertTrue(callable(getattr(benchmark, 'compare_benchmark', None)), 'comparison missing')
        strategy, proxy = self.comparison_fixture()
        proxy['distributions'] = dict(status='verified', provenance='release_verified_split_price_basis_and_distribution_capability', start=proxy['start'], end=proxy['end'], reinvestment='ex_date_close', expense_treatment='embedded_in_proxy_price', observations=[dict(date='2026-10-06', amount=D(1), provenance='issuer_verified_split_adjusted_distribution')])
        result = benchmark.compare_benchmark(strategy, proxy)
        self.assertEqual(result['benchmark_return'], D('.03'))
        self.assertEqual(result['excess_total_return'], D('-.0285'))
        self.assertEqual(result['return_kind'], 'total_return')
        proxy['distributions'].pop('provenance')
        result = benchmark.compare_benchmark(strategy, proxy)
        self.assertIsNone(result['excess_total_return'])
        self.assertEqual(result['return_kind'], 'price_return_only')

    def test_research_shadow_unknown_and_conflicting_dates_do_not_compare(self):
        self.assertTrue(callable(getattr(benchmark, 'compare_benchmark', None)), 'comparison missing')
        for kind in ('research', 'shadow', 'unknown', 'conflict'):
            strategy, proxy = self.comparison_fixture()
            if kind in {'research', 'shadow'}:
                strategy['scope'] = kind
            elif kind == 'unknown':
                strategy['coverage']['status'] = 'unknown'
            else:
                strategy['observations'].append(dict(date='2026-10-01', value=D(10001), provenance='conflicting'))
            result = benchmark.compare_benchmark(strategy, proxy)
            self.assertIsNone(result['strategy_return'])
            self.assertIsNone(result['excess_total_return'])

    def test_intraday_broker_marks_are_not_completed_close_comparison(self):
        strategy, proxy = self.comparison_fixture()
        strategy['valuation_basis'] = 'broker_snapshot'
        result = benchmark.compare_benchmark(strategy, proxy)
        self.assertIsNone(result['benchmark_return'])
        self.assertIn('valuation_basis_unsynchronized', result['reasons'])

    def test_current_uncompleted_session_rejected_before_network(self):
        from datetime import datetime, timezone
        self.assertTrue(callable(getattr(benchmark, 'utc_now', None)), 'publication clock missing')
        with patch('watchdog.benchmark.utc_now', return_value=datetime(2026, 10, 6, 19, 0, tzinfo=timezone.utc)), patch('market_data._massive_json') as read:
            result = benchmark.load_benchmark('2026-10-01', '2026-10-06')
        self.assertEqual(result['coverage']['status'], 'unknown')
        self.assertIn('benchmark_session_not_completed', result['reasons'])
        read.assert_not_called()
