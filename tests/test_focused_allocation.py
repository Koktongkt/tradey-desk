"""Pure, offline focused URL allocation contracts."""
import copy
from dataclasses import FrozenInstanceError
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class FocusedAllocationTests(unittest.TestCase):
    def allocate(self, candidates, alternatives, **changes):
        from focused_allocation import allocate_urls
        eligible = {url for candidate in candidates for url in candidate.get('urls', [])}
        eligible.update(url for urls in alternatives.values() for url in urls)
        return allocate_urls(candidates, alternatives, eligible_urls=changes.get('eligible_urls', eligible),
                             unhealthy_domains=changes.get('unhealthy_domains', set()))

    def test_five_candidates_receive_five_in_round_order(self):
        symbols = ['AAA', 'BBB', 'CCC', 'DDD', 'EEE']
        seeds = [f'https://seed.example/{symbol}' for symbol in symbols]
        candidates = [{'symbol': symbol, 'urls': [seed]} for symbol, seed in zip(symbols, seeds)]
        alternatives = {symbol: [f'https://p{i}.example/{symbol}' for i in range(4)] for symbol in symbols}
        result = self.allocate(candidates, alternatives)
        self.assertEqual(list(map(len, result.by_symbol.values())), [5] * 5)
        self.assertEqual(len(result.unique_urls), 25)
        self.assertEqual(list(map(len, result.batches)), [5] * 5)
        self.assertEqual(result.batches[0], seeds)
        self.assertEqual(result.unique_urls, seeds + [alternatives[s][i] for i in range(4) for s in symbols])
        self.assertEqual(result.available_counts, dict.fromkeys(symbols, 5))
        self.assertEqual(result.uncovered, {})

    def test_starved_fourth_candidate_gets_seed_before_extras(self):
        symbols = ['AAA', 'BBB', 'CCC', 'DDD']
        seeds = [f'https://seed.example/{s}' for s in symbols]
        candidates = [{'symbol': s, 'urls': [url, url]} for s, url in zip(symbols, seeds)]
        alternatives = {s: [f'https://p{i}.example/{s}' for i in range(n)]
                        for s, n in zip(symbols, [1, 3, 3, 0])}
        result = self.allocate(candidates, alternatives)
        self.assertEqual(result.batches[0][:4], seeds)
        self.assertEqual([len(result.by_symbol[s]) for s in symbols], [2, 4, 4, 1])
        self.assertEqual(len(result.unique_urls), len(set(result.unique_urls)))
        self.assertEqual(result.uncovered, {})
        alternatives['AAA'] = [f'https://many.example/{i}' for i in range(10)]
        result = self.allocate(candidates, alternatives)
        self.assertEqual(len(result.by_symbol['AAA']), 5)
        self.assertEqual(result.by_symbol['DDD'], [seeds[3]])
        self.assertEqual(result.available_counts['AAA'], 11)

    def test_shared_url_preserves_only_explicit_bindings(self):
        shared = 'https://shared.example/article'
        exact_other = shared + '?view=full'
        candidates = [{'symbol': 'AAA', 'urls': [shared]},
                      {'symbol': 'BBB', 'urls': ['https://b.example/seed']},
                      {'symbol': 'CCC', 'urls': ['https://c.example/seed']}]
        alternatives = {'AAA': [shared, exact_other], 'BBB': [shared, shared],
                        'UNBOUND': ['https://orphan.example/article']}
        result = self.allocate(candidates, alternatives)
        self.assertEqual(result.by_symbol['AAA'], [shared, exact_other])
        self.assertEqual(result.by_symbol['BBB'], [candidates[1]['urls'][0], shared])
        self.assertNotIn(shared, result.by_symbol['CCC'])
        self.assertEqual(result.unique_urls, [shared, candidates[1]['urls'][0],
                                             candidates[2]['urls'][0], exact_other])
        self.assertEqual(result.available_counts, {'AAA': 2, 'BBB': 2, 'CCC': 1})
        self.assertEqual(result.batches, [result.unique_urls])

    def test_publisher_diversity_then_health_then_provenance(self):
        seed = 'https://www.reuters.com/seed'
        same = 'https://reuters.com/other'
        unhealthy = 'https://sec.gov/filing'
        wire = 'https://businesswire.com/release'
        unknown = 'https://unknown.example/article'
        independent = 'https://bloomberg.com/article'
        unknown_two = 'https://another.example/article'
        candidates = [{'symbol': 'AAA', 'urls': [seed]}, {'symbol': 'BBB', 'urls': [seed]}]
        alternatives = {'AAA': [same, unhealthy, wire, unknown, independent, unknown_two], 'BBB': [same]}
        result = self.allocate(candidates, alternatives, unhealthy_domains={'sec.gov'})
        self.assertEqual(result.by_symbol['AAA'], [seed, independent, wire, unknown, unknown_two])
        self.assertEqual(result.by_symbol['BBB'], [seed, same])
        # A new but unhealthy publisher still outranks a healthy repeat publisher.
        result = self.allocate(candidates[:1], {'AAA': [same, unhealthy]}, unhealthy_domains={'sec.gov'})
        self.assertEqual(result.by_symbol['AAA'], [seed, unhealthy, same])
        # Rank ties preserve exact input order, not set order or alphabetical order.
        result = self.allocate(candidates[:1], {'AAA': [unknown_two, unknown]})
        self.assertEqual(result.by_symbol['AAA'], [seed, unknown_two, unknown])

    def test_unhealthy_seed_keeps_first_slot(self):
        seed = 'https://unknown.example/seed'
        healthy = 'https://sec.gov/filing'
        unsafe = 'https://private.example/article'
        candidates = [{'symbol': 'AAA', 'urls': [seed]},
                      {'symbol': 'BBB', 'urls': [unsafe]},
                      {'symbol': 'CCC', 'urls': ['not a url']}]
        result = self.allocate(candidates, {'AAA': [healthy]}, eligible_urls={seed, healthy},
                               unhealthy_domains={'unknown.example'})
        self.assertEqual(result.by_symbol, {'AAA': [seed, healthy], 'BBB': [], 'CCC': []})
        self.assertEqual(result.available_counts, {'AAA': 2, 'BBB': 0, 'CCC': 0})
        self.assertEqual(result.uncovered, {'BBB': 'no_eligible_url', 'CCC': 'no_eligible_url'})
        self.assertEqual(result.unique_urls, [seed, healthy])

    def test_invalid_syntax_is_rejected_even_if_attested(self):
        invalid = ['not a url', 'ftp://example.com/article', 'https://', 'https://[broken',
                   'https://example.com:bad/path', 'https://user:pass@example.com/path',
                   ' https://example.com/path', 'https://example.com/has space',
                   'https://example.com/line\nbreak']
        candidates = [{'symbol': 'AAA', 'urls': invalid}]
        result = self.allocate(candidates, {})
        self.assertEqual(result.by_symbol, {'AAA': []})
        self.assertEqual(result.batches, [])
        self.assertEqual(result.uncovered, {'AAA': 'no_eligible_url'})

    def test_without_eligible_seed_first_alternative_is_ranked(self):
        wire = 'https://businesswire.com/release'
        primary = 'https://sec.gov/filing'
        candidates = [{'symbol': 'AAA', 'urls': ['https://unsafe.example/seed']}]
        result = self.allocate(candidates, {'AAA': [wire, primary]}, eligible_urls={wire, primary})
        self.assertEqual(result.by_symbol['AAA'], [primary, wire])

    def test_only_first_five_candidates_are_retained(self):
        candidates = [{'symbol': str(i), 'urls': [f'https://seed.example/{i}']} for i in range(7)]
        alternatives = {str(i): [f'https://p{j}.example/{i}' for j in range(9)] for i in range(7)}
        result = self.allocate(candidates, alternatives)
        self.assertEqual(list(result.by_symbol), ['0', '1', '2', '3', '4'])
        self.assertEqual(list(result.available_counts.values()), [10] * 5)
        self.assertEqual(len(result.unique_urls), 25)
        self.assertEqual(list(map(len, result.batches)), [5] * 5)

    def test_duplicate_candidate_symbol_keeps_first_explicit_pool(self):
        first = 'https://first.example/seed'
        second = 'https://second.example/seed'
        candidates = [{'symbol': 'AAA', 'urls': [first]}, {'symbol': 'AAA', 'urls': [second]}]
        result = self.allocate(candidates, {})
        self.assertEqual(result.by_symbol, {'AAA': [first]})
        self.assertEqual(result.available_counts, {'AAA': 1})

    def test_empty_input_is_a_normal_empty_allocation(self):
        result = self.allocate([], {'AAA': ['https://orphan.example/article']})
        self.assertEqual(result.by_symbol, {})
        self.assertEqual(result.unique_urls, [])
        self.assertEqual(result.batches, [])
        self.assertEqual(result.available_counts, {})
        self.assertEqual(result.uncovered, {})

    def test_allocation_is_repeatable_without_mutating_inputs(self):
        from focused_allocation import allocate_urls
        seed = 'https://unknown.example/seed'
        extra = 'https://sec.gov/filing'
        inputs = ([{'symbol': 'AAA', 'urls': [seed, seed]}], {'AAA': [extra, seed]},
                  {seed, extra}, {'unknown.example'})
        before = copy.deepcopy(inputs)
        first = allocate_urls(inputs[0], inputs[1], eligible_urls=inputs[2], unhealthy_domains=inputs[3])
        second = allocate_urls(inputs[0], inputs[1], eligible_urls=inputs[2], unhealthy_domains=inputs[3])
        self.assertEqual(inputs, before)
        self.assertEqual(first, second)
        self.assertIsNot(first.by_symbol['AAA'], second.by_symbol['AAA'])
        with self.assertRaises(FrozenInstanceError):
            setattr(first, 'unique_urls', [])

    def test_fresh_import_and_allocation_do_not_use_network_processes_or_config(self):
        code = textwrap.dedent('''
            import sys
            def forbid_io(event, args):
                if event.startswith('socket.') or event in {'subprocess.Popen', 'os.system'}:
                    raise AssertionError('unexpected external I/O: ' + event)
                if event == 'open' and str(args[0]).endswith(('config.yaml', 'config.json', 'autonomy_config.json')):
                    raise AssertionError('unexpected config lookup')
            sys.addaudithook(forbid_io)
            from focused_allocation import allocate_urls
            seed = 'https://unknown.example/seed'
            extra = 'https://sec.gov/filing'
            result = allocate_urls([{'symbol': 'AAA', 'urls': [seed]}], {'AAA': [extra]},
                                   eligible_urls={seed, extra}, unhealthy_domains={'unknown.example'})
            assert result.by_symbol == {'AAA': [seed, extra]}
        ''')
        result = subprocess.run([sys.executable, '-c', code], cwd=Path(__file__).resolve().parents[1],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, '')


if __name__ == '__main__':
    unittest.main()
