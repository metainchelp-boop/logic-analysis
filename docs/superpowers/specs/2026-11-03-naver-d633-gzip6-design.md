# Fixed d633 gzip-6 archival profile

## Decision and scope

Add one explicit `d633-cold-backup-lossless-gzip6-v1` profile for the already
allowlisted d633 cold backup. Its source is unchanged, its destination ends in
`-gzip6-v1`, and its confirmation is
`ARCHIVE_D633_COLD_BACKUP_GZIP6_LOSSLESSLY`. There is no user-selectable compression
level or path. This is an alternative preservation format, not an additional
deletion target. Existing backups, archives, services, images and live data are
outside the change.

Changing the existing profile's level would invalidate its established manifest
contract. Allowing arbitrary levels would widen the operational interface.
A separate immutable profile instead makes both the selected level and the
source/destination identity part of the existing canonical plan hash.

## Compatibility and refusal boundaries

- Keep all four existing profiles, their level 1, version-1 manifest/receipt
  shapes, confirmation phrases and the legacy three-argument c44 CLI unchanged.
- Bind `gzip.level` to the exact selected profile. Do not accept both levels for
  every profile. Plan measurement and APPLY writing use that same fixed level.
- Keep gzip filename empty and mtime zero; retain compressed and original sizes
  and SHA-256 values, Python/zlib versions, source identity and protected state.
- For both d633 profiles, refuse PLAN and APPLY if either alternative archive
  directory exists, including an incomplete one. Check before measurement and
  again before creating a new archive, under the existing global flock. Do not
  read, overwrite or delete the conflicting archive. Restore is independent of
  this mutual exclusion and continues to accept its exact receipt-bound scope.
- Keep exact decompression verification, publication-before-source-unlink,
  original manifest preservation, bounded members, metadata restoration and
  every existing path/identity/snapshot check.
- Keep the 5 GiB projected and actual free-space requirement, 512 MiB reserve,
  source/archive size caps, 600-second cooperative budget and nice level 19.
  No retry, new deletion scope, service action or production restore command.

## Feasibility is not established by implementation

Compression savings depend on the cold source bytes and must be measured by a
new scope-bound PLAN. A successful PLAN does not guarantee APPLY finishes within
600 seconds: APPLY repeats compression measurement, writes compression, and fully
decompresses it. The same budget spans all stages. Chunk-boundary checks cannot
interrupt blocking kernel I/O; SSH/runner timeouts do not prove server-process
termination. Timeout leaves the existing preservation/refusal state intact.

## Implementation and verification sequence

1. Extend only fixed profile data, profile-bound compression/manifest checks,
   sibling destination checks, workflow choice/confirmation and documentation.
2. Preserve the existing per-profile suite and run it for the new profile. Add
   legacy gzip-1 restore, exact-level/type rejection, cross-profile hashes,
   conflicting partial/published archives, late conflicts, corruption and
   staged timeout preservation checks.
3. Run local and isolated Linux focused tests, workflow/source guards and secret
   scans. Push the owner branch and open a draft PR for exact full tools CI.
4. Merge and production PLAN/APPLY remain the coordinating owner's work. No
   implementation or synthetic result is a capacity or production recovery claim.

The coordinating agent selected this implementation under the representative's
existing normalization and preservation authorization. This does not claim a
separate representative approval of the gzip-6 design.
