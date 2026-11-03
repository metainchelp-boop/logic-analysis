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
entries at 4096 per folder and share one 10-second metadata deadline across both
folders together. No recursive scan.

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
