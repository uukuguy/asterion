# Provenance and Reproduction Task 1 Report

## Outcome

DCI experiment profiles now separate six immutable profiles across three
source families:

- `paper-reference/pi`
- `paper-reference/claude-code`
- `upstream-github/271f37e71f053bf0c99c05ce6d2fb53b841d922e/pi`
- `asterion-safe/pi`
- `asterion-safe/claude-subscription`
- `asterion-safe/claude-minimax`

Every resolved profile carries explicit, body-free source, prompt, Judge,
metric, runtime, context, dataset-selection, and implementation contracts.
Paper-unreported parameters are a closed immutable mapping. Cross-family
component substitution, noncanonical upstream commits, Asterion profiles with
published-paper targets, and unknown unreported parameters fail closed.

## Exact implementation binding and self-reference decision

The approved Task 1 brief proposed storing `implementation_sha256` in
`experiment-profiles.json`. That resource is itself one of the 65 exact bytes
hashed by `dci_complete_implementation_identity()`. Embedding the resulting
digest in the resource would require a SHA-256 fixed point and could not be
implemented truthfully by regeneration.

The static schema therefore stores a body-free `implementation_contract`
instead of a digest. The DCI-local loader reads and validates the exact
packaged schema/resource, then resolves `implementation_sha256` once through
`dci_complete_implementation_identity()`. All six profiles use that same
current Asterion execution digest; their profile identities remain distinct
because their source and semantic contracts differ.

This dependency is non-recursive:

```text
experiment_profiles loader
  -> dci_complete_implementation_identity
     -> exact-byte reads of the declared 65 resources
```

The provenance function never invokes the profile loader. Tests mutate the
profile resource bytes through the provenance reader, prove the implementation
digest changes, and prove the resolved profile identity changes with it.

## Compatibility boundary

The former `current-default/*` names are absent from packaged profiles,
resolved profile identities, verification inventory, and reproduction
branches. The three former names are accepted only by `asterion-dci paper`
CLI parsing and normalized immediately to `asterion-safe/*`. Direct resolver
calls reject them, and successful CLI output contains only the canonical ID.

The necessary reproduction MiniMax branches were renamed from
`current-default/claude-minimax` to `asterion-safe/claude-minimax`; this is a
small required extension beyond the brief's file list so canonical evidence
cannot reintroduce the compatibility alias.

## Canonical identities

- Experiment-profile schema SHA-256:
  `6c06ef8b0885433f660d008d35d988aaf0bc5f0d893c2ea8caec240cd3728c7b`
- Resolved implementation SHA-256 at verification:
  `af3402d5e48ca68e7080abb0524a8d59850c91c72e92ecaf15d5c62244d98aba`
- Resolved profile inventory SHA-256 at verification:
  `ddecd74e3d49d8a42203b43eca875aec9603c399c0e5b14631ebe41f44df0243`

The implementation and profile inventory digests are expected to change when
any declared implementation resource changes. Tests reproduce the schema,
upstream request-shape, upstream Judge-contract, and inventory hashes with the
repository's canonical JSON helper rather than trusting hand-entered values.

## TDD and verification

- Initial RED: the five new provenance tests failed because only mixed
  `current-default` and paper profiles existed, no source-contract fields or
  resolved implementation digest existed, and aliases reached the resolver.
- Focused suite: PASS, 15 tests.
- `make test`: PASS, 340 Python tests.
- `make lint`: PASS.
- `make check`: PASS, 340 Python tests, 13 runtime TypeScript tests,
  11 context-extension tests, 19 Rust tests, documentation, lint, and build.
- `make promotion-check`: PASS, 19 commands, zero provider operations, and no
  full dataset.
- `git diff --check`: PASS.

All verification was provider-free. No Agent or Judge operation ran.

## Ownership

`docs/status/JOURNAL.md` remained caller-owned and was neither edited nor
staged by this task.
