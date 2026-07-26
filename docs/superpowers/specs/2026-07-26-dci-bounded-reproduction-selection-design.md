# DCI Bounded Reproduction Selection Design

> Approved direction: add deterministic, explicitly authorized bounded
> selection to `paper reproduce` while preserving the default-off execution
> boundary and full-scope provenance.

## Context

The provider-free Tasks 8–10 closed same-process execution authority, operation
and cost budgets, locked benchmark evidence, and RunManifest compilation.
However, the original Task 11 smoke-test contract requires one selected query,
while the current reproduction CLI has no `--limit` option and requires every
executed paper scope to use its complete published selection.

The smallest currently executable paper scope contains 101 queries. Treating a
generic authorization response as consent for 101 provider operations would
violate the exact-scope and finite-budget boundary. This design restores the
intended one-query external-limited path without weakening full-scope identity
or changing provider-free defaults.

## Goals

- Support `paper reproduce --scope SCOPE --limit 1 --execute` as an explicitly
  authorized, at-most-one-query execution.
- Reuse the benchmark runner's deterministic source-order prefix selection.
- Bind the actual bounded selection to preflight, authorization, execution,
  evidence, and RunManifest identity.
- Preserve the existing five positive limit requirements.
- Produce private, body-free RunManifest evidence after a successful scope.
- Keep bounded evidence classified as `External-limited`, never as a full
  profile, paper-score, or published-score reproduction.

## Non-goals

- No random sampling, query search, or `--query-id` interface.
- No new synthetic paper scope or dataset identity.
- No relaxation of source-family, execution-class, launcher, batch-profile, or
  complete-scope compatibility checks.
- No provider-backed execution during implementation, testing, acceptance, or
  promotion.
- No claim that `paper_full_executable=false` has changed.

## Considered approaches

### Selected: one deterministic limit applied per explicit scope

Add a positive integer `--limit` to `paper reproduce`. For every explicit
scope, the bounded selection is the first `limit` query IDs in the already
verified canonical source order. The same limit applies independently to every
selected scope. Execution rejects a limit greater than any selected scope's
published selection count.

This reuses the benchmark's existing selection semantics, keeps the CLI small,
and makes operation counts deterministic before authority is issued.

### Rejected: synthetic smoke-test scopes

Adding one-query manifests to the paper scope inventory would conflate a test
selection with a paper-reported experiment and expand the closed profile
contracts for an operational convenience.

### Rejected: explicit query-ID selection

An operator-selected query ID would need a discovery surface, ordering rules,
and another cache/evidence identity branch. It is unnecessary for the Task 11
smoke test and increases the risk of cherry-picked evidence.

## User-facing contract

Plan mode remains the default:

```bash
uv run asterion-dci paper reproduce \
  --profile paper-reference/pi \
  --scope bright.robotics.main.full \
  --limit 1 \
  --output-root /operator/selected/private/root
```

This command:

- validates CLI metadata only;
- reports one planned Agent operation and zero planned Judge operations for the
  IR scope;
- performs zero external operations;
- issues no authority;
- creates no output directory;
- requires no budget flags.

Execution additionally requires `--execute` and all five existing positive
limits:

```text
--max-agent-operations
--max-judge-operations
--max-cost-usd
--max-agent-cost-per-operation-usd
--max-judge-cost-per-operation-usd
```

Execution still requires explicit, sorted, unique scopes. Every selected scope
must belong to the profile, use `paper-reference`, use execution class
`paper-full`, have an available launcher and batch profile, and bind a complete
published source selection. `--limit` bounds execution within that verified
scope; it does not create a new paper scope.

Omitting `--limit` preserves the existing full-selection behavior. A limit is
positive, finite as an integer, and no greater than the selection count of
every selected scope.

## Selection identities

The existing profile-selected digest continues to identify the complete
published selection for each scope. Bounded execution adds two immutable values
per scope:

- `bounded_selected_ids_sha256`: canonical digest of the exact selected query
  IDs, sorted into the existing evidence identity order after applying `limit`;
- `selected_query_count`: exact number of selected query IDs.

The full selection digest and bounded selection digest are distinct fields.
They must never overwrite or masquerade as one another.

Plan mode derives counts from closed scope metadata and does not read datasets.
Execution mode performs descriptor-safe host preflight, verifies the complete
source selection against the packaged scope identity, takes the deterministic
prefix, and computes the bounded digest before creating the output root or
issuing authority.

## Authority model

`FullExecutionAuthorization` remains an in-process, one-use capability. Its
immutable snapshot and private registry record gain the bounded selection
digest and selected count for every authorized scope.

Authorization validates:

- exact profile identity;
- explicit sorted scope identities;
- each complete profile-selected digest;
- one bounded selection digest and positive selected count per scope;
- selected count not greater than the scope's complete selection count;
- exact private output-root identity;
- all five positive limits;
- Agent and Judge operation caps sufficient for the bounded plan;
- `invocation_authorized is True`.

For calls that omit `--limit`, the bounded selection values equal the complete
selection values. This retains existing full-scope behavior and avoids a second
authority type.

No environment variable, credential, cache, prior result, manifest, or limit
value grants authority.

## Execution flow

The CLI constructs one immutable bounded plan before authority:

1. Resolve the exact profile and explicit scopes.
2. Validate scope compatibility and metadata counts.
3. In execution mode, preflight dataset, corpus, cwd, runtime, and Judge inputs.
4. Verify each complete selected-ID sequence from the local dataset.
5. Apply `limit` to that verified sequence and compute its bounded digest.
6. Verify the five supplied limits cover the bounded operation plan.
7. Issue one authority bound to both complete and bounded selection identities.
8. Create one `BenchmarkRequest` per scope with the exact `limit`, authority,
   scope ID, and descriptor-bound child output root.
9. Execute scopes sequentially through `execute_authorized_reproduction`.
10. Compile and persist a body-free RunManifest for each successful scope.
11. Consume/finalize authority on success; cancel it on every failure.

The benchmark runner independently reads and verifies the complete source,
applies the request limit, recomputes the bounded selection digest, and compares
it with the authority before the first Agent reservation.

## Operation accounting

Planned Agent operations equal the sum of selected query counts across scopes.
Planned Judge operations equal the selected query counts for QA scopes and zero
for IR scopes. The CLI prints these bounded counts in both plan and execution
modes.

The supplied operation limits may exceed the plan but may not be below it.
Existing reservation and reconciliation rules remain unchanged:

- every external Agent/Judge operation reserves before provider work;
- actual cost evidence reconciles after the operation;
- cache reuse consumes no operation;
- any exceeded or invalid bound cancels later operations.

The Judge operation cap remains a required positive integer even when the
selected IR plan expects zero Judge operations, preserving the approved
five-positive-limit interface.

## Evidence and comparison

At authorization issuance, the private parent output root receives a distinct
mode `0700` manifest directory whose descriptor identity is retained beside the
scope output identities. After one scope completes,
`compile_run_manifest(scope_output_root, profile)` compiles the locked batch. A
new descriptor-safe writer persists an opaque scope-named manifest as mode
`0600` in that separate manifest directory.

RunManifest is never written into a benchmark batch root because doing so would
violate the batch's closed artifact inventory. The manifest file contains no
prompts, answers, corpus text, provider payloads, raw output, credentials, or
private paths.

The reproduction result exposes only body-free manifest identity and a relative
artifact name for each scope. It does not expose the private output root.

RunManifest selection identity must describe the bounded query set. Existing
compiler validation rejects selection count, selection digest, artifact
inventory, profile, corpus, implementation, metric, or aggregate drift.

`paper compare` remains an explicit follow-up. A one-query comparison is
classified `External-limited`; it cannot produce a full-reproduction PASS or
change provider-free acceptance status.

## Failure and cancellation

The following fail before authority and output creation:

- missing explicit execution scope;
- invalid, duplicate, or unsorted scope;
- zero, negative, boolean, or excessive limit;
- unavailable or partial paper scope;
- missing dataset/corpus/runtime/Judge prerequisite;
- complete selected-ID mismatch;
- insufficient or invalid operation/cost limits.

The following cancel live authority and prevent later operations:

- bounded selection digest/count mismatch;
- dataset replacement after preflight;
- output-root identity replacement;
- budget reservation or reconciliation failure;
- benchmark failure, cancellation, or manifest compilation failure.

Public errors remain stable and body-free. They never include query IDs,
prompts, answers, corpus content, raw provider data, credentials, issuance
tokens, or private paths.

## Compatibility

- Existing plan-only commands without `--limit` are unchanged.
- Existing explicit full-selection execution without `--limit` is unchanged.
- Existing benchmark `--limit` behavior remains available outside reproduction.
- `paper_full_executable` continues to derive from complete method and target
  closure; bounded execution does not affect it.
- The closed reproduction-result schema continues to describe only RunManifest
  and comparison evidence. The in-process paper execution coordinator returns a
  strictly validated Python result containing body-free manifest identities and
  relative artifact names; it is not promoted into a new wire contract.
- Runtime, package, and assembly protocols remain unchanged.

## Verification

All implementation verification is provider-free and uses `unittest`.

Tests cover:

- plan-only `--limit 1` reports one Agent, zero expected Judge operations for a
  Bright IR scope, creates no output, and requires no budgets;
- execution requires explicit scope, `--execute`, and all five positive limits;
- one-query execution passes `limit=1` to the exact authorized request;
- multi-scope limits produce deterministic per-scope selections and summed
  operation counts;
- invalid and excessive limits fail before authority;
- insufficient operation/cost limits fail before authority;
- complete selection mismatch fails before authority;
- bounded digest/count, request-limit, dataset, and ordering drift fail before
  Agent work;
- replay, cancellation, and output identity replacement remain fail-closed;
- full-selection execution without `--limit` remains compatible;
- a successful local fixture execution writes one validated body-free
  RunManifest per scope;
- manifest compilation failure cancels/finalizes safely and cannot report
  success;
- sentinel prompts, answers, credentials, provider payloads, query IDs, and
  private paths do not appear on public output or errors;
- `paper verify`, `make check`, and `make promotion-check` retain zero provider
  operations and no full dataset run.

Provider-backed Task 11 execution occurs only after implementation review,
provider-free promotion, and a new exact operator approval naming profile,
scope, output root, and all five limits.
