# NAVER synthetic grammar preflight

The manually dispatched `naver-grammar-preflight.yml` tests one synthetic output
grammar through the existing engine's configured transport. It does not deploy
the product, open its database, save a report, change advertising, or restart a
service. Passing this check proves only that the single response matches the
supplied synthetic grammar; report compilation, source authority, freshness,
storage and rendered output require their own product checks.

## Fixed boundaries

- Live transport source: `d633ff4450bb74206ecce5dda157387336256097`.
- Candidate: `grounded-blocks-v16`.
- The live image label, image identity, engine UID and read-only root filesystem
  must match. All 16 files in the transport import closure are SHA-256 pinned;
  unexpected imports or changed files refuse execution.
- The private product commit supplied to the workflow identifies the synthetic
  schema factory. It is distinct from the deployed transport source above. Its
  checkout must exactly match that commit and contain no tracked or untracked
  changes. Building the package forbids socket connections and SQLite access.
- Only the public helper and the bounded synthetic JSON package are transferred.
  Package size is at most 24,576 bytes; request size is at most 32,768 bytes;
  response size is at most 131,072 bytes. No private product source, credentials,
  customer material or response text is emitted in the receipt.

## Separate prose and references

The v16 candidate represents reference-capable prose as closed objects containing
qualitative text and a separate reference array. The product assembles the text
and its selected evidence in separate lines. Originally qualitative fields stay
plain strings; appeal evidence remains in its existing server-owned basis.
This removes direct unit attachment to references in generated prose. It does
not establish the factual correctness of arbitrary prose or eliminate the
domain's separate Korean-quantity and semantic rules. The schema uses closed
objects, arrays, local definitions and patterns, without `anyOf` or text indices.
The helper's existing schema validator is unchanged.

A lexically valid reference is not proof that the referenced source is available
or supports a statement. The product's existing exact allowed-reference prompt,
compiler and domain checks remain responsible for source membership, numeric
claims, semantic limits and the final document. The short synthetic preflight
message does not execute the full product request builder or those domain checks.

The validator retains its narrowly bounded legacy support for a closed `s`/`f`
object with 1–36 partial enum branches. Its positive and negative tests remain;
this does not establish provider support or make that form part of v16. General
unions and unknown schema keywords still fail closed. Only the fixed v16
candidate is accepted at the package boundary; earlier candidate packages refuse.

## Execution and evidence

The existing owner, main-branch, first-attempt and explicit-confirmation guards
remain in place. Pinned Actions, SSH host fingerprint, shared deployment
concurrency and the server deployment lock protect the transport boundary.
Container identity, image, PID, start time and restart count must remain unchanged.

One dispatch can make at most one HTTP request, without repair or retry. The
configured provider must permit the existing unlimited monthly-budget policy;
the tool does not change that policy. An HTTP response must close successfully,
end normally, parse as a JSON object and match the exact supplied schema. A lost
child receipt reports an unknown transport outcome instead of claiming zero
calls. The receipt includes only bounded numbers, fixed identifiers and closed
reason codes. A further paid attempt requires a separate deliberate dispatch.

Local validation needs no provider, database, Docker daemon or credentials:

```sh
python3 -I -B -m unittest discover -s deploy/naver/tests -p test_grammar_preflight.py -v
```
