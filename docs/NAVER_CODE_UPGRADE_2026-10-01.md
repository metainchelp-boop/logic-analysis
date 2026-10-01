# Approved code-only Naver upgrade

Approval: 2026-10-01, source `7422fac362dc6cafcfe6ffface4d00d0f2820665`
to target `f7eb2e58aafad81e27978f175d83cca0eb5c5733`, engine/relay only.
This is a separate contract. The original bootstrap upgrade and its OLD_COMMIT
guard are unchanged. No branch-wide application deployment is authorized here.

## Dispatch contract

Workflow: `.github/workflows/debug-rank.yml`, ref
`codex/ad-deploy-prep-20261001`. All unrelated inputs must be `off`.

1. `ad_prepare=preview-code-prepare`: `ad_expected_baseline` is the existing
   encrypted-download package: baseline, source_commit, ciphertext_sha256,
   source_tar_gz_sha256, artifact_sha256, download_url. The target must be the
   exact approved commit. The runner adds its own run_id and operation
   `code-prepare`; plaintext never leaves the destination server.
2. `ad_prepare=preview-code-upgrade`: `ad_expected_baseline` is exactly
   `{ "release": { "baseline": "...", "source_commit": "f7eb2e58aafad81e27978f175d83cca0eb5c5733",
   "ciphertext_sha256": "...", "source_tar_gz_sha256": "...",
   "run_id": "PREPARE_RUN_ID", "operation": "code-prepare" },
   "operation_id": "UNIQUE_32_LOWERCASE_HEX" }`.
   No request, hold or approval fields are accepted.

## Preserved boundaries

- Current source manifest, image IDs/source labels/nonroot user, exact systemd
  units, active/enabled state and legacy host baseline must match before writes.
- Secrets/env are compared byte-for-byte and never rewritten. Compose,
  Dockerfiles, requirements, bootstrap implementation and schema definitions/
  version/migration AST must be identical. Only image source and unit paths move.
- Existing bootstrap request and its started/terminal result receipts are read
  and compared only. An uncompleted existing request refuses deployment. Missing
  request stays missing. The unchanged runtime safely refuses expired requests
  or reports already_started; neither is a new approval or bootstrap execution.
- Controller never opens or rewrites the runtime DB. Existing business decisions,
  keys, nginx, ERP tunnel and three legacy applications are not modified. Normal
  approved scheduler writes after startup are not frozen by deployment.
- Target and restored old code must pass socket health, page/security headers,
  unauthenticated read 401, business POST 403, container identity/image and
  active/enabled unit checks. Health alone is not collection completion.

## Rollback and compatibility

Before stopping, persist exact old unit bodies and image IDs in a new private
`receipts/code-upgrade-<operation_id>.json`. On failure stop only engine/relay,
restore those exact units and validated 7422fac images, then run the same
readiness/security checks. Any rollback inconsistency leaves both services
stopped with CODE_ROLLBACK_FAILED; never repair bootstrap or database state.

7422fac and f7eb2e5 share schema version 7, schema SQL and migration logic. New
matching reason strings occupy existing TEXT/JSON fields. Old code can reopen
that database; after rollback it does not understand the new ERP ad-account-ID
input and therefore cannot newly regenerate those automatic matches.

Code-only apply has a separate 60-minute SSH / 65-minute job budget, covering
serial bounded preflight, forward operations and rollback (all individual
commands retain their 45/90-second bounds). Preparation has 35/40 minutes for
two individually bounded 600-second image builds and checks. Original route
timeouts remain 12/15 and 15/20 minutes. The concurrency group stays unchanged.

Validation here is synthetic/local only. Operating dispatch and independent
post-deployment preview-status/collection-status are the release owner's task.
