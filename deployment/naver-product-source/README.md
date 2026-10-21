# Saved product export: undeployed Task05 templates

These files are review material. They do not modify the existing application,
install or activate a timer, mount a database, or restart a container. Task12
resolves the production profile, paths, service identity, permissions and release
baseline before installation and live verification.

`backend/naver_product_export.py` is a standalone standard-library CLI. It opens
the existing source SQLite database with `mode=ro`, `query_only` and one read
transaction, reads only allowlisted saved fields, then atomically replaces a
dedicated JSON bundle. It never imports the application, repairs schema,
collects pages, calls an AI/API, or writes the source database.

## Files and placeholder contract

| Template | Purpose |
| --- | --- |
| `naver-product-export.service.in` | Isolated exporter, source directory read only, export directory writable |
| `naver-product-export.timer` | Proposed daily 10:30 KST run; not an installed schedule |
| `compose.readonly-export.yml.in` | Add only the export directory to the existing engine, read only |

Resolve `@EXPORTER_USER@`, `@EXPORT_READER_GROUP@`, `@LOGIC_READ_GROUP@`,
`@PYTHON_EXECUTABLE@`, `@EXPORTER_SCRIPT@`, `@LOGIC_DATABASE@`,
`@LOGIC_DATA_DIRECTORY@`, `@EXPORT_DIRECTORY@`, and `@ENGINE_SERVICE@` from the
actual reviewed deployment profile. Paths must be absolute; quote/escape them
for systemd and YAML when substituting. With `ProtectHome=true`, installed
script/data paths must be outside protected home directories. The script must
be root-owned and not writable by the exporter. The engine service name and
existing environment/volumes remain those of the current production profile.

The dedicated exporter identity needs read access to the existing SQLite DB and
any existing `-wal`/`-shm` files. It has no source write access. The export
directory is created separately by deployment, mode `0750`, owned by the
exporter with the engine's numeric reader group; each bundle is `0640`. Confirm
the container actually has that group/read access. Do not grant the engine
access to the source database, its data directory, contacts, notes or HTML.
The export directory must contain only this bundle and temporary export files.

The engine reads `/var/lib/naver-product-source/bundle.json` by default. Its
`NAVER_ENGINE_PRODUCT_EXPORT_FILE` override changes a file path only, not the
source identity or access rules. The engine binds the dedicated host export
directory at `/var/lib/naver-product-source` with `read_only: true` and
`create_host_path: false`. Mount the directory so atomic file replacement is
visible; mounting a single bundle inode can leave the container on old data.

SQLite WAL mode requires the existing WAL/SHM files to be readable and compatible
with read-only access. If the host profile cannot provide that, the exporter
fails and retains the previous bundle. Do not add `immutable=1`, enable source
writes, copy a potentially inconsistent live database, or mount the whole DB in
the engine as a workaround.

## Bounds and failure behavior

The default limits are 10,000 candidate clients, 100,000 total visited rows,
2 MiB per selected JSON cell, 32 MiB cumulative input, 5 MiB output and 30 seconds
inside the exporter. The service adds a 45-second deadline and 256 MiB memory
bound. It selects up to three exact products per unique canonical store.
Duplicate store clients are `ambiguous`; unknown data stays null. No partial or
truncated bundle replaces a complete one. Failures before the atomic replace
leave the previous bundle unchanged, and temporary files are removed.
The successful atomic replace is the publish commit point. If directory fsync
fails afterwards, the complete new file is already visible; the CLI returns
`status: ok` with fixed warning `EXPORT_DURABILITY_UNCONFIRMED`. It does not
claim a rollback or confirmed crash durability. Monitor that warning separately
from a failed export. Process termination or host power loss at this boundary
also cannot be described as guaranteed previous-file retention.
CLI output contains only counts or fixed failure codes, never source rows,
paths, customer text, contact information or raw exception messages.

Task12 must verify the existing daily analysis completion time before activating
the proposed timer. A successful timer refresh is an export of cached saved
analysis, not a fresh page collection. A failed run does not refresh
`exported_at`; the engine limits export age to 30 hours and saved product age to
14 days, and must hide ready facts on missing/invalid/currently stale source.

`recorded_at` is the analysis save time; legacy naive source times are KST.
`observed_at` is always null because the original capture time is unconfirmed.
Detected delivery/return/gift/certification sections mean only that the stored
page contains a section, not that any service, benefit or certification is
verified. Estimated/AI metrics are not exported as observations, and a
review-sample rating remains explicitly a sample source.

## Required Task12 verification

Verify exact source role/store/product linkage, source permission and WAL
behavior; export a bounded bundle; confirm source DB contents/mtime unchanged;
confirm only the dedicated directory is mounted read only; confirm the engine
accepts the actual bundle and invalidates missing/invalid/stale inputs; verify
the daily job's output time and failure monitoring. Keep these live checks
separate from the synthetic tests that accompany Task05. No real source data or
deployment has been used to validate these templates.
