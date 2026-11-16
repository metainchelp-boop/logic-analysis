# Fixed fb70 cold-backup profile

## Decision and scope

Add only `fb70-cold-backup-lossless-v1` for the completed deployment's cold copy
`20261103T081036Z-fb70e6d2ef90`. The fixed archive name is the source name plus
`-v1`; confirmation is `ARCHIVE_FB70_COLD_BACKUP_LOSSLESSLY`. Gzip level 1 uses
the existing original-profile behavior to reduce compression work within the
unchanged deadline. No path, timestamp, commit or compression level becomes an
input, and no gzip-6 alternative is added for this source.

This is preparatory development for the monitoring-only release. Actual PLAN
and APPLY remain separate operations after source, capacity and review evidence.
Development does not read or change the production source or existing archives.

## Unchanged contracts

- Keep all six prior profiles for five backups, the c44 CLI default, existing
  version-1 receipts/manifests, archive bytes and isolated restore behavior.
- Preserve source-bound plan hashes, fixed confirmations, complete decompression
  verification, manifest fsync/publication, source rechecks and removal ordering.
- Preserve owner/main/first-attempt/host-pin gates and shared deployment flock.
- Preserve 5 GiB projected/actual free space, 512 MiB reserve, 600-second deadline,
  size caps and unchanged protected container and image identities.
- The bundle helper's hash pin must follow the updated cold helper. Its fixed
  54fc source, regular snapshot, image/source pins and all behavior remain unchanged.
- No general cleanup path, automatic retry, new recovery policy, archive
  recompression, live SQLite access, service mutation or offsite transfer.

## Evidence and limits

Successful deployment run `41599325150` recorded this exact cold copy while
replacing fb70 with 8c13. That receipt establishes provenance, not current source
presence, bytes, manifest identity, compressed size or capacity. A fresh PLAN
must pass unchanged capacity criteria. PLAN success does not prove APPLY fits
the same time budget because APPLY measures, writes and fully decompresses.
The deployment's database/image/source-tar budget is checked separately even
after the archive's final free-space check passes.

## Verification

Run the inherited full preservation, corruption, timeout, ownership, identity,
capacity and restoration suite for fb70. Verify exact seven-profile identities,
all cross-profile confirmations and scope-bound workflow receipt validation.
Run bundle import and recovery regressions with the updated sibling hash pin.
Linux/root-specific restoration checks require the exact reviewed CI commit;
local synthetic results do not establish production backup or deployment success.
