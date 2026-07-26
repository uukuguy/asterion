# Live Session Checkpoint

> Updated: 2026-07-26 11:58. **Session remains active — not a final handoff.**

## TL;DR

- Protocol/composition Tasks 1–8 and Application Authority Tasks 1–8 are
  complete, independently reviewed, and provider-free verified.
- DCI provenance/reproduction Tasks 1–10 are complete, independently reviewed,
  and provider-free verified.
- Task 11 execution remains external-blocked. Its bounded-selection design and
  five-task TDD implementation are complete and independently reviewed CLEAN
  through `da5dc3c`; no provider-backed execution has been authorized.
- Bounded authority now binds exact selected-query digests/counts, planned
  Agent/Judge operations, scope output identities, and a separate private
  RunManifest directory.
- `paper reproduce --limit N` remains optional and default-off. Plan mode is
  metadata-only; explicit execution propagates one exact per-scope prefix into
  preflight, operation caps, authority, and benchmark requests.
- Benchmark preparation revalidates bounded identity before authorization
  consumption or Agent work. Successful bounded evidence is
  `paper-bounded-authorized`, non-full, non-comparable, and preserved by the
  RunManifest compiler.
- Authorized execution additionally binds exact raw dataset bytes, benchmark
  descriptor identity, and descriptor device/inode. Private authority snapshots
  use independent primitive values and reject mutation, hostile equality,
  ancestor symlinks, replacement, and redaction bypasses.
- Bounded `limit-N` comparisons retain metrics but always report acceptance as
  not applicable. They remain `External-limited` and cannot become a normal
  source-parity PASS.
- QA, IR, and mixed scopes require exact planned Judge counts at authorization.
- RunManifest evidence is compiled and descriptor-safely written to a separate
  private directory before the next scope starts; closed batch inventories do
  not change.
- Task 8's supplemental design is committed as `87e1460`: default plan mode
  remains zero-operation and configuration-free; only explicit `--execute`
  requires complete operation and cost limits.
- Its three-layer TDD implementation plan is committed as `8662ad9`.
- Authority-ledger Task 1 is implemented across `9314c27`, `df8c35e`,
  `fcdfb61`, `fec9f3d`, and `641c331`; independent review is CLEAN.
- Task 8.2 is implemented across `3804a06..982c179`: exact scope-child roots
  are verified before input reads and consumed after selected-row validation;
  Agent/Judge operations are budgeted and reconciled from strict cost evidence.
- Task 8.2 review found two Important gaps, fixed in `730c9f3`; the final
  stale-docstring Minor is fixed in `982c179`. Independent review is CLEAN.
- Task 8.3 is complete across `ac88413..dd27856`: default plan mode is
  configuration-free and zero-operation; explicit execution requires sorted,
  available `paper-full` scopes and five positive limits, preflights before
  authority, dispatches scope-child requests sequentially, and always consumes
  or cancels live authority.
- Independent Task 8.3 review is CLEAN after closing partial-scope,
  post-authorization cancellation, duplicate count, and type-narrowing gaps.
- Task 8.4 passes all provider-free gates and an independent nine-property
  security review with zero Critical, Important, or Minor findings.
- Provenance Task 8 is complete across `9314c27..dd27856`.
- Provenance Task 9 is complete across `477aa93..d270f17`: locked benchmark
  evidence compiles into a closed, body-free RunManifest whose source,
  corpus, prompt, Judge, context, metric, implementation, selection, and
  artifact identities remain explicit and comparison-safe.
- Independent Task 9 review is CLEAN after closing forged-batch provenance,
  artifact inventory, failed-Judge accounting, corpus round-trip, bounded
  selection, and type-narrowing gaps.
- Task 10 is complete across `36e7c3c..99ff926`: public docs now distinguish
  local corpus from on-device-only processing, source families, inventory from
  executable closure, bounded verification from reproduction, and plan-only
  from explicitly budgeted execution.
- Independent Task 10 review is CLEAN after correcting whole-profile wording:
  sorted available `paper-full` scope subsets may execute, but they are not
  whole-profile or published-score reproduction.
- No provider-backed benchmark, Agent/Judge operation, full-dataset run, or
  published-score reproduction has been performed.

## Durable implementation state

- Paper-reference, pinned-upstream, and Asterion-safe experiment families have
  distinct prompt, Judge, ranking-metric, runtime, context, and implementation
  identities.
- Paper IR duplicate handling and paper trajectory localization parameters
  require explicit operator assumptions and never claim paper comparability.
- Trajectory alignment parses corpus-verified tool output before exact command
  argument fallback, including piped bash, `path:line:text`, `path:line`, and
  path-only output.
- Resolution configuration is closed, fingerprinted, and labels segment and
  overlap values as `asterion-defined`; forged rehashed configuration is
  rejected.
- Integer JSON overlap values are accepted according to the schema and
  normalized to floats; booleans, zero, non-finite values, partial triples,
  and non-Path registries fail before Agent execution.
- The Pi context extension implements golden-tested L0–L4 behavior: exact
  caps, strict pressure boundaries, structure-preserving placeholders,
  post-compaction pressure gating, and three-failure suppression.
- Effective benchmark context evidence binds exact paper, pinned-upstream, or
  Asterion-safe contracts to the immutable numeric profile and verified
  extension version/SHA without mixing source claims.
- Benchmark inventory now separates 13 paper dataset identities from 14
  standalone launchers: 11 upstream datasets plus 2 Asterion-added BEIR
  datasets.
- Bamboogle paper-full 125 and pinned-upstream sample-50 are incompatible
  scopes. Generic resolution sees 17 scopes, while paper profiles and
  authorization remain restricted to the original 16.
- RunManifest compilation uses descriptor-bound locked readers, exact closed
  artifact digests, canonical corpus contracts/content identities, and
  profile-bound external truth so fully rehashed forged batches fail closed.
- The target matrix covers Lite and CC, read+bash and read+grep, L0–L4, and
  100k/200k/400k corpus classes; unreported combinations remain explicitly
  method-incomplete rather than being promoted to executable paper claims.

## Verification boundary

- Task 7 focused suites pass 30 verification/resource tests.
- `make test` passes 393 Python tests.
- `make check` passes Python, Ruff/compileall, docs, TypeScript, Rust
  test/fmt/clippy, and wheel/sdist build gates.
- `make promotion-check` passes 19 commands with
  `provider_operations=0` and `full_dataset=no`.
- Independent Task 7 review is CLEAN after confirming the 17-row resource
  hash is an integrity binding, not an authorization expansion.
- Task 8.1 passes 23 authorization tests, 72 relevant regression tests, Ruff,
  diff checks, and independent dynamic identity/race/FD review.
- Task 8.2 passes 65 focused tests and 424 provider-free repository tests;
  Ruff and diff checks pass, and independent review is CLEAN.
- Task 8.3 passes 93 focused tests and 437 provider-free repository tests;
  Ruff, docs, diff, TypeScript, Rust, and build gates pass via `make check`.
- Task 8.4 promotion passes 19 commands with `provider_operations=0` and
  `full_dataset=no`; the final Task 8 security review is CLEAN.
- Task 9 passes 12 RunManifest tests and 50 benchmark/metric regression tests.
  Pyright reports zero errors for the compiler and its focused tests.
- Task 9 promotion passes 19 commands with `provider_operations=0` and
  `full_dataset=no`; independent provenance and comparison review is CLEAN.
- Final `make check` passes 450 Python tests plus Python, documentation,
  TypeScript, Rust, and distribution gates.
- Final promotion passes 19 commands with `provider_operations=0` and
  `full_dataset=no`; plan-only reproduction creates no authority or output root.
- Bounded Task 1 passes 84 focused tests after authority/fixture review fixes.
- Bounded Task 2 passes 65 focused tests after CLI orchestration review fixes.
- Bounded Task 3 passes 116 focused tests after drift/evidence review fixes.
- Bounded Tasks 4–5 and all final remediation reviews are CLEAN for spec,
  security, claims, code quality, and test completeness.
- Fresh final `make test` passes 493 Python tests; `make check` passes Python,
  Ruff, docs, TypeScript, Rust, and wheel/sdist build gates.
- Fresh promotion passes 19 commands with `provider_operations=0` and
  `full_dataset=no`; the `--limit 1` plan creates no authority or output root.
- Final cross-task review reports zero Critical, Important, or Minor findings.

## Immediate next actions

1. Integrate or preserve `feature/dci-bounded-reproduction` according to the
   selected Git completion option.
2. Request a new exact authorization for profile `paper-reference/pi`, scope
   `bright.robotics.main.full`, limit `1`, a private output root, and five
   positive operation/cost caps.
3. Only after that fresh approval, rerun preflight once and classify the result
   `External-limited`; never promote it to full or published-score reproduction.

## Do not regress these boundaries

- Do not treat packaged, bound, composed, executable, and verified as
  synonyms.
- Do not label Asterion-safe prompt, Judge, ranking, or localization choices
  as paper-reported semantics.
- Do not let manifests, `.env`, credentials, prior evidence, or caches grant
  execution authority.
- Do not infer full-reproduction authorization from this checkpoint.
- Do not expose prompts, answers, corpus bodies, provider payloads,
  credentials, raw output, or private paths on public surfaces.

## Ready-to-paste commands

```bash
git status --short
git log --oneline -10
cat docs/superpowers/specs/2026-07-26-dci-bounded-reproduction-selection-design.md
uv run asterion-dci paper describe
uv run asterion-dci paper verify
uv run asterion-dci paper reproduce --profile paper-reference/pi --output-root "$(mktemp -d)/absent"
uv run asterion-dci paper reproduce --profile paper-reference/pi --scope bright.robotics.main.full --limit 1 --output-root "$(mktemp -d)/absent"
make docs-check
make promotion-check
```
