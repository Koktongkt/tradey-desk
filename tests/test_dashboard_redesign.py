import json
import shutil
import subprocess
import unittest

import public_dashboard

NODE = shutil.which("node")


def _horizons(count):
    side = {"count": count, "avg_excess_pct": 1.25 if count else None}
    return {str(h): {"traded": dict(side), "skipped": dict(side)} for h in (1, 3, 5, 10)}


def _data(outcome_count=0):
    return {
        "performance": {"qualified_candidates": 190, "confirmed_trades": 27},
        "reviews": {"total_dual_model_reviews": 202, "agreements": 20, "disagreements": 39},
        "desk_status": {"enabled": True, "broker_mode": "paper", "account_cap_usd": 10000,
                        "max_position_usd": 500, "max_daily_orders": 3, "min_reward_risk": 1.6},
        "outcome_horizons": _horizons(outcome_count),
        "live_portfolio": {"captured_at": "2026-11-13T22:52:53Z", "holdings": [],
                           "summary": {"total_balance_usd": 9928.9, "cash_usd": 9444.1,
                                       "positions_value_usd": 484.8, "day_excess_pct": 0.32}},
        "watchdog": {"available": True, "strategy": {"marked_equity": "10020", "coverage": {"status": "incomplete"}},
                     "account": {"equity": "50000", "cash": "1"}},
        "decision_audit": [], "recent_orders": [], "blocker_diagnostics": [], "researched_candidates": [],
        "last_activity_at": "2026-11-13T22:15:50Z",
    }


def render(data):
    script = public_dashboard.html_template().split("<script>", 1)[1].split("</script>", 1)[0]
    harness = ("const nodes={};global.document={querySelector:s=>nodes[s]||(nodes[s]={value:'all',innerHTML:'',"
               "addEventListener(){},insertAdjacentHTML(){}})};global.fetch=async()=>({ok:true,json:async()=>("
               + json.dumps(data) + ")});\n" + script + "\nsetImmediate(()=>console.log(nodes['#app'].innerHTML));")
    return subprocess.run([NODE or "node", "-e", harness], text=True, capture_output=True, check=True).stdout


class DashboardRedesignTemplateTests(unittest.TestCase):
    def test_theme_defaults_dark_and_persists_a_toggle(self):
        html = public_dashboard.html_template()
        self.assertIn('<html lang="en" data-theme="dark">', html)
        self.assertIn('[data-theme="light"]', html)
        self.assertIn("data-theme-toggle", html)
        self.assertIn("localStorage.setItem('tradey-theme'", html)

    def test_theme_init_script_is_not_the_first_bare_script(self):
        # Render harnesses take the first bare <script> as the app; theme init must not shadow it.
        html = public_dashboard.html_template()
        self.assertIn("<script data-theme-init>", html)
        self.assertIn("fetch('dashboard.json')", html.split("<script>", 1)[1])

    def test_reduced_motion_is_respected(self):
        self.assertIn("prefers-reduced-motion:reduce", public_dashboard.html_template())


@unittest.skipUnless(NODE, "node is required for the render harness")
class DashboardRedesignRenderTests(unittest.TestCase):
    def test_kpi_strip_leads_with_balance_then_benchmark(self):
        page = render(_data())
        self.assertIn('class="kpis"', page)
        self.assertLess(page.index('class="kpis"'), page.index("Current Alpaca holdings"))
        self.assertLess(page.index("Current balance"), page.index("Live portfolio vs SPY"))

    def test_activity_logs_are_tabbed(self):
        page = render(_data())
        for marker in ('id="tab-decisions"', 'id="tab-orders"', 'id="panel-decisions"', 'id="panel-orders" hidden',
                       'role="tablist"', 'id="decision-events"', 'id="order-events"'):
            self.assertIn(marker, page)

    def test_outcomes_collapse_to_empty_state_without_samples(self):
        page = render(_data(outcome_count=0))
        self.assertIn("Candidate outcomes", page)
        self.assertIn("No matured outcome samples yet", page)
        self.assertNotIn("<th>Traded excess</th>", page)

    def test_outcomes_table_renders_when_samples_exist(self):
        page = render(_data(outcome_count=2))
        self.assertIn("<th>Traded excess</th>", page)
        self.assertNotIn("No matured outcome samples yet", page)

    def test_funnel_bars_are_proportional_with_review_shares(self):
        page = render(_data())
        self.assertIn('class="f-bar ', page)
        self.assertIn("width:100.0%", page)  # largest stage (202 reviews)
        self.assertIn("10% of reviews", page)  # 20 / 202 agreed
        self.assertIn("19% of reviews", page)  # 39 / 202 disagreed

    def test_watchdog_coverage_is_badged(self):
        page = render(_data())
        self.assertIn('<span class="badge warn">incomplete</span>', page)
        self.assertIn("$10,020", page)
        self.assertIn("$50,000", page)


if __name__ == "__main__":
    unittest.main()
