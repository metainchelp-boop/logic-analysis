# Fixed cold NAVER backups: lossless archive and isolated recovery

This helper accepts exactly three reviewed cold-backup profiles. Source and
archive paths are fixed in the helper; neither the workflow nor CLI accepts an
arbitrary path, commit, timestamp or confirmation phrase.

| Workflow scope | Source directory below `/var/backups/metainc/naver-deploy-db/` | Confirmation for APPLY |
| --- | --- | --- |
| `c44-cold-backup-lossless-v1` (default) | `20261102T170022Z-c44a66393340` | `ARCHIVE_C44_COLD_BACKUP_LOSSLESSLY` |
| `a377-cold-backup-lossless-v1` | `20261102T185748Z-a3770876f746` | `ARCHIVE_A377_COLD_BACKUP_LOSSLESSLY` |
| `bb151-cold-backup-lossless-v1` | `20261102T205647Z-bb151c2a483a` | `ARCHIVE_BB151_COLD_BACKUP_LOSSLESSLY` |

The a377 source is the previous-product backup recorded by the successful
bb151c2a deployment, run `41502564117`; it is not the running database. Adding
this profile does not read, remove or overwrite the existing c44 archive.
The bb151 source is the previous-product backup recorded by successful d633
deployment run `41521463521`. Read-only inspect run `41529054879` confirmed d633
remains active and approximately 1.99 GiB is free. The new fixed profile must
still pass its own PLAN and byte-verification gates before any archival action;
it does not read or overwrite either earlier archive.
It never opens SQLite, reads the live engine database, changes containers, or
removes images/volumes. The deployment flock is held throughout. All five
container identities, images, PIDs, start times and restart counts, and the full
image ID set must remain unchanged. A changed snapshot refuses the operation.

Each separate destination is below `/var/backups/metainc/naver-cold-archives/`,
with the exact selected source directory name plus `-v1`.
Its parent and directory are root-owned mode `0700`; files are mode `0600`.
The destination is never overwritten or automatically pruned. Only the chosen
profile's source files may be removed, after the verified archive is published.

## Profile selection and compatibility

Use the manual workflow on main with the required `scope` choice and mode
`plan`. Then select that same scope for `apply`, using its returned plan hash
and its own confirmation from the table. Actor, triggering actor, first attempt,
trusted host fingerprint and the shared deployment lock gates are unchanged.
The closed receipt is validated against the requested scope before publication.

The helper CLI adds an optional fourth scope argument:

```sh
python3 -I -B cold_backup_archive.py plan '' '' a377-cold-backup-lossless-v1
python3 -I -B cold_backup_archive.py apply PLAN_SHA256 ARCHIVE_A377_COLD_BACKUP_LOSSLESSLY a377-cold-backup-lossless-v1
```

These are operator examples, not a request to run a production operation.
Existing three-argument CLI calls retain the c44 default. Existing version-1
c44 manifests and receipts remain valid; no existing archive is rewritten.
All plan hashes include the fixed scope, backup and archive names along with
source identity and protected state. A plan or confirmation for one profile cannot
authorize another profile's APPLY. Unsupported scope strings are refused without
printing the supplied value. Even identical source bytes do not make plans
interchangeable.

## Format and publication

- Each original manifest member (`engine.db` and only its listed `-wal`, `-shm`,
  or `-journal` sidecars) becomes one same-name `.gz` file. Gzip uses level 1,
  an empty filename and timestamp zero. Empty sidecars are retained.
- `source-manifest.json` contains the exact original `manifest.json` bytes,
  including whitespace. Original SHA-256 and size checks must pass first.
- `archive-manifest.json` records both original and compressed SHA-256/size,
  source device/inode/owner/group/mode/link count/mtime/ctime/allocated bytes,
  the original directory and manifest metadata, compression version, fixed
  source/destination identity and the protected container/image snapshot.
  The closed receipt includes its SHA-256; retain that receipt separately.

PLAN only streams the cold source into a gzip counting/hash sink. It creates no
archive. APPLY repeats that measurement and requires the same plan hash before
writing. It reserves the exact compressed size plus 1 MiB overhead and 512 MiB
headroom, and requires at least 5 GiB projected free space after cleanup.
Allocated source blocks, rather than apparent length, are used for this estimate.
The final actual free space is checked again; 5 GiB is a deployment prerequisite,
not a substitute for the deployer's current database/image/source-tar budget.

Every compressed file is fsynced, fully decompressed in bounded chunks and
checked against the original SHA-256 and size. Trailing gzip members, garbage,
truncation and decompression expansion beyond the expected size are rejected.
The original manifest and pending archive manifest are also fsynced. An
exclusive hard link publishes `archive-manifest.json` as the atomic completion
marker, then the pending link is removed and the directory fsynced. Original
copied files are unlinked only after publication, byte verification and a final
source identity check. Each source descriptor is immediately closed so its
blocks are released before measuring free space. No live database path is used.

This helper runs at CPU nice level 19 with a 600-second cooperative deadline.
The workflow also has a hard execution timeout. A timeout is never retried
automatically. Kernel I/O may not return before a cooperative deadline.

## Isolated restore exercise

There is no workflow or CLI `restore` mode. The following callable recovery
exercise accepts only a newly created `restore-check-<16 hex digits>` child of
an existing private directory, never overwrites a file, and refuses common
production data roots and symlink ancestors. Run it as root in an isolated Linux
recovery environment with enough space for all original bytes. The reviewed
helper and archive must already be present; this example performs no transfer.
The second argument must be the **archive_manifest_sha256 from the saved closed
APPLY receipt**, not a newly calculated hash of an untrusted archive.

```sh
install -d -m 0700 /root/naver-restore-exercise
python3 -I -B - /root/reviewed-tools/cold_backup_archive.py RECEIPT_ARCHIVE_MANIFEST_SHA256 <<'PY'
import importlib.util
import sys

spec = importlib.util.spec_from_file_location('cold_archive', sys.argv[1])
archive = importlib.util.module_from_spec(spec)
spec.loader.exec_module(archive)
archive.restore_isolated(
    '/var/backups/metainc/naver-cold-archives/20261102T170022Z-c44a66393340-v1',
    '/root/naver-restore-exercise',
    'restore-check-0123456789abcdef',
    sys.argv[2],
)
PY
```

The example above retains the original c44 default. For an a377 isolated
exercise, use archive directory
`/var/backups/metainc/naver-cold-archives/20261102T185748Z-a3770876f746-v1`,
the a377 APPLY receipt hash, and pass
`scope='a377-cold-backup-lossless-v1'` to `restore_isolated`. A different
expected scope, or a manifest mixing one scope with the other's source/archive
name, is refused before creating the restore target. The caller-provided archive
location permits an isolated copied archive; it does not relax the fixed
manifest identity or receipt hash requirement.

Before creating the target, restore verifies the receipt-bound archive manifest,
its closed metadata types/allowlist, the verbatim original manifest, and every
gzip's compressed and uncompressed hash/size. After extraction it restores each
file's original UID/GID, mode and nanosecond mtime, the original manifest bytes
and metadata, and the original directory UID/GID/mode/mtime. Original inode,
device, ctime and physical block allocation cannot be reproduced and remain
audit metadata only. Access time, ACLs and extended attributes are not part of
this format. Restoration preserves physical database and sidecar bytes; it does
not establish SQLite logical integrity or start an application.

The existing deployer's automatic rollback restores code, units and previous
images. It does **not** read this archive or restore database bytes. Promoting a
recovered database into production remains a separate, explicitly scoped
recovery operation with the services stopped and compatibility verified.

## Interrupted runs

- Before the archive completion marker is published, all original source files
  remain. An incomplete archive directory is retained for review, not erased.
- After publication, the complete verified archive remains even if original
  cleanup fails halfway. The receipt reports cleanup progress separately.
- A crash may leave both pending and published manifest links or a partially
  removed source directory. Do not rerun blindly: retain both copies, verify the
  archive against the saved plan/receipt and inspect the exact remaining files.
  The helper refuses an existing archive; it does not automatically finalize or
  delete interrupted artifacts. A lost receipt after publication requires
  independently establishing the archive manifest hash before recovery.
- A completed archive with less than 5 GiB actual free space is reported as
  `SPACE_REFUSED`, while its successful preservation/cleanup fields remain
  visible. Do not lower the guard or skip the next deployment backup.

Synthetic tests cover full byte/metadata recovery, manifest preservation,
corruption and gzip bombs/trailing members, source drift, symlink/hardlink
refusal, interrupted publication/cleanup, file descriptor release, plan and
confirmation gates, snapshot changes, capacity refusal and restore no-overwrite
for both profiles. They also cover cross-profile plan/confirmation/restore
refusal, legacy c44 CLI compatibility, receipt scope binding, and preservation
of the other profile's source and archive bytes/metadata.
They do not constitute a restore test of the production database.
