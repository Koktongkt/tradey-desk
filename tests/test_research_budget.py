"""Guard tests for the 540-second radar envelope and stage deadlines.

The 510-second active allocation is discovery 165 + focused retrieval 120
+ shared evidence/rescue 120 + shared synthesis 60 + shared enrichment 45;
the outer cycle reserves 30 seconds for intake/persistence/scheduling overhead.
Calibration requires observing real provider latency and qualified-candidate rates.
"""
import json
import subprocess
import tempfile
import time
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

import alpha_radar
import earnings_calendar
import market_data
import research_budget
import run_cycle


class DeadlineContextTests(unittest.TestCase):
    def test_stage_telemetry_is_private_and_cannot_block_research(self):
        with tempfile.TemporaryDirectory() as td, patch.object(alpha_radar,"ROOT",Path(td)), patch.object(alpha_radar,"perf_counter",side_effect=[100,107]), alpha_radar.enable_timing():
            with alpha_radar.timed_research_stage("discovery"):
                pass
            row=json.loads((Path(td)/"private"/"research_timings.jsonl").read_text().strip())
            self.assertEqual((row["stage"],row["outcome"],row["elapsed_seconds"]),("discovery","completed",7))
        with patch.object(Path,"open",side_effect=OSError("telemetry unavailable")), alpha_radar.enable_timing():
            with alpha_radar.timed_research_stage("discovery"):
                pass

    def test_active_deadline_clamps_individual_network_timeout(self):
        with patch.object(research_budget, "monotonic", return_value=100):
            with research_budget.active_deadline(108):
                self.assertEqual(research_budget.remaining(30), 8)
            self.assertEqual(research_budget.remaining(30), 30)

    def test_expired_deadline_raises_non_suppressible_timeout(self):
        with patch.object(research_budget, "monotonic", return_value=100):
            with research_budget.active_deadline(100):
                with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                    research_budget.remaining(30)
    def test_enrichment_http_refuses_to_start_after_deadline(self):
        with patch.object(research_budget, "monotonic", return_value=100), research_budget.active_deadline(100):
            with patch.object(earnings_calendar.urllib.request, "urlopen") as fetch:
                with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                    earnings_calendar._get_text("https://example.com/")
                fetch.assert_not_called()
            with patch.object(market_data.urllib.request, "urlopen") as fetch:
                with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                    market_data.synchronized_completed_close_prices("AAPL")
                fetch.assert_not_called()
            with patch.object(market_data.subprocess,"run") as config:
                with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                    market_data.configured_massive_key()
                config.assert_not_called()

    def test_trickling_http_body_is_interrupted_by_wall_clock_deadline(self):
        clock=[100.0]
        class FakeSocket:
            def __init__(self):self.timeouts=[]
            def settimeout(self,seconds):self.timeouts.append(seconds)
        class FakeResponse:
            def __init__(self):
                self.fp=type('Fp',(),{'raw':type('Raw',(),{'_sock':FakeSocket()})()})()
                self.reads=0
            def read1(self,n):
                self.reads+=1
                clock[0]+=5
                return b'x'
        response=FakeResponse()
        with patch.object(research_budget,"monotonic",side_effect=lambda:clock[0]), research_budget.active_deadline(108):
            with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                research_budget.read_http_response(response,max_bytes=50)
        self.assertEqual(response.reads,2)
        self.assertEqual(response.fp.raw._sock.timeouts,[8,3])

    def test_socket_timeout_at_deadline_is_typed_as_enrichment_exhaustion(self):
        clock=[100.0]
        class TimedOutResponse:
            fp=type('Fp',(),{'raw':type('Raw',(),{'_sock':type('Sock',(),{'settimeout':lambda self,seconds:None})()})()})()
            def read1(self,n):
                clock[0]=108.0
                raise TimeoutError('socket deadline')
        with patch.object(research_budget,"monotonic",side_effect=lambda:clock[0]), research_budget.active_deadline(108):
            with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                research_budget.read_http_response(TimedOutResponse())
        with patch.object(research_budget,"monotonic",return_value=108), research_budget.active_deadline(108):
            with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                research_budget.raise_if_expired_timeout(TimeoutError('connect deadline'))

    def test_connect_timeout_at_deadline_preserves_typed_reason(self):
        cases = (("market direct", "market", False, "connect deadline"),
                 ("earnings direct", "earnings", False, "connect deadline"),
                 ("market wrapped", "market", True, "socket deadline"))
        for label, boundary, wrapped, message in cases:
            with self.subTest(case=label):
                clock = [100.0]
                def timed_out(*args, **kwargs):
                    clock[0] = 108.0
                    error = TimeoutError(message)
                    raise urllib.error.URLError(error) if wrapped else error
                with patch.object(research_budget, "monotonic", side_effect=lambda: clock[0]), research_budget.active_deadline(108):
                    if boundary == "market":
                        with patch.object(market_data, "configured_massive_key", return_value="fixture"), patch.object(market_data.urllib.request, "urlopen", side_effect=timed_out):
                            with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                                market_data.synchronized_completed_close_prices("AAPL")
                    else:
                        with patch.object(earnings_calendar.urllib.request, "urlopen", side_effect=timed_out):
                            with self.assertRaises(research_budget.ResearchDeadlineExceeded):
                                earnings_calendar._get_text("https://example.com/")


class ResearchBudgetGuardTests(unittest.TestCase):
    def test_focused_stage_obeys_remaining_global_budget(self):
        with patch.object(alpha_radar,"monotonic",return_value=100), patch.object(alpha_radar,"focused_retrieval_command",return_value=["hermes"]), patch.object(alpha_radar.subprocess,"run",return_value=subprocess.CompletedProcess([],0,'{"candidates":[]}',"")) as run:
            alpha_radar.focused_retrieval([{"symbol":"AAA","catalyst":"dated","event_date":"2026-09-27"}],deadline=109)
            self.assertEqual(run.call_args.kwargs["timeout"],9)
            with self.assertRaises(alpha_radar.ResearchFailure) as caught:
                alpha_radar.focused_retrieval([{"symbol":"AAA","catalyst":"dated","event_date":"2026-09-27"}],deadline=100)
            self.assertEqual(caught.exception.code,"research_focused_retrieval_timeout")
            run.assert_called_once()

    def test_scout_timeout_covers_bounded_discovery_call(self):
        source = (alpha_radar.ROOT / "alpha_radar.py").read_text()
        self.assertIn("input=discovery_prompt(cfg),capture_output=True,text=True,timeout=", source)
        self.assertNotIn("input=SCOUT_PROMPT,capture_output=True,text=True,timeout=240", source)
        self.assertIn("synthesis_deadline=min(overall_deadline,monotonic()+SYNTHESIS_PHASE_BUDGET_SECONDS)", source)
        self.assertIn("timeout=min(SYNTHESIS_BUDGET_SECONDS,remaining),cwd=ROOT", source)

    def test_nine_minute_budget_clips_adaptive_caps_and_preserves_reserve(self):
        self.assertEqual(alpha_radar.RESEARCH_ACTIVE_BUDGET_SECONDS, 510)
        self.assertEqual(alpha_radar.DISCOVERY_TIMEOUT_SECONDS, 165)
        self.assertEqual(alpha_radar.FOCUSED_RETRIEVAL_TIMEOUT_SECONDS, 120)
        self.assertEqual(alpha_radar.EVIDENCE_PIPELINE_BUDGET_SECONDS, 120)
        self.assertEqual(alpha_radar.SYNTHESIS_BUDGET_SECONDS, 60)
        self.assertEqual(alpha_radar.SYNTHESIS_PHASE_BUDGET_SECONDS, 90)
        self.assertEqual(alpha_radar.MIN_SYNTHESIS_WINDOW_SECONDS, 30)
        self.assertEqual(alpha_radar.ENRICHMENT_BUDGET_SECONDS, 45)
        # The extra 30 seconds is borrowed from unused upstream caps, not additive.
        self.assertEqual(alpha_radar.RESEARCH_ACTIVE_BUDGET_SECONDS+30,540)
        self.assertIn("research_enrichment_timeout",run_cycle.ALLOWED_FAILURE_TOKENS)

    def test_scout_run_budget_bounds_discovery(self):
        with patch.object(alpha_radar,"configured_default_model",return_value=("test-provider","test/model")):
            command = alpha_radar.discovery_command()
        budget_index = command.index("--run-budget") + 1
        self.assertEqual(command[budget_index], "130")
        self.assertEqual(command[command.index("--max-turns")+1],"2")
        self.assertEqual(command[command.index("-t")+1],"search")

    def test_focused_retrieval_has_bounded_tool_budget_and_timeout(self):
        with patch.object(alpha_radar,"configured_default_model",return_value=("test-provider","test/model")):
            command=alpha_radar.focused_retrieval_command()
        self.assertEqual(command[command.index("--max-turns")+1],"4")
        self.assertEqual(command[command.index("--run-budget")+1],"90")
        source=(alpha_radar.ROOT/"alpha_radar.py").read_text()
        self.assertIn("focused_retrieval_prompt(candidates),capture_output=True,text=True,timeout=",source)

    def test_cycle_budget_covers_serialized_worst_case(self):
        # Earlier caps remain 165/120/120. Synthesis phase can borrow up to 90,
        # but launches reserve remaining shared enrichment inside active 510.
        # These adaptive caps cannot all be added; outer 540 keeps final 30.
        self.assertEqual(earnings_calendar.SEC_LOOKUP_BUDGET_SECONDS,45)
        self.assertEqual(alpha_radar.EVIDENCE_PIPELINE_BUDGET_SECONDS,120)
        source = (alpha_radar.ROOT / "run_cycle.py").read_text()
        self.assertIn(
            'if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=540',
            source,
        )
        self.assertNotIn(
            'if a.mode in {"premarket","radar"}:rc=execute([sys.executable,str(ROOT/"alpha_radar.py")],timeout_seconds=1110',
            source,
        )


class ScoutReliabilityGuardTests(unittest.TestCase):
    """Guard tests from the 2026-09-09 3-run fetch-failure streak.

    Causes addressed: scout URL hallucination (ir.ionq.com NXDOMAIN),
    intermittent source timeouts (businesswire.com), and a too-thin URL
    surplus (5 candidates minus dedupe/walls/staleness left <2 usable).
    """

    def test_scout_prompt_discovery_contracts(self):
        cases = (
            ("verified article URL", True, "confirmed article URL copied exactly from the web_search results"),
            ("no guessed URLs", True, "Never construct or guess"),
            ("candidate schema", True, '"candidates"'),
            ("ranked groups", True, "one to five candidates in ranked order"),
            ("one confirmed URL", True, "at least one confirmed article URL"),
            ("focused stage", True, "focused retrieval stage"),
            ("deferred two-domain gate", True, "apply the final two-domain evidence gate"),
            ("four parallel searches", True, "call web_search exactly four times in parallel with limit 10 each"),
            ("one tool turn", True, "Use exactly one tool-using turn"),
            ("no extraction tool", False, "web_extract"),
            ("no page extraction", True, "Do not extract pages"),
        )
        for label, present, phrase in cases:
            with self.subTest(case=label):
                if present:
                    self.assertIn(phrase, alpha_radar.SCOUT_PROMPT)
                else:
                    self.assertNotIn(phrase, alpha_radar.SCOUT_PROMPT)


    def test_live_research_enforces_five_total_discovery_urls(self):
        source = (alpha_radar.ROOT / "alpha_radar.py").read_text()
        self.assertIn("scout_parse_result(scout.stdout,max_candidates=5,max_urls=5)", source)

    def test_gather_evidence_timeout_goes_to_gateway_without_second_direct_attempt(self):
        attempts = {"n": 0}

        def fetch(url, _timeout):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise TimeoutError("read timed out")
            return {"url": url, "title": "Recovered", "text": "usable evidence", "published_at": "2026-09-08T15:00:00Z"}

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch), patch.object(
            alpha_radar,"fetch_source_via_gateway",return_value={"url":"https://flaky.example/a","title":"Gateway","text":"usable evidence","published_at":"2026-09-08T15:00:00Z"}
        ) as gateway:
            pages = alpha_radar.gather_evidence(["https://flaky.example/a"])

        self.assertEqual(attempts["n"], 1)
        gateway.assert_called_once()
        self.assertEqual([page["title"] for page in pages], ["Gateway"])

    def test_gather_evidence_identical_urls_fetch_once_and_bind_result(self):
        url="https://shared.example/article"
        page={"url":url,"title":"Shared","text":"usable evidence","published_at":"2026-09-08T15:00:00Z"}
        with patch.object(alpha_radar,"fetch_source",return_value=page) as direct:
            pages=alpha_radar.gather_evidence([url,url,url])
        direct.assert_called_once()
        self.assertEqual(pages,[page])

    def test_duplicate_cache_hit_does_not_extend_ttl_or_fetch(self):
        url="https://cached.example/one"
        page={"url":url,"title":"Cached","text":"body","published_at":"2026-09-08"}
        stamp=alpha_radar.dt.datetime.now(alpha_radar.dt.timezone.utc).isoformat().replace("+00:00","Z")
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"cache.json"
            cache.write_text(json.dumps({url:{"page":page,"checked_at":stamp}}))
            with patch.object(alpha_radar,"fetch_source") as direct:
                pages=alpha_radar.gather_evidence([url,url],cache_path=cache)
            self.assertEqual(json.loads(cache.read_text())[url]["checked_at"],stamp)
        direct.assert_not_called()
        self.assertEqual(pages,[page])

    def test_direct_page_for_different_url_cannot_enter_cache_or_evidence(self):
        url="https://requested.example/a"
        wrong={"url":"https://other.example/a","title":"Other","text":"body","published_at":"2026-09-08"}
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"cache.json"
            with patch.object(alpha_radar,"fetch_source",return_value=wrong), patch.object(alpha_radar,"fetch_source_via_gateway",return_value=None):
                pages=alpha_radar.gather_evidence([url,url],cache_path=cache)
            self.assertEqual(pages,[])
            self.assertNotIn(wrong["url"],json.loads(cache.read_text()))

    def test_clear_timeout_preserves_remaining_deadline_for_gateway(self):
        url="https://timed.example/a"
        deadline=alpha_radar.monotonic()+0.3
        seen=[]
        def gateway(_url,timeout_seconds=None):
            seen.append(timeout_seconds)
            return {"url":url,"text":"body"}
        with patch.object(alpha_radar,"fetch_source",side_effect=TimeoutError("timed out")) as direct, patch.object(alpha_radar,"fetch_source_via_gateway",side_effect=gateway):
            pages=alpha_radar.gather_evidence([url],collection_deadline=deadline)
        self.assertEqual(pages[0]["url"],url)
        direct.assert_called_once()
        self.assertTrue(0<seen[0]<=min(alpha_radar.GATEWAY_FALLBACK_TIMEOUT_SECONDS,0.3))

    def test_gather_evidence_records_single_timeout_after_retry_exhausted(self):
        diagnostics = []

        def fetch(url, _timeout):
            raise TimeoutError("read timed out")

        with patch.object(alpha_radar, "fetch_source", side_effect=fetch), patch.object(
            alpha_radar, "fetch_source_via_gateway", return_value=None
        ):
            pages = alpha_radar.gather_evidence(
                ["https://down.example/a"], diagnostics=diagnostics
            )

        self.assertEqual(pages, [])
        self.assertEqual(
            diagnostics,
            [{"url":"https://down.example/a","domain": "down.example", "reason": "source_fetch_timeout"}],
        )

    def test_gather_evidence_retries_connection_reset_once(self):
        for label, url, wrapped in (
            ("direct reset", "https://bad.example/a", False),
            ("wrapped reset", "https://wrapped.example/a", True),
        ):
            with self.subTest(case=label):
                attempts = {"n": 0}
                def fetch(requested, _timeout):
                    attempts["n"] += 1
                    if attempts["n"] == 1:
                        error = ConnectionResetError("reset")
                        raise urllib.error.URLError(error) if wrapped else error
                    return {"url": requested, "title": "Recovered", "text": "usable evidence", "published_at": "2026-09-08T15:00:00Z"}
                with patch.object(alpha_radar, "fetch_source", side_effect=fetch):
                    pages = alpha_radar.gather_evidence([url])
                self.assertEqual(attempts["n"], 2)
                self.assertEqual([page["title"] for page in pages], ["Recovered"])


    def test_collection_budget_exhaustion_is_typed_without_starting_fetch(self):
        diagnostics=[]
        with patch.object(alpha_radar,"fetch_source") as direct:
            pages=alpha_radar.gather_evidence(
                ["https://late.example/a"],diagnostics=diagnostics,collection_budget_seconds=0
            )
        direct.assert_not_called()
        self.assertEqual(pages,[])
        self.assertEqual(diagnostics,[{
            "url":"https://late.example/a","domain":"late.example","reason":"source_deadline_exhausted"
        }])

    def test_fresh_source_cache_avoids_network_fetch(self):
        page={"url":"https://cached.example/a","title":"Cached","text":"usable cached evidence","published_at":"2026-09-08T15:00:00Z"}
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"source_cache.json"
            with patch.object(alpha_radar,"fetch_source",return_value=page) as direct:
                first=alpha_radar.gather_evidence([page["url"]],cache_path=cache)
                original_checked_at=json.loads(cache.read_text())[page["url"]]["checked_at"]
                second=alpha_radar.gather_evidence([page["url"]],cache_path=cache)
                cached_checked_at=json.loads(cache.read_text())[page["url"]]["checked_at"]
        self.assertEqual(first,second)
        self.assertEqual(direct.call_count,1)
        self.assertEqual(cached_checked_at,original_checked_at)

    def test_fresh_source_cache_rejects_page_bound_to_different_url(self):
        requested="https://cached.example/requested"
        correct={"url":requested,"title":"Fresh","text":"usable fresh evidence","published_at":"2026-09-08T15:00:00Z"}
        with tempfile.TemporaryDirectory() as td:
            cache=Path(td)/"source_cache.json"
            cache.write_text(json.dumps({requested:{
                "checked_at":alpha_radar.dt.datetime.now(alpha_radar.dt.timezone.utc).isoformat().replace("+00:00","Z"),
                "page":{"url":"https://wrong.example/article","title":"Wrong","text":"wrong cached evidence","published_at":"2026-09-08T15:00:00Z"},
            }}))
            with patch.object(alpha_radar,"fetch_source",return_value=correct) as direct:
                pages=alpha_radar.gather_evidence([requested],cache_path=cache)
        direct.assert_called_once()
        self.assertEqual(pages,[correct])


class GatewayFallbackGuardTests(unittest.TestCase):
    """Bot-walled and timing-out primary sources (businesswire.com timeouts,
    investors.* 403s) get one bounded gateway-backed extraction fallback per
    URL. The fallback shells out to the hermes web toolset, which routes
    through the provider gateway and extracted pages direct fetching could
    not (verified 2026-09-09: businesswire.com article recovered)."""

    def test_gather_evidence_falls_back_on_timeout_after_retry(self):
        calls = []

        def direct(url, _timeout):
            calls.append("direct")
            raise TimeoutError("read timed out")

        def fallback(cmd, input=None, capture_output=None, text=None, timeout=None, cwd=None):
            calls.append("fallback")
            self.assertIn("web", cmd)
            return subprocess.CompletedProcess(
                cmd, 0, "Published 2026-09-08. Revenue rose 37 percent year over year.", ""
            )

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run", side_effect=fallback
        ):
            pages = alpha_radar.gather_evidence(["https://walled.example/a"])

        self.assertEqual(calls, ["direct", "fallback"])
        self.assertEqual(len(pages), 1)
        self.assertEqual(pages[0]["url"], "https://walled.example/a")
        self.assertIn("37 percent", pages[0]["text"])

    def test_businesswire_forbidden_skips_direct_retry_and_uses_gateway(self):
        calls=[]
        def direct(url,_timeout):
            calls.append("direct")
            raise urllib.error.HTTPError(url,403,"forbidden",{},None)
        def gateway(url,timeout_seconds=60):
            calls.append("gateway")
            return {"url":url,"title":"Wire","text":"usable wire evidence","published_at":"2026-09-08T15:00:00Z"}
        with patch.object(alpha_radar,"fetch_source",side_effect=direct), patch.object(
            alpha_radar,"fetch_source_via_gateway",side_effect=gateway
        ):
            pages=alpha_radar.gather_evidence(["https://www.businesswire.com/news/home/1/en/Test"])
        self.assertEqual(calls,["direct","gateway"])
        self.assertEqual([page["title"] for page in pages],["Wire"])

    def test_shared_gateway_failure_preserves_implicit_and_explicit_causes(self):
        error=OSError("private fixture")
        for explicit in (False,True):
            try:
                raise error
            except OSError:
                with self.assertRaises(alpha_radar.ResearchFailure) as caught:
                    alpha_radar._gateway_provider_failure(True,error if explicit else None)
            self.assertEqual((caught.exception.code,caught.exception.__cause__,caught.exception.__context__,caught.exception.__suppress_context__), ("research_rescue_unavailable",error if explicit else None,error,explicit))

    def test_gateway_fallback_failure_keeps_typed_timeout(self):
        diagnostics = []

        def direct(url, _timeout):
            raise TimeoutError("read timed out")

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run", side_effect=subprocess.TimeoutExpired(cmd="x", timeout=30)
        ):
            pages = alpha_radar.gather_evidence(
                ["https://walled.example/a"], diagnostics=diagnostics
            )

        self.assertEqual(pages, [])
        self.assertEqual(diagnostics, [{"url":"https://walled.example/a","domain": "walled.example", "reason": "source_fetch_timeout"}])

    def test_strict_gateway_failure_propagates_as_global_research_failure(self):
        def direct(url, _timeout):
            raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)

        failed = subprocess.CompletedProcess([], 1, "", "provider unavailable")
        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run", return_value=failed
        ):
            with self.assertRaises(alpha_radar.ResearchFailure) as ctx:
                alpha_radar.gather_evidence(
                    ["https://www.reuters.com/markets/requested"],
                    strict_gateway_provider=True,
                )

        self.assertEqual(ctx.exception.code, "research_rescue_unavailable")

    def test_strict_gateway_inflight_at_shared_deadline_is_global_failure(self):
        def direct(url, _timeout):
            raise urllib.error.HTTPError(url, 403, "forbidden", {}, None)

        def slow_gateway(url, timeout_seconds=None, strict_provider=False):
            self.assertTrue(strict_provider)
            time.sleep(0.05)
            raise alpha_radar.ResearchFailure("research_rescue_unavailable")

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar, "fetch_source_via_gateway", side_effect=slow_gateway
        ):
            with self.assertRaises(alpha_radar.ResearchFailure) as ctx:
                alpha_radar.gather_evidence(
                    ["https://www.reuters.com/markets/requested"],
                    collection_deadline=alpha_radar.monotonic()+0.01,
                    strict_gateway_provider=True,
                )

        self.assertEqual(ctx.exception.code, "research_rescue_unavailable")

    def test_gateway_fallback_only_invoked_for_failures_not_successes(self):
        def direct(url, _timeout):
            return {"url": url, "title": "Direct", "text": "fine", "published_at": "2026-09-08T15:00:00Z"}

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run"
        ) as boot:
            pages = alpha_radar.gather_evidence(["https://ok.example/a"])

        boot.assert_not_called()
        self.assertEqual([page["title"] for page in pages], ["Direct"])

    def test_gateway_fallback_output_is_empty_is_not_evidence(self):
        def direct(url, _timeout):
            raise TimeoutError("read timed out")

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess,
            "run",
            return_value=subprocess.CompletedProcess([], 0, "   ", ""),
        ):
            pages = alpha_radar.gather_evidence(["https://walled.example/a"])

        self.assertEqual(pages, [])

    def test_gateway_fallback_has_bounded_timeout(self):
        captured = {}

        def direct(url, _timeout):
            raise TimeoutError("read timed out")

        def fallback(cmd, input=None, capture_output=None, text=None, timeout=None, cwd=None):
            captured["timeout"] = timeout
            return subprocess.CompletedProcess(cmd, 0, "body", "")

        with patch.object(alpha_radar, "fetch_source", side_effect=direct), patch.object(
            alpha_radar.subprocess, "run", side_effect=fallback
        ):
            alpha_radar.gather_evidence(["https://walled.example/a"])

        self.assertIsNotNone(captured.get("timeout"))
        self.assertLessEqual(captured["timeout"], 60)


if __name__ == "__main__":
    unittest.main()
