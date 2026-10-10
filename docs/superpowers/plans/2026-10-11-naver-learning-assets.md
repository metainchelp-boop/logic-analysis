# Naver learning assets — local implementation, 2026-10-11

## Authorized outcome
Enhance the existing data learning center with performance, configuration-change, and A/B evidence assets; make vetted assets available to Claude marketing drafts. Existing store insights stay intact. No production deployment, real advertising executor, or paid activation is part of this verified result.

## Boundaries
The logic-analysis application links to the published Naver automation entry with tab=learning. It does not pass its JWT, customer ID, or guessed company-name mapping. Naver resolves its own authenticated account scope. The viewer role receives no management entry.

Learning assets use additive keys in the existing naver_auto_meta table. Each save/review/reject appends an immutable version and updates its head with optimistic concurrency. Manual writes cannot forge source_refs, reserve report-/plan- identifiers, or modify imported source documents. The current UI shows heads; full historical versions remain stored, without a dedicated historical comparison screen yet.

## Capture
New stored reports automatically produce per-account performance observations. A failed learning capture rolls back its own savepoint and marks a retry as pending without discarding the report. Manual report import considers at most the most recent 100 report rows for the selected advertiser. It does not claim a completed production backfill. Missing metrics remain null; actual zero remains zero. Automatic report observations use platform conversion semantics and do not assert purchase completion or mature conversion lag.

Plan saves and approvals produce setting-change records marked planned. Approval does not imply a Naver setting was applied. Manual observed/applied records are staff-supplied evidence; this release does not independently collect live configuration changes.

## A/B assessment
Server assessment requires immutable preregistration before the start date, fixed horizon, stable protocol, randomization, independent observation units, one changed variable, measurement completion, mature lag, allocation validity, and adequate power/sample size. CTR/CVR use confidence intervals and a meaningful difference threshold. CPA/ROAS totals without variance/event detail cannot yield a winner. Stopped, invalid and inconclusive cases remain useful negative evidence. Staff checkboxes are attestations, not independently verified Naver allocation logs.

## Claude input, provenance and approval
Only reviewed cases enter retrieval. Own-account evidence is preferred. Cross-advertiser evidence is considered only within the caller's current permitted account pairs, with known matching industry, goal and advertising type; budget band ranks relevance. At most five cases are used. Own retrieval considers up to 500 heads; cross retrieval is bounded at 1,000 candidates. Company names, account IDs, free-text notes and source references do not go to the model. Metadata is currently entered on manual cases; imported immutable reports are not automatically industry classified.

The request includes numeric performance, current bounded operating-plan fields, typed evidence and server outcomes. The strategy stores its exact report revision, plan version and case versions. Auth and inputs are rechecked before reservation and after generation. Changed inputs prevent saving. Changed referenced cases/plan suspend the previously approved strategy's shared output until regeneration. Generated drafts still require staff review/approval before report sharing.

## Provider activation
Default disabled. Runtime configuration requires NAVER_CLAUDE_ENABLED=true; ANTHROPIC_API_KEY or CLAUDE_API_KEY; CLAUDE_MODEL or ANTHROPIC_MODEL; NAVER_CLAUDE_MONTHLY_CAP_USD; NAVER_CLAUDE_INPUT_USD_PER_MILLION; NAVER_CLAUDE_OUTPUT_USD_PER_MILLION. Optional NAVER_CLAUDE_TIMEOUT_SECONDS defaults to 10, range 1–20. There is no guessed model or price. Do not put secrets in source or output files.

HTTPS endpoint is fixed to api.anthropic.com/v1/messages, with bounded I/O and no automatic retry. Timeout is a socket timeout, not an absolute end-to-end job deadline. Conservative per-call worst-case reservations are persisted against a KST monthly cap. Failed or stale calls retain their reservation; this is not measured invoiced usage. No real API key or paid call was used for local verification.

## Delivery and activation sequence
1. Review the local implementation and synthetic screen/test evidence in the HTML briefing.
2. Deploy both application changes through their existing approved operational paths.
3. Configure the API model, current unit prices and an agreed monthly cap using the server secret configuration.
4. Verify scoped login, report capture and one bounded real generation; inspect actual model output and usage.
5. Build live setting/experiment collection and an execution adapter separately before enabling any bounded automatic advertising operation.
