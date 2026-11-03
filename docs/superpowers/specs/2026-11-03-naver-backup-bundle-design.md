# Fixed NAVER backup preservation bundle

The coordinating agent selected this implementation under the representative's
existing normalization and preservation authorization. Operational dispatch and
merge remain with that agent. This change does not authorize other cleanup.

## Scope and evidence

The fixed sources are the existing 54fc deployment backup and one old regular
backup building directory. Discovery accepts exactly one `.building-xxxxxxxx`
directory with the observed 2026-10-21T15:01:32.360859Z directory mtime, containing
only `snapshot.sqlite` of 2,475,552,768 logical and allocated bytes. Paths are not
caller inputs. Three completed local ZIPs, outgoing backups, state, other cold
archives, services and the live database are protected.

Old age does not establish non-use or SQLite integrity. The immutable live fb70
image and exact producer source hashes, init process generation/namespaces and
fixed backup bind must agree before and after the operation. Current producer
code creates exclusive new temporary directories and does not resume old
building directories. Generation evidence must postdate all candidate times.

All host PID/TID FD tables are inspected twice with a bounded late tail. Every
access mode, O_PATH, every file-backed mapping, and candidate directory FD,
cwd/root reference count as use. Only exact preregistered observer FDs are
excluded. Unknown visibility, permissions, identity, limits or relevant churn
refuse. A finite observation is not a promise about arbitrary future opens.

## Capacity and time

Keep the existing 512MiB working reserve, 5GiB final free-space floor and shared
600-second budget. Neither source alone currently reaches the final floor. Both
compressed archives must be durable and fully verified before any source unlink.
Using previous measurements, temporary gzip must fit within 323,838,245 bytes
while both originals remain; PLAN must measure fresh values. Allocation metadata
is not a guarantee of physical reclaimed bytes. Final actual free is checked.

The prior 54fc PLAN took 256 seconds. APPLY must not discard-compress both inputs
again: it rehashes sources and validates the exact plan, then compresses each
source once, compares compressed hashes/lengths, and fully decompresses both.
The 600-second limit can still refuse this operation and is not extended.

## Closed plan and publication

PLAN first performs metadata-only eligibility and use checks; it then reads only
the two approved source files to measure deterministic gzip6 and raw hashes.
Its bounded, exact-key plan contains fixed scope/version/codec, sizes and hashes,
including source identity and producer-generation hashes. No raw paths, names,
PIDs, customer content or keys are exposed. APPLY requires that exact closed
plan JSON and its SHA-256; it cannot select paths or compression parameters.

An exclusive root-private bundle contains separate deployment and snapshot
subarchives. The deployment subtree retains the original manifest bytes and
existing archive-plan format for old isolated restore compatibility. The
snapshot subtree preserves byte hash, owner, mode and mtime in a new closed
manifest. Its isolated restore proves byte preservation, not database integrity.
Both subarchives are fully decompressed and verified, fsynced, and committed
before the bundle marker is published. Source identity, generation, all-mode
use checks and combined free projection are rechecked before source cleanup.

Unlink only the two exact source files, the original deployment manifest and
their now-empty source directories. Close pinned source FDs before actual free
measurement. Pair cleanup is not filesystem-atomic: crashes or late failures
leave verified archives and remaining sources, with explicit partial facts.
There is no automatic retry, partial-archive deletion or scope expansion.

## Compatibility and implementation

The six existing cold profiles, their CLI, manifests and restore behavior stay
unchanged. A new helper loads the unchanged, exact-hash cold helper from a fixed
sibling and reuses compression, hashing, source verification and archive checks.
The new workflow keeps owner/main/first-attempt/host-pin/global-concurrency gates.

Tests cover all-mode references, PID/TID reuse and observer exceptions; bounded
unknown outcomes; candidate identity changes; both archives verified before any
unlink; corrupted/truncated archives and manifests; partial preservation;
working/final capacity and timeout; old restore compatibility; and closed output.

## Metadata-only limit diagnosis

The first operational PLAN stopped with `PROC_LIMIT` before any completed
reference scan or gzip measurement. That result alone does not identify the
limit or establish source use, non-use or sufficient capacity.

The fixed `diagnose` mode follows the same source metadata, immutable producer
binding and first all-mode reference scan, then rechecks source/protected state
and producer generation. It stops before backup payload reads/hashes, gzip,
archive creation or source cleanup. Existing manifest metadata and pinned public
producer source code are still read; backup payload FDs are opened for metadata
and identity checks. Success is `observed/METADATA_READY`, not a preservation or
capacity result. No arbitrary path, limit or process selector is accepted.

Receipt version 2 adds only `limit_diagnostic`: null or the exact fields `kind`,
`cap`, `observed_lower_bound`. The closed kinds distinguish population, observed
generations, per-task FD table, total FD observations, maps bytes, late
generations and the bounded stat/fdinfo reads. A bounded read reports only the
bytes actually read (at most cap plus one), not an invented full size. Existing
malformed FD-table names or non-bytes maps retain `PROC_LIMIT`, with separate
shape kinds and null bounds. Invalid maps-line grammar retains `PROC_INVALID`.
No paths, PIDs, descriptor numbers, raw data or further /proc reads are added.

PLAN/APPLY execution, source/plan/archive formats and all existing bounds remain
unchanged. A failed diagnosis stays unknown; it never raises a cap or retries.

## Target identity before optional FD flags

The separate diagnostic observed an FD-info read of at least 4,097 bytes against
the unchanged 4,096-byte cap. It did not identify the FD or establish that it was
unrelated to either source; it also cannot retroactively identify the first
PLAN's exact limit.

Every PID/TID FD is still compared by device/inode. An unrelated FD needs no
access-mode decision, so its additional FD-info is not read. Any target FD with
no exact registered observer identity is immediately a reference in every mode,
including read-only and O_PATH. Only the exact observer tuple and full metadata
may proceed to the existing bounded flags read, followed by the original second
metadata-plus-flags observation. Missing, changed, malformed or over-limit
observer evidence still refuses. All maps, cwd/root, process generations,
two passes, late observations, ceilings and time/space guards remain unchanged.

## Closed unavailable-observation diagnostics

Receipt version 3 adds only `proc_diagnostic`, either null or the exact object
`{phase, errno_bucket}`. `phase` is a fixed enum of observation operations or
refusal conditions. A still-visible task with unavailable identity distinguishes
its existing stat, PID namespace and mount namespace reads. The errno bucket is
null or one of `ENOENT`, `ESRCH`, `EACCES`, `EPERM`, `EIO`, `OTHER_OS`,
`INVALID_VALUE`, `INVALID_ENCODING`; no error message, path, PID, TID, FD or raw
numeric errno is published. A direct namespace mismatch has a null errno.
Uninstrumented exception origins remain explicitly `unknown`, rather than being
inferred from earlier events. Non-null diagnostics are valid only on a refused
`PROC_UNAVAILABLE` receipt. The existing limit diagnostic remains separate.

The primitive observation wrapper records the closed fields on the current
exception and rethrows the same object. There is no ambient last-error state.
Existing ENOENT/ESRCH recovery, generation/presence rechecks, all-mode references,
limits, existing /proc reads and their order stay unchanged. A recovered closed FD or exited
task therefore cannot supply the cause of a later permission failure. A failed
recheck reports its own error; when an existing semantic refusal follows a
successful recheck, it retains the initiating error's bucket. Reused exception
objects receive the current operation's annotation when raised again.

This diagnostic does not establish that missing metadata is transient or that a
visible task may safely be skipped. In an isolated Linux fixture an exited,
unreaped child remains visible while its namespace metadata is unavailable; the
existing code refuses it. This is a synthetic counterexample, not an observation
of an operating-host zombie. A finite /proc scan is not an atomic snapshot or a
proof of future non-use. The added fields identify the refused observation only;
they do not change the refusal, retry, compression or cleanup policy.

The v3 validator deliberately rejects an old v2 receipt; historical receipts
retain their original pinned helper for verification. Stored plan and archive
manifests remain version 1 with unchanged hashes and restore contracts. The
workflow still verifies the exact shipped helper and invokes its closed
validator before emitting one result line; no workflow or deployment input is
added.

Two additional namespace-refusal phases indicate `Z` in the stat bytes already
read for that identity. They mean only `zombie_at_identity_read`, never current
state, non-use, safe omission or deletion permission. A missing but still-listed
FD also distinguishes the helper's own PID using `os.getpid()`; no identifier is
published and no extra /proc read is made. An isolated native Linux scan exposed
both an unreaped-child namespace refusal and a self-FD listing refusal: the
listing can include its temporary directory FD, which closes and reappears at
the same slot on the next listing. In the diagnostic-only version both remain
refusals. Neither local example
establishes the first unavailable observation on the operating host.

## Closed current-task listing descriptor

A `/proc/.../fd` listing can include the directory descriptor used by that
listing. It closes before the list is returned, and a confirming listing can
reuse the same number. In the metadata-missing branch only, the helper may now
confirm that number is closed with one direct `fstat`, under all of these gates:

- The original `fd_metadata` failure has errno ENOENT or ESRCH. A diagnostic
  phase string is never used as authority for this exception.
- Both the observed PID and native TID equal the current caller. Same PID alone
  is insufficient: a different thread can have an unshared file-descriptor
  table while the caller sees EBADF for a descriptor still open in that thread.
- The exact `(pid, tid, generation, number)` is not a known pinned observer slot.
  A closed source handle remains a broken pin even if the next listing reuses
  its number.
- Direct `fstat` reports EBADF. A valid descriptor or any other error retains
  the existing refusal. No flags, access mode, filename or inode guess excuses
  a positive source reference.

The check adds no file open or `/proc` read. It is not applied after target
metadata has been observed, to observer flags or the final identity recheck.
RO, RW, O_PATH and unlinked-but-open sources remain in use. Existing descriptor
counts, byte/task ceilings, deadlines, two passes, late tasks and generation
checks remain in force; the closed descriptor is still counted as observed.
The preexisting recovery for a descriptor absent from the confirming listing
is unchanged.

EBADF means closed at the direct probe, not future non-use. Reuse before the
probe refuses; a persistent source reference introduced after it is found by
the later pass. A finite scan still cannot prove an atomic global snapshot.
This candidate does not authorize skipping zombie tasks or unresolved metadata,
and its synthetic results do not identify an operating-host failure cause.

Regression coverage includes a real current-task `/proc` scan, actual Linux
RO/RW/O_PATH and unlinked handles, a same-PID thread with a genuinely unshared
FD table, reuse around the probe, broken pinned slots, flags failures, changed
generations and the unchanged total-FD cap. Native Linux cases are required on
Linux; they are explicitly skipped on other operating systems.


## Interrupted bundle metadata inspection

The fixed `inspect` mode observes only the already selected bundle after an
interrupted APPLY. It accepts the same closed plan JSON and SHA, and no confirm
or caller path. Its separate version-1 receipt does not change the existing
version-3 diagnose/plan/apply contract. The existing 600-second deadline, global
lock, 512 MiB reserve and 5 GiB preservation floor are unchanged. Inspection
opens the existing lock read-only without creating it and takes an exclusive
nonblocking flock. It does not run host reference scans because it never reads
backup payloads, writes an archive or removes an original.

Only the fixed bundle, deployment and snapshot directories and nine fixed file
slots are traversed, with a shared sixteen-distinct-entry bound including final rechecks. Every ancestor and child
is pinned without following symlinks. Regular payloads are statted, never opened.
Only the seven possible JSON manifest names can be opened, at most 64 KiB each
and 448 KiB total. Same-inode JSON is read once. The sole allowed multi-link case
is a same-directory `.manifest.pending`/`archive-manifest.json` pair with exactly
two links; this is the existing link-then-unlink publication window. Other aliases
or links are refused. Fixed directory entries, parent bindings and complete file
identities are checked again after observation. Docker protected state is checked
before and after; incomplete observations never become a successful result.

The closed result exposes presence, sizes, allocated bytes, identity/content
hashes and manifest shape/plan-claim checks, never raw content, dynamic paths,
process identifiers or exception messages. Gzip length equality is only a size
comparison. A well-formed plan-bound manifest is a claim about payload hashes,
not a fresh payload verification. Child plan association covers the measured
values/codec and deployment protected-state claim; it cannot reconstruct the
whole original source-identity hash or attest current originals. The root plan
claim and copied source-manifest hash are checked separately; the fixed
`bundle_child_hashes_match` field compares only manifest claims. `payload_verified` and all mutation flags stay
false, including when a published marker exists. Directory/file allocation is
counted once per inode. A malformed/truncated JSON is reported as such without
printing it. No inspection result authorizes recovery, cleanup or a retry.

Regression coverage includes partial and published fixtures, the publication
link window, cross-role aliases, wrong owners/modes/symlinks, unknown entries,
manifest limits and races, exact source/plan association, failure output closure,
read-only lock behavior, protected-state failure, and spies that reject payload
opens, compression, publication, source writes or removal. Existing bundle and
single-backup suites remain required; actual operating state remains separate.
