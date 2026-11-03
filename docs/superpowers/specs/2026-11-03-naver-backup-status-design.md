# Fixed NAVER backup status and metadata observation

This approved bounded implementation observes the existing NAVER backup contract;
it does not change backup, retention, permission, encryption or collection policy.

## Exact scope

Read one fixed engine Unix health GET (3-second whole request, 64 KiB total HTTP response including headers),
project only backup code/last_attempt_at/last_offsite_at and last_tick using closed
values. Missing backup state, unavailable health and invalid response remain
explicitly unknown; they are never converted to NEVER or a successful zero.
The RAM backup state is updated after scheduler ticks and is not an immediate
in-flight upload oracle. No database is opened by this health path.

Verify the current engine container has the exact fixed backup and socket bind
mounts before reading their fixed host paths. Read only local/outgoing directory
entry metadata, never ZIP/CMS/state.json/credential contents. Aggregate count,
logical/allocated bytes and oldest/newest filename KST day; filenames, UUIDs,
paths and raw values are not included in the result. The filename date is not a
verified archive manifest date. Reject symlinks/special files and mark unknown
entries, active building directories or concurrent changes incomplete. Bound
entries at 4096 shared across both folders and any permitted immediate building
children, and share one 10-second metadata deadline across both folders together.
Only the one-level building observation described below is permitted.

Protect the existing container/image identity baseline before and after the
observation. Reuse the same owner/main/first-attempt/host-pin/global concurrency
and existing global flock; do not imply that flock stops regular backup writes.
No external network request, SQLite access, key/content read, upload, deletion,
chmod of operating files, backup generation, restore or service action.

## Verification and release

Use synthetic Unix HTTP and metadata fixtures for red/green tests of closed
projection, absent/invalid/timeout/oversize response, empty versus incomplete,
symlink/special/name/mode/ownership refusal, caps, concurrent changes and no file
content reads. Test workflow guards, hash-bound helper and closed receipt, public
output canaries, exact CI and secrets. Source-only owner branch/PR is authorized;
merge and actual observation remain the coordinating agent's next decision.

## Python 3.10 timestamp compatibility

The initial observation refused before health or backup metadata was observed.
An isolated Python 3.10 reproduction confirmed that the previous parser rejected
Docker timestamps with 1/2/4/5/7/8/9 fractional digits, including nanoseconds;
the existing cold-backup snapshot accepts these. No raw operating timestamp was
retained, so this is a confirmed compatibility defect, not proof of the sole live
failure cause.

Keep the existing strict timestamp grammar and calendar/timezone validation.
Only the temporary parsing copy pads or truncates its fraction to six digits;
return the original string unchanged. Thus timestamps differing below one
microsecond remain different protected identities. No observation, policy,
permission, output field, command or retry scope is added. Verify all supported
precisions, invalid dates/timezones and old/new snapshot equality on Python 3.10
and 3.12 before the coordinating agent considers another observation.

## Version 2: unexpected-entry metadata

The existing archive aggregate stays strict: an unexpected root item still makes
the count, logical/allocated bytes and filename dates unknown. The separate
`metadata` object does not certify an item as a backup. Its closed root buckets
classify archive-shaped regular files, producer-shaped building directories,
other regular files/directories, symlinks and special entries. Archive-shaped
means the existing name grammar, not a correct extension, valid date or verified
manifest. Archive eligibility violation counters are independent and may overlap:
name, extension, type, owner, mode, links, size and date. Directory owner/mode
violations here compare against the archive-file contract, not a directory policy.
Invalid numeric size/allocation makes the entire diagnostic incomplete, because
no numeric aggregate can be trusted in that case.

Only real `.building-[a-z0-9_]{8}` directories owned by engine UID 10001 with exact
0700 permissions can be opened. Use `O_DIRECTORY|O_NOFOLLOW`, pin the descriptor
identity and inspect its immediate children by nofollow stat. Child buckets name
only fixed producer categories (snapshot, packed, encrypted), other regular
files, directories, symlinks and special entries. Never open a regular file or
descend a nested/unrecognized directory. Count unscanned directories and keep
their subtree bytes null when any exist; zero means no such directories were
encountered, not that symlink targets or filesystem overhead were measured.

Each bucket reports entry count, regular-file logical bytes and inode-allocated
bytes. Deduplicate `(device,inode)` within each folder across root and child
items, attributing an inode to its first sorted root name and then sorted
building/child name. Count duplicate appearances separately; root and child
bucket amounts are additive within one folder, not a guaranteed reclaim amount.
Folder inode allocation is not subtree allocation. Hard links outside the
observed folder, shared/reflink extents and symlink target contents are unmeasured.
No directory is labelled orphaned, inactive, safe to delete or safe to restore.

Only producer-shaped root directory mtimes have closed oldest/newest UTC fields.
They use the already captured stat values and retain full nanosecond identity
in the internal race check; displayed times have microsecond precision. Mtime is
not a creation time, process-liveness signal or reliable completion timestamp.
No raw paths, filenames, UUIDs, UIDs, permission strings or file contents escape.

One shared budget covers local and outgoing together: 4096 root/child entries,
16 opened building directories, and 10 seconds. Recheck all observed entry and
directory identities. Changes, caps or stat/open failures leave all diagnostic
numbers unknown with a closed reason; no partial numeric estimate is emitted.
An observed diagnostic describes only this bounded metadata view. It cannot
upgrade an incomplete archive summary, nor prove a backup upload or restoration.
Keep the exact hash-bound helper, closed receipt validator, container/image
protection, global lock and existing owner/main/host guard. The receipt version
and scope change to 2 and `naver-backup-status-v2`; the workflow adds the new
contract module to its focused checks without changing its operating actions.
