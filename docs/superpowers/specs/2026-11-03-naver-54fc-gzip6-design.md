# Fixed 54fc gzip-6 cold-backup profile

## Decision and scope

Add exactly `54fc-cold-backup-lossless-gzip6-v1` for the completed deployment's
cold copy `20261103T012239Z-54fcf985d9f5`. The immutable archive name is that
source name plus `-gzip6-v1`; the confirmation is
`ARCHIVE_54FC_COLD_BACKUP_GZIP6_LOSSLESSLY`. Compression level is fixed at 6.
No path, timestamp, commit or compression level becomes user-selectable.

The coordinating agent selected this bounded implementation under the existing
normalization and preservation authorization. This change prepares code, tests
and a PR only. Merge and actual PLAN/APPLY require the coordinator's next action.
The source raw copy and all existing archives remain untouched by development.

## Unchanged contracts

- Keep all five existing profiles for four older backups byte-for-byte, including
  four gzip-1 profiles and the d633 gzip-6 alternative, with their existing
  version-1 manifests, receipts, isolated restore and legacy default CLI.
- Reuse existing profile-bound source/archive/level plan hashes, exact confirmation,
  full byte decompression verification, original manifest preservation, exclusive
  publication, source identity rechecks and publication-before-source-removal.
- Preserve owner/main/first-attempt/host-pin gates and the same global flock.
- Preserve 5 GiB final free space, 512 MiB working reserve, 600-second cooperative
  time budget, size caps and protection of every container and image identity.
- No new cleanup scope beyond this one fixed cold source; no regular backup,
  archive recompression, offsite transfer, restore CLI, SQLite or service action.

## Evidence and uncertainty

Deployment run `41557056268` recorded this exact cold-copy path while replacing
54fc with fb70. That receipt does not establish the copy's current byte count,
manifest hash, gzip size or runtime. The new scope's PLAN must measure those
facts under the unchanged gates before any capacity conclusion. A successful
PLAN also does not prove APPLY can finish: APPLY measures, writes and fully
verifies within the same 600-second budget. Existing copies are not deleted to
make a failing projection pass. No capacity or backup recovery success is
claimed from these synthetic tests.

## Verification

Run every existing per-profile restoration, corruption, interruption, ownership,
identity, capacity and no-change test for the new fixed profile. Verify exact
constants, every other profile's confirmation rejection, immutable legacy
profiles and unchanged operational functions. Run isolated networkless Linux,
workflow gates and secret scans; obtain exact PR CI before operational use.
