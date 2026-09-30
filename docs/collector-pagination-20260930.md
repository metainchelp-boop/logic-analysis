# Pagination correctness candidate

Baseline: main `60864fbe3231bb7f150d9994a2c041c808c888ad`, extension 1.27.0.
The user approved implementing the scoped recommendations from the September 30 diagnosis.

## Accepted behavior

1. Match responses to the requested keyword, page, default search scope and transition time. Reject unrelated, stale and unsuccessful responses. Keep a checked router transition fallback for normal cached SPA navigation.
2. Dispatch one pagination click, then wait for verified data. Do not click a covered target or repeat a click just because a transition takes more than 200 ms. An unverified “next” group jump is not a page number.
3. Preserve confirmed positive ranks after interruption. Insufficient depth or a malformed observation must never assert that an unseen product is outside the requested rank depth.
4. Record pages attempted separately from pages successfully read. Site restriction/authentication signals stop collection; no CAPTCHA, rate-limit or access-control bypass.

## Work and gates

- Reproduce each defect using the actual reader/navigation/observation functions with fake browser/network boundaries.
- Fix capture, reader, navigation and backend validation in bounded vertical slices.
- Run regression suites and isolated browser fixtures; review the integrated diff.
- Package a candidate with hashes, compatibility notes and a Windows acceptance checklist.

No production deployment, settings/DB changes, new traffic to shopping endpoints or extension replacement is authorized by this implementation task. Offline checks do not establish live Windows operation or a guaranteed collection deadline. Short pages without explicit end-of-results proof remain partial.

## Candidate result: 1.28.0-rc1

- Passive capture now recognizes productName and dates XHR requests at send time; one-shot listeners prevent duplicate records on XHR reuse.
- Reader checks keyword, page, request scope, source, response match, HTTP status and start time. A fresh router transition can be used for cached SPA results. An unchanged SSR object is not a new observation.
- One click is followed by bounded existing polling. A covered target or unknown next-page group is not clicked. No rate/parallelism/page-count increase.
- Page evidence is propagated instead of fabricating a verified source. Unidentified organic rows stop the current page to prevent rank compression.
- Short pages and page limits below requested depth remain partial. Malformed provided envelopes cannot enter the legacy/full path. Missing legacy envelopes retain pre-existing compatibility.
- pagesAttempted includes failed reads. HTTP401/403/418/429 are classified explicitly.

## Verification

- All 16 extension JavaScript test files pass (including the response and click regression suites).
- Nine related backend test files pass: collector_observation, collector_board, done_when_found, codex_port_3, codex_port_4, collector_v2_wire, collector_settings, product_match_identity and rank_guard.
- Isolated Chromium fixture: delayed tap response, cached router transition, restriction, covered button and next-group button. Normal cases yield ranks 1..80 with one pagination click; restricted cases preserve the first 40 only. Every HTTP request is intercepted locally.
- The fixture passes the real extension envelope to Python validate + ingest with an in-memory SQLite ledger. It checks full/positive callback selection and one observation row; it does not exercise the deployed HTTP endpoint or production rank DB.
- Independent review caught unchanged SSR reuse; regression added and fixed. No additional confirmed blocker in the bounded final review. Windows/real-site collection is unverified.

Browser fixture (Playwright must already be available):

```sh
COLLECTOR_TEST_CHANNEL=chrome node collector-extension/tests/pagination_browser.test.cjs
```

Use NODE_PATH for an existing Playwright installation if needed. COLLECTOR_TEST_PYTHON may select a Python runtime. No downloads or runtime installation are performed by this test.

## Remaining acceptance gate

After approval, back up the installed extension folder and pending upload state, apply the backend change through the normal reviewed deployment workflow, and test one Windows machine first. Reuse its existing extension ID/storage; do not remove/reinstall, clear cookies or run old/new collectors simultaneously. Refresh only its collector-owned shopping tab after reload so the new document-start capture is installed.

Use a small approved keyword set whose target is on page 2: compare page/order/source evidence and recorded ranks against a manual view in the same session. Confirm one click per transition, no duplicate rank records after an upload retry, positive-only preservation after interruption, and pagesAttempted including failed page 2. Any restriction must stop the trial. Do not widen rollout or call the candidate ready until this gate passes. Historical records are not rewritten by this patch.
