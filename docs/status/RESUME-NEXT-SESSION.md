# Live Session Checkpoint

> Updated: 2026-07-24 22:16. **Session remains active — not a final handoff.**

## TL;DR

- Protocol/composition Tasks 1–8 are implemented. The final whole-branch review
  found one catalog race, direct-error redaction gaps, and documentation/recovery
  drift; the corrective wave is implemented and its full provider-free gates
  pass.
- Application Authority Task 1 was pulled forward and implemented to remove DCI
  configuration authority from the generic CLI. Approved Application Authority
  Tasks 2–8 remain future work.
- No `asterion.host_services` registry exists in the current tree. It remains an
  approved future design in Application Authority Task 5, not implemented
  evidence.
- No provider-backed benchmark, Agent/Judge operation, or published-score
  reproduction has been run.

## Cumulative state as of this checkpoint

- `docs/architecture/dci-capability-audit.md` remains the authoritative mapping
  from paper/GitHub claims to Asterion code, reachability, evidence, and gaps.
- The approved work sequence remains protocol/composition, application
  authority, then DCI provenance/reproduction. The protocol implementation and
  its pulled-forward generic-CLI correction are complete; later application and
  provenance tasks have not been promoted to implemented.
- Runtime identifiers and capability arrays are canonical across Python,
  TypeScript, schemas, and shared fixtures. Runtime streams require one run ID,
  contiguous sequence numbers, one terminal event, and exactly one matched
  result for every tool call.
- TypeScript validation values, catalog manifests, assembly plans, package
  invocations/results, and runner evidence are immutable snapshots.
- Composition is deterministic, rejects every package/package and package/host
  provider ambiguity, fails on missing edges and cycles, and requires exact
  package references and implementation bindings.
- DCI and controlled-code declarations use real package-produced event/artifact
  edges. Runtime-internal events and source artifacts are not modeled as host
  evidence.
- The generic CLI is DCI-neutral, loads one exact provider and runtime, accepts
  only explicit opaque runtime options, and does not materialize repository
  `.env` authority.
- Packaged resources are portable: the tracked instruction symlink is gone and
  CI uses the repository's exact Node `22.19.0` floor.
- Final-review correction `798591b` pins catalog roots and direct JSON children
  to descriptor-owned filesystem objects. Descriptor-relative no-follow
  discovery fails closed when the platform cannot provide safe primitives.
- Final-review correction `71dff6a` keeps runtime and Pi/Claude tool-lifecycle
  errors structural without echoing provider-controlled keys or call IDs.
- Architecture examples now use actual `asterion.*` imports and the real
  controlled-code graph. The docs checker validates documented Asterion import
  symbols so future API drift fails the documentation gate.

## Verification boundary

- The broad review of base `a607d6a` recorded 67 focused Python protocol tests,
  13 TypeScript tests, 244 repository Python tests, `make check`, lint,
  docs-check, promotion-check, and diff-check as passing.
- The corrective wave passes the equivalent expanded protocol gate: the former
  67-test set now has 72 tests after five new runtime/catalog regressions. The
  two direct adapter-redaction tests also pass.
- TypeScript passes 13 tests. `make test` passes 252 tests. `make check`, lint,
  docs-check (25 Markdown files and 39 links), promotion-check (18 commands,
  zero provider operations), and whitespace validation pass.
- All commands in this wave are provider-free. External Agent/Judge, full
  benchmark, and paper-reproduction boundaries remain not rerun.

## Immediate next actions

1. Request the final whole-branch re-review.
2. After a clean final re-review, resume Application Authority Task 2: prove
   runtime-to-assembly bijection and executable closure.
3. Continue approved Application Authority Tasks 3–8 in order, then begin the
   separate DCI provenance/reproduction plan only with its stated authorization
   and budget boundaries.

## Do not regress these boundaries

- Do not treat packaged, bound, composed, executable, and verified as synonyms.
- Do not claim `dci.complete-application` is a full-dataset benchmark; it is a
  one-question five-stage chain.
- Do not label Asterion-safe prompt, Judge, NDCG, or localization parameters as
  paper semantics.
- Do not make execution authority persist through `.env`, cache, prior evidence,
  package manifests, or provider payloads.
- Do not add source scanning, package ranges, registries, hidden precedence, or
  symlink traversal to the catalog.
- Do not rerun provider-backed work without explicit operator authorization and
  a finite positive budget.

## Ready-to-paste commands

```bash
git status --short
git log --oneline -8
sed -n '1,260p' .superpowers/sdd/protocol-final-fix-report.md
sed -n '150,260p' docs/superpowers/plans/2026-07-24-asterion-application-authority.md
```
