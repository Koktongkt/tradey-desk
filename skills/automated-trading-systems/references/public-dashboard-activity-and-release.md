# Public dashboard activity and release verification

## Activity-panel pattern

Publish every sanitized decision and review/order lifecycle row; do not impose an undocumented backend or UI tail cap. Keep the interface usable by filtering in the browser:

- default: the visitor's local calendar day;
- rolling windows: 24 hours, 5 days, 7 days, 30 days, and 365 days;
- all history;
- custom local start/end dates, with the end date inclusive.

Display the selected decision and order counts. Sort newest first after filtering and place long lists inside bounded, independently scrollable columns.

Generate explanations from a fixed map keyed by normalized reason, decision, or status code. Precedence should be normalized reason, then decision, then status, then a generic sanitized fallback. Publish only the generated summary; never summarize raw reviewer prose for the public artifact. Render it with native `<details><summary>Why?</summary>…</details>` so rows stay compact and keyboard-accessible. Escape the headline, symbol, labels, and summary before interpolation.

Regression coverage should prove:

1. More than the former cap survives the data build.
2. Every public row has a non-empty safe summary.
3. Nested private reviews can contribute only explicitly allowed identity fields, such as a sanitized ticker.
4. Today is the selected default and every requested range/control exists.
5. Rolling and custom inclusive boundaries behave correctly under a fixed timezone/time.
6. The generated inline script passes `node --check`.

## Artifact-only release sequence

1. Build the private generator's public output.
2. Run the public-output verifier on the build directory containing only publishable artifacts.
3. Copy `index.html` and `dashboard.json` into the separate public repository with `cp`.
4. Use `cmp` to prove source and destination bytes match; require `git status` to show both files modified, then run `git diff --check` and inspect `git diff --stat`.
5. If the repository root also has a README that says phrases such as “never publish private reviews,” scan a temporary artifact-only directory rather than weakening the forbidden-term detector or changing accurate policy prose.
6. Set repository-local author identity to match prior commits, commit only the built artifacts, and push.
7. Compare local `HEAD` with `git ls-remote origin -h refs/heads/main` before claiming GitHub publication.
8. Deploy the already-scanned built directory to the linked Vercel production project.
9. Fetch production `index.html` and `dashboard.json`; compare each byte-for-byte and by SHA-256 with the local artifacts.
10. Parse the remote JSON and assert expected row counts/summary completeness; inspect the remote HTML for the default filter, custom dates, and expandable summary controls.
11. Require 404 responses for `.env.local`, private directories, operational ledgers, and any other non-public path.

A deployment receipt is not sufficient: production alias resolution, artifact checksums, rendered-content extraction, and private-path probes jointly establish external deployment verification.
