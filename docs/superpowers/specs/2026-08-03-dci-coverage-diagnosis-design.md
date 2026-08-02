# DCI Coverage Diagnosis Closure Design

## Goal

Prepare the provider-free half of Task 9 without running a provider, Agent,
Judge, network request, or external model. The implementation will accept a
fully validated, content-free aggregate representing the future five-by-ten
coverage experiment, merge it with the existing six recovered historical
runs, render a safe Chinese diagnosis, and expose the query-decomposition gate
without granting execution authority.

## Scope Boundary

This change stops before Task 9 Step 3. It does not execute the Task 8 plan,
create a positive execution authorization, read unvalidated raw run folders,
or publish coverage results. Documentation will explicitly say that the
coverage experiment has not run and that the decomposition gate remains
blocked until five complete valid aggregates exist.

The raw-artifact reader is deferred until the real immutable Task 8 evidence
layout exists and can be validated against its receipts. This change does not
invent a second evidence serialization contract.

## Safe Aggregate Contract

`DciCoverageDatasetObservation` is a frozen, exact-type value for one of these
datasets, in this order:

1. `bright.biology`
2. `bright.earth-science`
3. `bright.economics`
4. `bright.robotics`
5. `beir.scifact`

Each value contains only public-safe fields: dataset identity; available and
total query counts; median coverage-any, coverage-mean, and coverage-all in
microunits; retained-coverage availability and value; tool observation count;
surfaced gold count; model-call count; context-frame count; missing-boundary
count; integrity-failure count; and one evidence digest. Metrics may be absent
only when their corresponding availability is zero. Counts are bounded by the
ten-case task scope and microunits by 0 through 1,000,000.

`DciCoverageExperimentObservation` contains exactly those five values plus the
Task 8 plan, proposal, scope, variant, registry-set, authorization, and receipt
set digests. It also binds 50 Agent operations, zero Judge operations, a
5,000,000-microusd maximum, fewer than two infrastructure failures, and an
experiment digest derived from the complete safe mapping. It is data only and
contains no execution authority.

## Diagnosis Merge

`diagnose_recommended_pack(runs, *, coverage_experiment=None)` preserves the
current no-coverage report and renderer output. When a safe aggregate is
present, dataset observations receive the coverage fields for the five IR
datasets; Bamboogle receives explicit unavailable coverage fields.

Only a complete aggregate with 10 available of 10 total queries for all five
datasets and zero integrity failures closes `retrieval-coverage`. Other missing
evidence codes remain unchanged. Partial, reordered, identity-mismatched, or
integrity-failed input fails closed or leaves the gate blocked according to
whether the aggregate itself is structurally invalid or valid-but-incomplete.

Findings remain digest-based observations, hypotheses, evidence gaps, and
non-comparability statements. The Chinese renderer describes relationships as
observed correlations and explicitly says they do not establish causality.

## Proposal Gate

`DciProposalSummary` gains an exact gate state. Coverage instrumentation is
reported as completed only for complete valid coverage evidence. The existing
`retrieval-query-decomposition` proposal becomes ready for a separate finite
authorization only when coverage is complete and integrity-clean. It always
retains `requires_operator_authorization=True` and
`execution_authorized=False`; this task cannot authorize or start its 80 Agent
operations or 8,000,000-microusd envelope.

## CLI Boundary

`pathlight_cli.main` accepts an optional in-memory
`DciCoverageExperimentObservation` dependency for provider-free tests and
future validated loaders. The existing command line adds no coverage file flag
and no raw evidence parser. With no injected aggregate, `pathlight diagnose`
remains compatible with its existing inputs and outputs.

## Documentation

`PATHLIGHT-DCI-DIAGNOSIS.md` and `DCI-BENCHMARK-INSTANCES.md` will add a clear
provider-free preparation section. It states that no 50-case coverage result
exists yet, lists the finite Task 8 limits, and gives the exact execution
command shape and the digest fields an operator must verify before creating a
0600 authorization. It contains no operator path, case identity, provider,
model, configuration, prompt, answer, tool payload, or corpus text.

## Error Handling and Privacy

All new value types copy and validate exact built-in values. Unknown fields,
subclasses, unsorted datasets, invalid digests, out-of-range counts, missing
metrics, and contradictory completion claims fail with the existing
context-free diagnosis error. Rendering uses only fixed Chinese labels,
integers, fixed states, and digests already accepted by the safe aggregate.

## Test Strategy

Tests first demonstrate that diagnosis does not accept the new aggregate.
Focused coverage then verifies:

- complete 10/10 evidence closes only `retrieval-coverage`;
- all coverage metrics are deterministic and present for the five datasets;
- partial valid evidence keeps the decomposition gate blocked;
- integrity failures block the gate;
- reordered, swapped, subclassed, or digest-tampered aggregates fail closed;
- renderer output is correlation-only, deterministic, and sentinel-free;
- CLI dependency injection publishes the same private staged outputs without
  loading a provider;
- the existing no-coverage report remains unchanged.

Provider-free verification covers the diagnosis and CLI modules plus the
existing Pathlight coverage and experiment coordination tests. External Step 3
and result-bearing documentation remain explicitly unverified.
