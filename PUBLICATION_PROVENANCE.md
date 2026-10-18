# Publication provenance boundary

## Supported contract

The installed Hermes `web_extract` result retains its existing public fields.
It may add only these bounded optional records (not arbitrary vendor metadata):

```json
{
  "publication": {
    "version": 1,
    "basis": "provider_reported",
    "provider": "keenable",
    "field": "published_at",
    "value": "2026-10-14T12:21:33Z",
    "precision": "second"
  },
  "extraction_location": {
    "version": 1,
    "requested_url": "https://example.com/requested",
    "returned_url": "https://www.example.com/returned"
  }
}
```

Version 1 preserves only Keenable's integer Unix-seconds `published_at`, bounded
from 2000 through 2099. Strings, booleans, floats, nonfinite values, negative/zero
values and millisecond epochs are not coerced. Normalization preserves the
instant as UTC; the original epoch has no timezone offset to preserve.
Generic `published_at`, crawl/cache/request/event/copyright dates and
`dateModified` are not promoted to this contract. Malformed typed extensions
fail closed at projection, worker and validator boundaries.

A provider report is **not independently authenticated publisher metadata**.
It is carried through the lower extraction cache, real supervised worker,
strict validator, focused capture and upper source cache for provenance, not
copied to evidence `published_at`. It cannot make an undated, stale, future,
insubstantial, error or challenge page eligible. Adding domains to an allowlist
would not solve this authority problem, and no domain allowlist was added.

## Acceptance

Evidence still requires the existing supported publication text/HTML semantics,
substantive body, freshness and safe exact-request binding. The strict adapter
rejects a provider report that contradicts an independently parsed article
publication day/instant. A visible day is a day-only value, not an assertion
that publication occurred at midnight; adapter pages annotate
`publication_precision` as `day` or `second`. Exact timezone-bearing timestamps
are retained, including real midnight instants. Day comparisons are conservative
and may reject a valid cross-timezone/day-boundary disagreement rather than guess.

The generic visible-label parser stops at explicit related/recommendation
section headings, including whole-label Markdown bold/emphasis, links, trailing
colons and their combinations. Ordinary reporting prose mentioning related
stories is not a section boundary. It does not treat trailing related-story labels or tool
spill footers as current-article provenance. This is not a general redesign of
all pre-existing raw-HTML metadata extraction heuristics.

Existing exact SEC accession/CIK/primary-document filing-date enrichment remains
unchanged. Existing future-date rejection, Reuters final-location guard and
hard two-distinct-registered-domain gate remain unchanged. A retained provider
report is not candidate qualification or a trade signal.

## Cache and focused reuse

New lower-cache records retain requested and returned URLs separately. The
returned location is not rebound to its lookup key. Provider and format remain
part of the cache key and TTL does not slide. Legacy entries have no publication
report/location attestation: they remain unknown, with the existing request-local
Reuters refetch guard preserved. No global cache disabling is used.

Each new lower-cache write uses an exclusively created immutable body generation
and SHA-256, then atomically replaces the index with the matching body path and
provenance. Independent writers cannot overwrite one another's body. Index merges
can still lose an unrelated concurrent insert (a cache miss, not mixed provenance).
Malformed present typed fields, digest failures, identity contradictions and older
typed entries without an integrity digest are misses/refetches, never silently
converted to legacy entries. Truly old entries with absent extensions remain
compatible only under their exact requested URL and fixed TTL.

Writers do not unlink superseded/orphan generations: another process may hold a
previous index snapshot. Disk retention/cleanup is separate from the cache
transaction; an externally removed file yields a miss. This repair adds no eager
generation collector and does not change the configured retention policy.

Focused receipts bind multi-URL redirects only using the validated explicit
requested location, never result order. Contradictory/malformed new provenance
disables optional reuse. The receipt channel remains process provenance, not a
sandbox against same-UID actors. Provider-only dates cannot make a focused page
eligible for zero-fetch evidence reuse; existing quality/freshness checks decide.

## Remaining authority blocker

The real Kalkine and Business Wire provider seconds match separately observed
publisher `datePublished` and visible headers for the original exact articles.
Those browser observations are scratch probe evidence, not a permanent runtime
attestation for all future articles. The configured extraction response contains
no independent publisher corroboration. Consequently these two pages remain
undated for automatic acceptance after this preservation-only repair. A future
acceptance change needs a separately reviewed exact-article publisher-corroboration
path; do not relabel vendor data as publisher-verified or hardcode these URLs.
