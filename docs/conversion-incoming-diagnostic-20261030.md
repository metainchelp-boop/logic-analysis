# Read-only diagnosis of prepare 41023987057

The released executor (7121379, file-identical to ba05a5e) sealed run 41022549110
(ciphertext 53b9fd97ccf1baf5923af959fd8b7e315df04c51b4440ce12de91a029ad32027), and
prepare 41023987057 then stopped at Incoming with COMPLETION_INCOMING_REFUSED.
Ownership, Transfer and Patch were skipped. The suspected but unconfirmed cause is
HOST_BASELINE drift from an unrelated container restart on the same host.

This branch adds one minimal read-only probe. It rebuilds the failed prepare request
offline from the unchanged pinned release (transport 58bc51e9, Bundle 546c7cb7,
controller 0048f014, base controller 3be9c036) with source abceeb7/50681cb0, the
sealed ciphertext hash and the live baseline 1a107fb0. No signed URL is used and no
ciphertext is downloaded. On the host it only decodes, binds modules, validates the
package and computes the existing host baseline. It reports only stage, root_user,
the actual baseline hash, the expected current baseline and whether they are equal.

It never calls transport.execute, prepare, apply, rollback, trusted_dir or any write.
Detailed container components and directory metadata are deliberately not collected;
a separate bounded probe would be needed if this result is inconclusive.

The branch is BASE 7121379 plus exactly four added files; the release checker,
qualification and payload are untouched, and the normal release gate intentionally
refuses this head. One push to this branch runs one first-attempt diagnosis under
the deploy-logic-analysis lock. A differing baseline is a stop condition, not an
override; nothing here deploys or authorizes a deployment.
