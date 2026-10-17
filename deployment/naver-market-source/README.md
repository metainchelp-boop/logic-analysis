# Saved search sample export — uninstalled Task06 templates

These files are review material. They install no timer, mount no database, call
no source API, and restart no service. Task12 resolves the actual production
profile and verifies real coverage. All accompanying tests use synthetic data.

The standard-library CLI `backend/naver_market_export.py` opens the existing
source SQLite file with `mode=ro`, `query_only`, an allowlisted column authorizer
and a single read transaction. It imports only the reviewed sibling
`naver_product_export.py`, by exact path, and works with `python -I`. Install both
scripts in the same root-owned, non-writable exporter directory. It never
imports or initializes the application, repairs schema, crawls, calls an AI/API,
or writes the source database. Existing product exports are unchanged.

## Linkage and evidence

The source must contain the current `clients`, `client_keyword_product`,
`client_keyword_mute`, `collector_observations` and `collected_serp` tables.
Unique canonical advertiser/store clients are linked through their current
comma-separated `main_keywords`, excluding exact muted keywords. An explicit
keyword product assignment must be an exact same-store product; an invalid
assignment never falls back to another product. Without an assignment, only an
exact product base URL can supply that product. Duplicate store clients or
contradictory assignments are ambiguous. Names, bare numeric IDs, historical
analyses and tracking-table guesses never establish current ownership.

Only the newest observation for each assigned keyword is considered. A newer
partial, failed, legacy, malformed, stale or unorderable observation blocks
fallback to an older complete observation for that keyword. A different current
assigned keyword can supply its own newest valid sample; one cohort per store is
chosen deterministically by received time, capture-end time, keyword and UUID.

An eligible observation has complete/full/COMPLETE status, a valid UUID, exact
keyword, aware start/end timestamps, a coherent count/page/source envelope and
sequential, unique raw sample positions. Each retained result needs a valid
HTTP/HTTPS URL, with no credentials or non-default port. URL identity is hashed;
it does not establish product ownership, and raw names/URLs/IDs are not exported.
Exact supported store/product URLs use canonical product identity with tracking
queries/fragments removed, so the same product cannot be counted twice that way.
Other links retain validated path/query semantics and identify result items,
not confirmed distinct products.
The search page evidence must identify the same keyword on the saved Naver
shopping search surface. Device, region and filters remain unknown. The source
producer can mark a configured page cap complete; this never means full market
coverage. Pages with no retained sample are conservatively unverified here.

The original ledger payload hash must be reproducible from the *same*
`collected_serp` observation, products, metadata and total. Ledger rows alone
lack total, so no substitute total, same-day unrelated observation, or older
snapshot can repair missing proof. Only positive integer numeric price strings
become listed sample prices; zero, missing, formatted/estimated or invalid
prices remain null. Reviews, ratings, search volumes, DataLab ratios, market
revenue, ad strength, AI narratives and ad/organic ranks are not exported.
Sample prices do not confirm common units, options, delivery or coupons, and
cannot prove own-price advantage, industry demand, market share, competitor ad
budgets or the cause of past ad performance.

## Time and bounds

`observed_at` is the producer-reported capture end, not independently verified
capture time. `recorded_at` is server received time; existing naive SQLite
timestamps are explicitly interpreted as Asia/Seoul. Capture duration is at most
24 hours, receive time can precede capture end by at most five minutes and lag it
by at most 24 hours, and both must be within 72 hours of export. Future slack is
five minutes. The engine additionally limits bundle reuse to 30 hours. These
are engineering reuse windows for next-plan samples, not live freshness or
full-market evidence. An outbox receive/save date cannot replace capture time.

Bounds: 10,000 clients, 100,000 total visited rows, 2 MiB per selected JSON cell,
32 MiB cumulative input, 5 MiB output, 1,000 rows per cohort and 30 seconds inside
the exporter. The service adds a 45-second deadline and 256 MiB memory limit.
Oversized input or output fails; no truncated bundle is published.

Publication uses a mode-0640 temporary file, file fsync and atomic replacement.
Failure before replacement preserves the previous file. Replacement is the
publish commit point; a subsequent directory fsync failure leaves the complete
new file visible and returns `ok` with `EXPORT_DURABILITY_UNCONFIRMED`. It does
not claim rollback or confirmed crash durability. A failed export does not
refresh `exported_at`. Logs contain only fixed codes/counts, not raw exceptions,
source rows, source paths or customer text.

## Task12 installation and live verification

Resolve `@EXPORTER_USER@`, `@EXPORT_READER_GROUP@`, `@LOGIC_READ_GROUP@`,
`@PYTHON_EXECUTABLE@`, `@EXPORTER_DIRECTORY@`, `@LOGIC_DATABASE@`,
`@LOGIC_DATA_DIRECTORY@`, `@MARKET_EXPORT_DIRECTORY@`, and `@ENGINE_SERVICE@`
against the approved deployment profile. All paths must be absolute and
correctly quoted/escaped for systemd/YAML. ProtectHome requires installed script
and data paths outside protected home directories. Do not weaken source
read-only access if WAL/SHM permissions prevent a consistent read. Never use
`immutable=1`, copy a potentially inconsistent live DB, or mount the full DB in
the engine as a workaround.

Use a separate export-only directory, mode 0750, owned by the exporter and the
engine's numeric reader group. Bind that *directory* read only at
`/var/lib/naver-market-source`, so atomic replacements are visible. A single-file
inode mount can remain on old data. Confirm group access; the directory contains
only its bundle and temporary export files. The engine override is
`NAVER_ENGINE_MARKET_EXPORT_FILE`, a file path only. Preserve every existing
service environment and mount.

The proposed 10:35 KST timer is not installed. Verify real collection completion,
source permissions/WAL behavior, exact current product/keyword linkage and
actual valid/invalid/no-observation coverage before activation. Verify DB bytes
and mtime unchanged, no raw payload or private identities in the export, the
engine's missing/invalid/stale invalidation, and failure monitoring. Source
coverage and AI quality remain live Task12 checks, separate from synthetic CI.
