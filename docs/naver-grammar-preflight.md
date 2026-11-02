# NAVER synthetic grammar preflight

The manually dispatched `naver-grammar-preflight.yml` tests one synthetic output
grammar through the existing engine's configured transport. It does not deploy
the product, open its database, save a report, change advertising, or restart a
service. Passing this check proves only that the single response matches the
supplied synthetic grammar; report compilation, source authority, freshness,
storage and rendered output require their own product checks.

## Fixed boundaries

- Live transport source: `bb151c2a483a3422c25ba203b7a9358569f5a9da`.
- Candidate: `grounded-segments-v14`.
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

## Grounded reference grammar

The validator supports the existing closed JSON subset and one additional form:
a closed object requiring exactly the string fields `s` and `f`, combined with
an `anyOf` containing 1–36 branches. Every branch contains only `properties`,
with only nonempty string enums for `s` and `f`. The parent constraints and a
branch must both match. These represent the permitted source and field pairs
in the private fixture.
The finite product catalog has at most 35 sources: 17 metric, 5 case, 1 plan,
3 product and 9 setup sources. Grouping cannot create more groups than sources;
the additional empty-reference branch gives the 36-branch bound. This bound
comes from the product catalog, not an asserted provider branch limit.
The no-reference branch has only `s: ""` and `f: ""`; mixed empty and nonempty
values are refused. All branches are checked before a matching branch can
succeed. General unions, unconstrained parents, extra branch keywords and nested union leaves remain
unsupported. The product remains responsible for whether a reference supports
the generated statement and whether the compiled document is valid.

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
