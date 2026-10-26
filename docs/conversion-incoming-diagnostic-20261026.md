# Read-only diagnosis of prepare 40335961943

The exact reviewed release reached the existing VPS connection but Incoming returned COMPLETION_INCOMING_REFUSED. Ownership, Transfer and Patch were skipped. This dedicated branch adds a one-shot read-only probe of that failed run's transport decoding, module binding, package validation, effective root identity, current host baseline fingerprint and three fixed directory metadata records. The original deployment job, Bundle, source pins, helpers, caps and private qualification stay unchanged.

The probe does not invoke transport.execute, prepare/apply/rollback, trusted_dir or any mutation. It does not read environment files, keys, databases, application logs or model text. Docker reads use only the existing baseline function's selected public metadata; output contains hashes, booleans and fixed-path stat metadata. Failures expose only a fixed stage and allowlisted error code. A differing host baseline is a stop condition, never an override or deployment authorization.

The dedicated owner push branch runs only three new boundary checks and the read-only probe, with pinned actions, exact base plus four added files, attempt 1, and the existing deploy-logic-analysis concurrency lock. It does not repeat native qualification or the failed prepare. All emitted results remain diagnosis, not successful preparation or strategy completion.
