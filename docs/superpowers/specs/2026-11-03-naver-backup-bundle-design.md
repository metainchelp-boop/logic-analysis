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
