# Conversion diagnostic using the existing operating connection

This directory contains only the twelve public deployment tools, the original
Bundle Python code and job reference, and metadata from private qualification.
The six private product fixtures remain in the private qualification repository.
No connection secret is copied, extracted, or newly registered.

The two unchanged Bundle unittest commands run privately. Their exact successful
run, head, tree and artifact are verified before pinning the receipt in this
release. Two historical sibling-only replay skips remain explicitly separate
from passes. The public gate validates this receipt, each file digest, the
original Bundle Python and the narrowly declared workflow changes before SSH.
The reviewed release commit is the trust boundary for the private receipt.

The registered `debug-rank.yml` workflow is used on a new dedicated release
branch. The default branch and the historical 35f2 release branch are preserved.
Push/PR events run only checks. Only the first manual attempt on the dedicated
release branch can run report-progress prepare/apply/rollback. The existing
deployment concurrency group and pinned actions are retained.

Relative local paths gain this namespace. The transferred filename, server
destination, ownership, permissions, Incoming/Patch scripts and runtime guards
are unchanged. A current prepare run and reserved operation IDs must pass the
original payload and SSH pressure checks before apply. This change does not
trigger new advertising collection or bypass validation.

Qualification, deployment and customer strategy completion are separate facts.
Actual strategy completion still requires confirmed sources, exact account and
report-period identity, successful AI save, full reload and matching server GET.
