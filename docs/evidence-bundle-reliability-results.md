# Evidence-bundle reliability: implementation and measured outcome

Runtime commit: `4e6ac6090ffdfd3efc054023f641d296ad3c4f2e` on the isolated `design/discovery-quality-first` branch. Production remains unchanged.

## Conclusion

The implementation is exercised and regression-tested, but the live improvement criterion is **not met**: both versions produced zero same-candidate two-publisher bundles, zero syntheses and zero final qualified dossiers. The newer path was faster on this one sequential matched cohort; that is not a demonstrated reliability gain or a deployment justification.

## Implemented

- Private original-representation retention through acquisition, worker projection and normalization, with exact URL/title/raw/projection digest binding. Public extraction responses do not expose private capture fields. Selected provider publication metadata is retained as untrusted hints, not publication authority; omitted fields/capacity/incomplete representations are explicit.
- Independent current-article header/body witnesses for supported Markdown and HTML structures. Nested related/event sections cannot authorize the article's publication date or body, including through a flattened projection.
- Optional exact article-body selection in the existing one-shot publication interpretation batch. Body-only repair preserves an already valid publication observation or exact legacy timestamp; invalid-present markers, stale/future dates, conflicts and precision restrictions remain protected.
- Gap-directed focused-search instructions and opt-in code-owned missing-publisher rescue. One actual search per missing independent/wire lane replaces its model URL courier, filters attempted URLs and accepted publishers, and retains existing dispatcher, deadlines, round-robin fairness and caps.

No new providers, keys, dependencies, Hermes changes, gateway restarts, search/model/recovery budget increases or evidence/trading exceptions were introduced.

## Verification

- Final full and raw suites: **1615 tests each**, zero failures/errors/skips; zero unexpected Hermes/local-control attempts, one expected blocked control, zero external-network attempts in the guarded parent interpreter. The guard is not an OS/descendant sandbox.
- Independent review identified two Important issues: section/ancestor ownership and body repair with known publication. Both were reproduced RED, fixed, and passed the full/raw gates. No additional actionable Minor finding.
- Frozen reused corpus: 17 hash-verified original captures recovered without wrong accepted values or precision loss; 13 remained freshness-rejected. These were development-reused controls, not prospective acceptance gains.

## Matched live test

UTC 22 October 2026, approximately 07:12–07:18, outside the US regular session. One real shared discovery produced five provisional candidates: IRDM, LEU, CCI, DHR and TSLA. These were research targets, not trade recommendations.

Each arm received an independent copy of those exact live candidates, then ran actual focused search, extraction, rescue and publication verification. Shared discovery plus startup cost51.315s was deducted from both original690s active/720s outer windows. Source versions were prior`2c67769` versus new`4e6ac60`; both used the same policy configuration and separate fresh inner test_artifacts SQLite roots. Sequential searches/provider responses can differ; this is not a statistical comparison or a claim of production dossier-spending eligibility.

New version:
- Five focused URLs, four extracted representations, one initially accepted page.
- Two distinct fresh accepted URL IDs after evidence/rescue, across the candidate pool—not a two-publisher bundle for one candidate.
- Seven distinct unknown-freshness URL IDs; three publication proposals rejected as inadmissible.
- Downstream100.280s; total charged151.595s; rescue49.845s.
- Final`research_source_freshness_insufficient`; zero synthesis/qualified dossiers.

Prior version:
- Six focused URLs, five extracted representations, two initially accepted pages.
- Two distinct fresh accepted URL IDs after evidence/rescue; no qualifying bundle.
- Three distinct unknown-freshness URL IDs; three publication proposals rejected as inadmissible.
- Downstream146.222s; total charged197.537s; rescue97.748s.
- Same final failure; zero synthesis/qualified dossiers.

The different URL pools mean fewer unknowns is not automatically better coverage, and faster rescue is not proof of better evidence quality.

## What remains binding

In the new arm's five cached page records, four original captures were omitted under the unchanged capacity limit; one complete provider representation survived. That complete representation had a timezone-bearing timestamp before a bold Markdown headline, rather than the explicit publication relations supported by the new witness grammar. Its presence is observable; it is not permission to accept a date solely from proximity. Existing guardrails correctly left unsupported publication authority unresolved.

Thus fixture recovery did not translate into live bundle completion. Broadening admissibility to fit a single failed scan or raising limits would not be a justified fix. Before substantial further changes, agree the next narrower recovery contract: compact provenance-preserving capture/witness transport for large pages, plus independently validated publication-header structures actually present in retained publisher representations, with negative event/update/related-story controls. Keep final same-event two-publisher and qualification acceptance as the objective.

## Safety and carried limitations

No production candidates were published; no reviewer/autotrader/broker entrypoint was invoked. Monitored production and worktree configurations, candidate/order ledgers, intents and reviews were hash-identical before/after the live comparison. No production activation, push or merge occurred.

An earlier failed test run missed renamed private-dispatch mocks; unintended source HTTP traffic during that run remains unverified despite no recorded Hermes launch. The mocks were corrected and a sticky parent network guard added. Its first full run caught five older unmocked DNS lookups in a mismatched second-URL fixture; the fixture was corrected to the actual requested URL without weakening production safety validation.

One earlier unchanged process-lifetime test failed (`test_outer_scheduler_timeout_retains_lock_until_orphans_are_reaped`, pid1421621 present at the successor-lock assertion). Three focused repeats and later full/raw suites passed, but the original root cause remains unresolved. No supervisor, lock or execution control was altered, and this report does not declare that failure harmless or certify deployment readiness.

Private proof: `test_artifacts/evidence-bundle-live-20261022T064006Z/` (comparison, shared discovery, source/config hashes, per-arm timings/diagnostics/cache and final metrics). Preserve raw evidence privately, separate from source publication.
