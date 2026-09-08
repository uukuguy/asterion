# Asterion-Prime P7 Reset Design

**Date:** 2026-09-08  
**Status:** Approved for planning  
**First delivery:** Asterion-owned ARC-AGI-3 LS20 level-one solve

## Decision

Asterion-prime is Asterion's Prime-style agent implementation built on the
existing Pi foundation. It is a peer of `asterion-native`: both consume the
same Asterion framework contracts, support Asterion capability packages, and
may operate portfolios of assembled applications. P1 through P7 are
applications of Asterion-prime, not the agent implementation itself. Asterion
implementation code and release artifacts
must not import, dynamically load, launch, inspect, source-lock, or require
Prime Agent source code or its SDK. Prime Agent may run only as an external
black-box baseline whose exported log is converted into a neutral comparison
format outside the Asterion execution path.

The first delivery is a vertical native P7 slice: Asterion-prime must use
DeepSeek V4 Flash through Asterion's existing Pi integration to solve the first
level of the public offline `ls20-9607627b` ARC-AGI-3 game without a supplied
answer or prescribed action sequence. The same native Pi, session, IPython,
evidence, and control foundations then become the only implementation path for
P1 through P6.

This design supersedes the runtime and completion claims in:

- `2026-09-02-asterion-prime-capability-program-design.md` where they retain
  Prime's session, IPython, or RLM implementation;
- `2026-09-04-prime-p7-arc-agi-3-design.md`;
- `2026-09-07-prime-p7-real-solving-design.md`; and
- every status or parity claim whose evidence requires a real Prime SDK
  session or an external Prime source checkout.

Existing wrapper results remain historical compatibility experiments. They are
not evidence that Asterion implements Prime-style capabilities.

In this document, “Asterion-owned” means implemented without Prime Agent
source or SDK. It does not mean the separate peer product `asterion-native`.

## Product and source boundary

The authoritative implementation remains the wheel rooted at `pyproject.toml`
and `src/asterion/`, together with its shipped TypeScript and Rust packages.
Those artifacts may depend on the separately pinned Pi runtime already defined
by Asterion, but they may not depend on Prime Agent.

The following are forbidden from Asterion implementation and release paths:

- Prime Agent SDK session factories, managers, registries, compaction, RLM, or
  tool implementations;
- `primeSourceRoot` or an equivalent Prime checkout locator;
- imports or dynamic imports resolved from a Prime Agent checkout;
- source, module, or artifact locks whose subject is Prime Agent;
- preparation, build, or launch steps for Prime Agent; and
- tests that can pass only when Prime Agent source is present.

The product name `asterion-prime`, its P1-P7 application identities, and neutral
behavioral vocabulary may remain. Naming a capability does not create a source
dependency.

Prime Agent comparison is strictly external:

```text
official Prime Agent process -> exported baseline log
                                      |
                                      v
                            neutral log normalizer
                                      |
Asterion-prime private trace ----------+-> differential report
```

The external baseline process has no import, callback, control, or execution
edge into Asterion.

## Existing Asterion architecture

Pi is Asterion's established bottom-level agent framework. It owns the model
conversation, tool-use loop, provider/model selection, session behavior, and
context handling exposed through its JSONL-RPC and extension interfaces.
Asterion owns application composition, runtime selection, host-service
injection, authority, budgets, process lifecycle, evidence, and public-safe
projection.

The ownership and execution direction remains:

```text
CLI/operator host
  -> exact agent system
  -> selected peer agent implementation
       +-> asterion-prime
       `-> asterion-native
  -> public Asterion control contract
  -> canonical journal, authority, and admission
  -> exact application assembly
       <- exact Asterion capability packages
  -> Asterion runner
  -> selected peer AgentRuntime implementation and injected host services
```

Python remains the sole orchestration, composition, assembly, and execution
owner. TypeScript supplies Pi extension and Node integration code; it does not
create a second composer or runner. Rust remains limited to controlled
execution. The application runner receives an already resolved plan, runtime,
implementations, cancellation signal, and read-only host services; it does not
discover, authorize, retry, persist, schedule, or select a model.

## Asterion-prime agent boundary

The missing product is an Asterion-owned `asterion-prime` agent implementation
at the same architectural level as `asterion-native`. It provides the reusable
Prime-style semantics that the current wrapper delegates to Prime Agent while
consuming only public Asterion framework, capability-package, assembly, runner,
runtime, control, and host-service contracts. P1 through P7 configure and
exercise this agent; they must not each recreate it.

An agent implementation can participate through both orthogonal Asterion
contracts:

- `AgentRuntimeClient` executes one already composed application request; and
- `ControlPlaneClient` manages a long-running agent system that may propose
  execution of applications from its immutable portfolio.

The first P7 delivery exercises Asterion-prime through its `AgentRuntimeClient`
surface. Later long-running and recursive applications also exercise its
`ControlPlaneClient` surface. Both surfaces belong to the same peer
Asterion-prime product and share its private session semantics; neither may
delegate those semantics to Prime Agent.

The Asterion-prime agent owns:

- session creation, lifecycle, state, immutable event publication, and exact
  terminal classification;
- application tool registration, allowlisting, activation, sequential tool
  execution, cancellation, and uncertain-effect handling;
- persistent conversation and application state over the Pi session;
- context accounting, compaction requests, summary replacement boundaries,
  and post-compaction continuity;
- parent/child session trees, bounded child creation, explicit family
  messaging, and result collection;
- detach/attach, checkpoints, recovery admission, and lease ownership;
- goal and bounded-autonomy state needed by applications;
- hooks for deterministic quality evaluation, evidence-backed improvement,
  rollback, and passive observation; and
- a closed private event interface through which the operator trace recorder
  can join model, tool, session, child, compaction, and application events.

The agent does not duplicate Pi's provider adapters, model inference loop, or
native message/tool protocol. It also does not duplicate Asterion composition,
capability packages, assemblies, runner execution, runtime adapters, host
services, credentials, or command authorization. Those remain in the common
Asterion framework, Pi, or the operator boundary as already assigned.

Implementation is split accordingly:

- genuinely domain-neutral Pi RPC, extension, session, and event translation
  belongs in the common Asterion runtime layer and is available equally to
  `asterion-prime`, `asterion-native`, and other products;
- Prime-style reusable session, child-agent, continuity, autonomy, and
  improvement semantics belong only in the peer Asterion-prime agent
  implementation; and
- ARC rules, frames, actions, scoring, and solve policy belong only to the P7
  application.

Asterion-prime completeness is a prerequisite for claiming native P1-P7
completion. The P7 vertical slice may initially exercise only the agent subset
it needs, but that proves the shared-framework integration and P7 application,
not the full Asterion-prime agent. The remaining agent contracts must be
implemented and verified before the full Asterion-prime program is complete.

## First delivery scope

The first delivery implements the smallest complete Asterion-owned
Asterion-prime slice
that consumes shared Asterion framework contracts and capability packages,
supports one real ARC application, and solves one real level. It includes:

1. a framework-level Pi RPC/session integration capable of loading exact,
   application-owned extensions and reporting their capabilities;
2. an Asterion-prime agent session using that integration, with exact tool,
   lifecycle, limit, cancellation, and private-event contracts;
3. an Asterion-prime Pi extension that registers only `ipython` for the P7
   application;
4. one persistent, restricted IPython worker owned by an injected host service;
5. the existing source-independent ARC broker behavior for `observe`, `status`,
   and validated `act` requests;
6. a private trace recorder joining Pi events, Asterion-prime agent events,
   IPython activity, and ARC transitions under one run identity;
7. a passive diagnostic analyzer and neutral baseline comparator;
8. an installed `prime.arc-agi-3-solving@1.0.0` route selecting
   `asterion.prime`, whose internal model/tool loop uses the common Pi
   integration;
   and
9. deletion of the Prime SDK P7 execution path and correction of false status
   claims.

P1-P6 application implementation and the agent contracts used only by those
applications are not part of this first code delivery. Their product goal is
unchanged: Asterion-prime is expanded and each application is reimplemented on
the same native Pi path after P7 proves the vertical architecture. No existing
Prime SDK-backed P1-P6 result retains native completion status while that work
is pending.

## Component design

### Pi foundation integration

The existing framework Pi integration remains the shared bottom-level model
and tool-loop foundation used internally by the first Asterion-prime slice. It
is not the application-selected `asterion.prime` runtime identity and is
equally available to peer agent implementations.
The generic Pi layer gains an exact mechanism for host-resolved application
extensions and tool capabilities. Manifests contain compatibility identities
only; extension paths, commands, credentials, provider configuration, and
mutable state remain operator-owned values supplied after preflight.

The reusable Pi RPC/session behavior currently embedded in DCI product code is
extracted only where it is genuinely domain-neutral. The Asterion-prime product
must not import DCI implementation modules. DCI and Asterion-prime consume one
framework Pi integration rather than maintaining separate process clients.

### Asterion-prime IPython extension

The P7 application owns a TypeScript Pi extension that registers one `ipython`
tool. The extension translates one Pi tool invocation into one request to an
already injected persistent-IPython host service. It does not choose or start a
worker, authorize code, read `.env`, access ARC directly, or persist evidence.

The model sees only the `ipython` tool. Inside the worker, the only game access
is an injected client exposing `observe()`, `status()`, and `act(actions)`.
Ordinary analysis libraries may be admitted by the worker profile. The worker
cannot import the ARC SDK, inspect engine source, access another game or prior
run, use the network, or read provider credentials.

### ARC broker

The broker owns one offline `ls20-9607627b` engine instance with seed zero. It
validates method names, request sequences, action names and data, available
actions, batch length, primitive-action ceiling, terminal state, and calls after
closure. Each primitive action is applied and journaled separately. A batch
stops immediately when the first level transition occurs.

The broker is authoritative for action count, level count, terminal reason,
score calculation, and deterministic replay. It supplies observations only to
the isolated worker. It supplies structured private transition records to the
operator trace recorder and allowlisted counters/digests to public evidence.

### Operator model integration

The operator integration resolves `.env`, Pi authentication, provider, and
model after application selection and before runtime construction. Framework
modules never read `.env` or credentials. The DeepSeek acceptance run selects
`deepseek-v4-flash`; the later Sol experiment selects `gpt-5.6-sol` through the
same Pi integration without changing P7 code, assembly, prompt, broker, or
evidence semantics.

The user-facing solve action remains one preset. It exposes no provider, model,
cost, token, action, callback, or deadline knobs. Finite controls are fixed by
the operator integration and reported through public-safe status.

## Solver behavior

The production solve prompt is game-agnostic and contains no answer, golden
action trace, target coordinates, known object identity, or level-specific
hint. It requires the agent to:

- inspect frames programmatically in persistent IPython;
- maintain player, objects, controls, hypotheses, rejected hypotheses, plan,
  and last-observation state;
- test uncertain controls with short experiments;
- compare observations before and after actions;
- reject known no-ops and death paths;
- revise its world model when evidence contradicts a hypothesis; and
- continue until the broker reports a level transition or a fixed limit ends
  the run.

Provider-free doubles may use deterministic actions to verify plumbing. Such
tests cannot satisfy the live-solving acceptance gate.

## Private execution trace

One operator-owned private trace joins every layer under exact run, session,
runtime, model, worker, broker, and game identities. It records, in causal
order:

- Pi session lifecycle and native event identity;
- model-visible messages and assistant-visible output;
- model callback and token usage facts;
- tool-call identity and submitted IPython code;
- bounded stdout, stderr, error, and tool result;
- compaction request, summary, replacement boundary, and continuity facts;
- every ARC primitive action and its before/after observation;
- action, callback, token, cost, and elapsed-time counters;
- derived spatial state, no-op streaks, state cycles, resource resets, resource
  losses, deaths, and completed-level transitions; and
- exact terminal classification and cleanup outcome.

Private entries form a contiguous, hash-chained journal. A committed entry is
immutable. Missing sequence positions, digest mismatches, conflicting
identities, oversized values, invalid encodings, or uncertain engine effects
fail closed. The recorder may retain raw prompts, tool code, and frames only in
the operator-authorized private root. Reprs, exceptions, stdout, public events,
receipts, Pathlight summaries, and packaged resources contain none of those
values.

## Passive diagnostics

The initial DeepSeek comparison run uses a passive analyzer. It may label a
trace but may not inject a message, alter a tool result, reset the game, retry a
turn, or stop an otherwise authorized run.

The analyzer reports at least:

- consecutive actions that do not move any key object;
- collapse to one repeated action;
- normalized state cycles after excluding purely decorative animation;
- resource-bar reset accompanied by a reserve/life decrement;
- actions since the latest level progress;
- continued use of a hypothesis after contradicting evidence; and
- estimated information gain for each experiment.

An online intervention policy is outside the first comparison run. It requires
separate design and evidence because intervention changes the solver being
compared.

## Neutral comparison

The official Prime Agent DeepSeek baseline remains an external artifact. A
normalizer converts both baseline and Asterion traces into a closed neutral
record containing only comparable semantics:

- model/provider identity and declared reasoning mode;
- turn, callback, tool-call, primitive-action, and level counters;
- normalized action sequence;
- frame/state digests and derived state transitions;
- hypothesis and replan markers derived from model-visible output when
  available;
- no-op, cycle, death, and resource-loss markers; and
- terminal outcome.

The differential report compares time and actions to identify controls, first
supported and rejected hypotheses, information-gain efficiency, no-op/death
repetition, replan latency, first-level completion, and total action count. It
does not require identical reasoning text or identical trajectories.

## Failure and cancellation semantics

Preflight rejects missing or mismatched Pi, extension, worker, broker, ARC
resource, model host, private evidence root, or finite-control identities before
starting model work. Runtime failures use stable content-free public errors and
retain private stage diagnostics.

Cancellation propagates from the runner to the Pi process, IPython worker, and
broker. Cleanup is shielded, bounded, and idempotent. An uncertain provider,
tool, or engine effect is journaled privately and cannot be replayed or retried
as though it were known. The runner itself never retries.

The first live preset permits one game, one Pi session, at most 500 primitive
actions, at most 128 model callbacks, and a 60-minute wall deadline. Limit
exhaustion is an unsuccessful attempt, never a PASS. The broker stops the run
immediately after the first authoritative level transition.

## Public result

The public runtime stream continues to satisfy
`asterion.agent-runtime/v1`: one run ID, contiguous sequences, matched tool
calls/results, and one terminal event. Public progress contains only allowlisted
phase, round, action-count, level-count, and terminal status.

On success, the local operator presentation may display the public puzzle's
initial grid, action sequence, solved-level frame, model/tool/action counts, and
partial score. The durable public receipt contains exact identities, counts,
fixed-decimal score, trace/replay digests, terminal reason, promotion state, and
cleanup assertions. It contains no prompts, model prose, provider bodies,
IPython code/output, credentials, raw engine output, or private paths.

## Removal and migration

The implementation plan must identify and remove or replace:

- the `prime.agent` AgentRuntime adapter when it invokes Prime SDK execution;
- Prime Gateway session and bridge code used for P1-P7 execution;
- P1-P7 `primeSourceRoot` propagation;
- Prime source, ecosystem-module, client-module, operational-module, and SDK
  artifact locks used as runtime or acceptance prerequisites;
- setup and preparation commands for Prime Agent;
- package-data and entry-point references to removed resources; and
- tests, documentation, Make targets, inventories, ledgers, and status claims
  that describe Prime SDK-backed results as Asterion-native completion.

Source-independent broker, restricted-worker, budget, scoring, replay,
receipt, presentation, and redaction components are retained or moved behind
the native Pi path. Wrapper-specific code is not retained for hypothetical
future development.

Deletion occurs after the corresponding native path has provider-free coverage
within the same implementation program, so failures remain attributable. The
final source-detachment gate is authoritative: no wrapper may remain in release
or acceptance paths merely because it once supplied compatibility evidence.

## Verification gates

### 1. Dependency and distribution gate

Build the sdist and wheel in an environment with no Prime checkout and no Prime
source environment variables. Inspect imports, entry points, package data, and
spawned commands. The gate fails on any Prime SDK/source dependency. Product
capability names alone are not failures.

### 2. Provider-free component gate

Use `unittest` and deterministic Pi/worker/engine doubles to cover success,
invalid identities, sequence gaps, malformed actions, batch stopping, action
cap, callback cap, deadline, cancellation at multiple stages, uncertain effects,
replay mismatch, cleanup, immutability, and sentinel-secret redaction.

### 3. Provider-free installed-route gate

Build and install the Asterion wheel outside the source tree. Select
`prime.arc-agi-3-solving@1.0.0`, compose it with `asterion.prime`, inject exact
fake host services, execute through the public runner, and verify the complete
runtime stream, private trace, public receipt, internal Pi binding, and zero
Prime source access.

### 4. DeepSeek live-solving gate

With separate finite operator authorization, run the installed route against
offline `ls20-9607627b` using `deepseek-v4-flash`. Supply no answer or action
sequence. PASS requires exactly one authoritative level transition within all
preset limits, successful deterministic replay, complete cleanup, and a sealed
private trace. A model call, valid action, nonzero score, or transport-complete
run without the level transition is not PASS.

### 5. Differential report gate

Normalize the sealed Asterion trace and the external official Prime Agent
DeepSeek baseline with the same versioned normalizer. Produce a deterministic
report covering the declared comparison fields. The report describes behavioral
differences; it neither grants PASS nor requires trajectory identity.

### 6. Sol experiment

After the DeepSeek gate and comparison are complete, an operator may run the
same installed route with `gpt-5.6-sol`. Only operator configuration changes.
The Sol result is separately reported and cannot replace missing DeepSeek
acceptance evidence.

### 7. Repository regression

Run focused Python and TypeScript tests, `make test`, `make lint`,
`make docs-check`, `make check`, and `make promotion-check` when package data,
entry points, schemas, or distribution assumptions change. A pre-existing or
external-limited failure remains explicitly classified and is never promoted.

## P1-P6 continuation

After P7 establishes the vertical path, the Asterion-prime agent is completed
incrementally and P1-P6 applications are reimplemented in this order on the
same native foundation:

1. P1 persistent IPython coding;
2. P2 programmatic long-context work;
3. P3 recursive child sessions and explicit messaging;
4. P4 detach/attach, compaction, recovery, and continuity;
5. P5 bounded autonomy with a deterministic quality gate; and
6. P6 evidence-backed continual improvement and rollback.

Each capability receives its own provider-free and, where necessary, bounded
provider gate. None imports Prime Agent, and none inherits completion status
from the deleted wrapper path. Full native P1-P7 completion requires every
named native gate and every agent contract above to pass; solving P7 alone
proves only the first Asterion-prime slice and application delivery.

## Completion criteria

The first delivery is complete only when all of the following are true:

- Asterion implementation and release artifacts have no Prime Agent source or
  SDK execution dependency;
- the installed P7 route selects the Asterion-prime AgentRuntime, uses the
  common Pi foundation internally, and receives only injected Asterion host
  services;
- provider-free and source-detached gates pass;
- DeepSeek V4 Flash autonomously completes the first LS20 level within the
  fixed preset;
- replay, trace sealing, cleanup, and public redaction pass;
- the neutral differential report against the official DeepSeek baseline is
  reproducible; and
- documentation and status accurately distinguish native implementation,
  verified evidence, failed attempts, and later P1-P6 work.

Anything less is Implemented, External-limited, Not rerun, or an unsuccessful
attempt as appropriate; it is not native P7 PASS.
