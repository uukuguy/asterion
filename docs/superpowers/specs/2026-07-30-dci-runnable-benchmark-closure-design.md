# Runnable DCI Benchmark Closure Design

## Goal

Deliver an installed Asterion DCI benchmark path that closes:

```text
instance selection → exact source lock → plan → explicit authorization
→ selected provider loading → task execution → private evidence → resume
```

The first delivery contains both a deterministic local instance and one real
Agent/Judge-backed DCI instance. The remaining DCI benchmarks then advance
individually through an explicit instance backlog.

## Architectural position

DCI remains a capability-package implementation of Asterion's generic benchmark
subsystem. Generic benchmark modules own plans, sequential execution, evidence
protocols, and injected executor interfaces. Product-owned DCI modules select
an exact instance, translate private operator configuration, authorize work,
load the selected package provider, and supply the executor.

The installed `asterion-dci` entry point wires a production
`DciBenchmarkHost`. Tests and embedding applications no longer need to inject a
host factory merely to make an installed benchmark executable. The DCI adapter
does not add a task loop, source scanner, composer, runner, retry layer, or
evidence writer.

## Exact benchmark instances

An immutable product catalog declares exact instance identities. Each entry
contains:

- `instance_id` and exact version;
- exact application and suite refs;
- the selected task or task set;
- executor profile;
- dataset contract;
- default case count;
- whether exact all-case resolution is supported;
- cost class.

The initial catalog contains:

- `dci.local-fixture@1.0.0`: all fifteen `dci.all@1.0.0` bindings over
  deterministic fixture inputs and a provider-free executor, selected through
  `dci.local-benchmark-application@1.0.0`;
- `dci.qa.bamboogle.github-sample50@1.0.0`: the exact GitHub Bamboogle
  sample-50 contract using real data, Agent execution, and an independent
  Judge, selected through `dci.complete-application@1.0.0` and a package-owned
  one-task suite with the same ID and version as the instance.

The remaining fourteen exact DCI task instances are present as planned catalog
entries but cannot be selected for execution until their implementation state
is `implemented`.

Instance identity is bound into the plan and evidence through an exact
application identity. This prevents a local-fixture run from being compatible
with real Agent/Judge evidence even when both use the same DCI package and task
declarations.

The generic runner executes complete exact suites and does not filter tasks.
Therefore every real single-task instance owns a one-task portable suite rather
than adding a DCI-specific task filter to generic planning. A planned catalog
entry maps to an existing package binding; it becomes `implemented` only when
its exact suite and application exposure also exist.

## CLI contract

The product adapter exposes:

```bash
asterion-dci benchmark instances [--json]

asterion-dci benchmark lock \
  --instance ID@VERSION \
  --output PATH

asterion-dci benchmark plan \
  --instance ID@VERSION \
  [--case-limit N | --all-cases]

asterion-dci benchmark run \
  --instance ID@VERSION \
  [--case-limit N | --all-cases] \
  --capability-source-lock PATH \
  --evidence-root PATH \
  --execute

asterion-dci benchmark resume \
  --instance ID@VERSION \
  --run-id ID \
  [--case-limit N | --all-cases] \
  --capability-source-lock PATH \
  --evidence-root PATH \
  --execute
```

`instances` and `plan` are metadata-only. `lock` reads public source metadata
and verified portable payloads without importing implementation providers. The
adapter expands the instance into exact application and suite selectors before
delegating to the generic CLI.

Omitting both range options selects one case. `--case-limit N` selects the first
positive bounded N cases under the instance's declared ordering.
`--all-cases` is allowed only for an instance with exact all-case resolution.
The product host inspects local dataset metadata, resolves a finite integer,
and binds it into authorization and the typed plan. No infinity, wildcard, or
implicit full-run value enters generic public values.

## Host components

### Instance catalog

`asterion.applications.dci_agent_lite.benchmark_instances` owns immutable
`DciBenchmarkInstance` values, exact selection, stable public summaries, and
implemented/planned gating. It contains no credentials, private paths, prompt
bodies, or mutable verification status.

### Source-lock writer

`benchmark_source_lock` discovers public package candidates through explicit
generic sources, opens the selected portable payload, verifies identity, and
writes a canonical exact lock without loading the provider. It fails closed on
ambiguity. It does not invent built-in precedence.

### Authorization

`benchmark_authorization` creates opaque host-owned claims only from an
explicit `--execute` request after source-lock and operator preflight. A claim
is bound to:

- exact instance, application, and suite;
- exact case count;
- package ref, source ID, and payload digest;
- new-run or exact resume intent;
- an operator-host issuer identity.

Configuration, credentials, existing evidence, a source lock, or an amount do
not grant authority. Claims are non-serializable and have body-free
representations.

### DCI benchmark host

`benchmark_host` implements `BenchmarkCommandHost`. Planning remains
metadata-only. Execution:

1. validates the exact source lock;
2. loads private operator configuration after explicit execution intent;
3. performs local data/service readiness checks;
4. issues and validates the opaque authorization;
5. loads only the selected DCI package provider;
6. recreates exact benchmark bindings with private operator inputs;
7. constructs the generic runner, evidence store, cancellation signal, and
   selected executor;
8. returns only the body-free public run result.

Resume reuses the same flow and additionally requires exact run compatibility.

### Executors

`benchmark_executor` provides two implementations of the generic
`BenchmarkTaskExecutor` protocol.

The local executor validates the real DCI invocation payload and emits
deterministic progress and result metadata. It performs no provider, Judge,
network, or external-dataset operation. It exists to make every installation
and CI run prove the entire host/runner/evidence/resume path.

The real executor translates the invocation into existing DCI benchmark
requests, reusing the current runtime, Agent, dataset, corpus, evaluation, and
Judge implementation. It does not reproduce those workflows. The first real
mapping is `qa.bamboogle.github-sample50`; its full range is exactly 50 cases.

## Data flow

```text
DCI instance selector
  → exact application/suite/task identity
  → source-lock validation
  → private operator preflight
  → explicit execution authorization
  → selected DCI package provider
  → private dataset/corpus/model/Judge binding
  → generic BenchmarkRunner
  → local or real DCI task executor
  → private BenchmarkEvidenceStore
  → body-free public result
```

The real executor may access operator-owned files, Agent and Judge providers,
and the network because that is the purpose of a real DCI instance. Cost is
controlled by an exact finite sample selection and explicit execution intent,
not by disabling real dependencies.

## Evidence and resume

Evidence remains private, immutable, and descriptor-bound. Compatibility
includes:

- instance/application identity;
- suite and ordered tasks;
- finite case selection;
- package source locks and payload digests;
- run ID;
- executor profile.

A completed compatible run is returned without repeating Agent/Judge work.
Partial compatible evidence resumes at the next task or case supported by the
existing DCI execution contract. Mismatched local/real profiles, changed case
counts, changed source locks, replaced datasets, or a different run ID fail
before provider work.

## Failure, cancellation, and privacy

- Missing or ambiguous sources fail before provider import.
- Missing data, corpus, credentials, runtime, or Judge readiness fails before
  Agent execution.
- Execution is sequential and has no automatic retry.
- Failure and cancellation close task and run evidence with one terminal state.
- Public output and exceptions omit prompts, answers, credentials, provider
  payloads, corpus text, raw output, host-service values, private paths, and
  optional amount.
- Sentinel-secret tests cover argument parsing, preflight, authorization,
  provider loading, executor failures, evidence, and resume.
- The local fixture is never labelled as real benchmark or paper evidence.
- A bounded real run is `External-limited` unless its named command actually
  passes. Full verification requires a separately authorized complete run.

## Instance backlog

`docs/status/DCI-BENCHMARK-INSTANCES.md` is the human-readable delivery ledger
and is registered in `docs/status/INDEX.md`. It records every exact instance,
task/suite mapping, implementation state, verification state, cost class,
named verification command, and evidence commit.

Allowed verification labels are:

- `Not rerun`;
- `Verified-local`;
- `External-limited`;
- `Verified-bounded`;
- `Verified-full`.

`Implemented` is a separate state and never implies verification. Repository
tests compare the ledger against the product catalog, the fifteen package
bindings, and the three suite manifests. An instance without named passing
evidence cannot be promoted to `Verified-bounded` or `Verified-full`.

The expansion order begins:

1. `dci.local-fixture@1.0.0`;
2. `dci.qa.bamboogle.github-sample50@1.0.0`;
3. the remaining fourteen task instances in canonical task-ID order.

## Verification strategy

All behavior changes follow test-first RED/GREEN cycles.

Provider-free gates prove:

- catalog identity, ordering, immutability, and redaction;
- catalog/package/suite/backlog closure;
- source-lock generation and ambiguity rejection;
- authorization binding and unforgeability;
- installed-wheel local `plan`, `run`, evidence, and `resume`;
- cancellation and failure terminal evidence;
- local/real resume incompatibility;
- public-output redaction;
- `--all-cases` resolving to exactly 50 for the Bamboogle instance without
  invoking a provider.

The real bounded gate runs:

```bash
asterion-dci benchmark run \
  --instance dci.qa.bamboogle.github-sample50@1.0.0 \
  --case-limit 1 \
  --capability-source-lock PATH \
  --evidence-root PATH \
  --execute
```

It must use real operator-owned Bamboogle data, corpus, Agent credentials, and
independent Judge configuration. If an external prerequisite is unavailable,
the result is reported as `External-limited`; it is never converted to PASS.

Repository closure requires:

```bash
uv run python -m unittest discover -s tests -v
make test
make lint
make docs-check
make check
make promotion-check
```

Promotion remains provider-free and reports zero provider operations and no
full dataset.

## Delivery phases

1. Add the exact instance catalog, CLI listing, and backlog consistency gate.
2. Add metadata-only exact source-lock generation.
3. Add opaque product authorization and the production DCI host.
4. Close installed-wheel local fixture plan/run/evidence/resume.
5. Add real Bamboogle operator preflight and executor translation.
6. Run the explicitly authorized real `case-limit=1` gate.
7. Add exact `--all-cases=50` planning/authorization without executing all 50.
8. Run complete repository, promotion, privacy, and independent review gates.
9. Advance the remaining instance backlog one exact DCI task at a time.

## Non-goals

- No DCI imports in generic benchmark modules.
- No new generic or DCI task loop.
- No source scanning, source precedence, registry, or version ranges.
- No credentials, paths, prompts, commands, or mutable state in portable
  manifests.
- No automatic real-provider execution in tests or promotion.
- No claim that local fixture or one-case evidence reproduces a paper score.
- No execution of all 50 Bamboogle cases without a separate explicit request.
