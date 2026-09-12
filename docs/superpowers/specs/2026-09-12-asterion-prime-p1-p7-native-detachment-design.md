# Asterion Prime P1-P7 Native Detachment Design

**Date:** 2026-09-12  
**Status:** Approved in conversation; written review pending  
**Authority:** This design extends the approved P7 native reset to every P1-P7 application.

## Decision

Asterion Prime has one formal implementation path. P7 already established that
path; P1 through P6 must be rebuilt on it. Formal execution, packaging,
preflight, verification, and evidence must not import, dynamically load,
launch, inspect, source-lock, or require Prime Agent source code or its SDK.

Prime Agent may exist only outside the Asterion execution trust boundary as a
black-box historical baseline. A neutral comparison tool may read an exported
log. It may not accept a Prime checkout locator or start a Prime process.

The current P1 implementation is not native acceptance evidence because its
operator launches modules from a Prime Agent source tree. Existing P1-P6
Prime-backed results are historical compatibility evidence only.

## Supersession

This design preserves the architectural decision in
`2026-09-08-asterion-prime-native-p7-reset-design.md` and makes it global.

It supersedes:

- every P1-P6 design or plan clause that requires a Prime source root, Prime
  SDK, Prime Gateway execution session, Prime artifact lock, or Prime internal
  compaction module;
- native-completion claims derived from those paths; and
- the contradictory parts of
  `2026-09-10-asterion-prime-native-p1-shared-kernel-design.md` and its plan
  where the written source-detachment rule and the planned source-root
  execution disagree.

Behavioral requirements, task fixtures, oracles, budgets, and historical
results remain useful references only when they are independent of Prime
execution code.

## Product boundary

The formal dependency direction is:

```text
CLI / operator host
  -> prime-applications provider
  -> selected P1-P7 application assembly
  -> Asterion runner
  -> asterion.prime runtime
  -> Asterion-owned session, control, tool, and evidence services
  -> separately pinned Pi runtime
```

The separately pinned Pi runtime is an allowed foundation already established
by the P7 reset. A Prime Agent checkout is not the Pi runtime and cannot be
reintroduced under a Pi label.

Python continues to own orchestration, composition, assembly, control,
recovery, and execution. TypeScript may implement Asterion-owned Pi extension
or Node integration code. Rust remains responsible for controlled execution.
No language introduces a second composer or application runner.

## Forbidden dependencies

Formal P1-P7 paths must contain none of the following:

- a Prime checkout locator or source-root environment variable;
- imports or dynamic imports from Prime Agent packages or build output;
- Prime SDK session, daemon, child-agent, model-registry, settings, resource,
  auth, compaction, or tool implementation;
- Prime Gateway bridges that execute an application through those internals;
- preparation or setup commands for Prime Agent;
- artifact or source locks whose subject is Prime Agent;
- package data or entry points for a Prime-backed provider/runtime; or
- tests that require a Prime checkout to pass.

The rule is semantic, not string-specific. Renaming or relocating a checkout
does not make it an allowed dependency.

## Distribution and entry points

The distributed application provider is `prime-applications`. The formal agent
runtime is `asterion.prime`.

The following legacy release surfaces are removed rather than retained as
fallbacks:

- the `prime-agent` application-provider entry point;
- the `prime.agent` runtime entry point;
- P1-P7 Make and CLI targets that select either legacy entry point;
- Prime setup/preparation commands used by those targets; and
- packaged SDK/Gateway execution resources and Prime source locks.

Missing native capability returns an explicit unavailable result. It never
falls back to Prime Agent.

Before an application is migrated, its selector is omitted from
`prime-applications` and from `asterion.application_index`; metadata lookup
therefore rejects it as unavailable before importing a runtime or starting a
process. No executable unavailable stub is added. The exact selector is added
back only with its native package and installed-route witness.

## Exact native application map

All application versions remain `1.0.0`, all assemblies use runtime
`asterion.prime`, and all paths below are wheel-owned resources.

| Phase | Application ID | Capability package ID | Assembly path | Required injected host services | Formal Make preset |
|---|---|---|---|---|---|
| P1 | `prime.ipython-coding` | `prime-ipython-coding-native` | `src/asterion/applications/prime/assemblies/prime-ipython-coding.json` | `prime.ipython`, `prime.p1-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | `asterion-prime-p1-run` |
| P2 | `prime.programmatic-long-context` | `prime-programmatic-long-context-native` | `src/asterion/applications/prime/assemblies/prime-programmatic-long-context.json` | `prime.ipython`, `prime.p2-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | `asterion-prime-p2-run` |
| P3 | `prime.recursive-workflow` | `prime-recursive-workflow-native` | `src/asterion/applications/prime/assemblies/prime-recursive-workflow.json` | `prime.child-runner`, `prime.p3-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | `asterion-prime-p3-run` |
| P4 | `prime.long-session-continuity` | `prime-long-session-continuity-native` | `src/asterion/applications/prime/assemblies/prime-long-session-continuity.json` | `prime.continuity-store`, `prime.p4-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | `asterion-prime-p4-run` |
| P5 | `prime.bounded-autonomy` | `prime-bounded-autonomy-native` | `src/asterion/applications/prime/assemblies/prime-bounded-autonomy.json` | `prime.ipython`, `prime.p5-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | `asterion-prime-p5-run` |
| P6 | `prime.continual-improvement` | `prime-continual-improvement-native` | `src/asterion/applications/prime/assemblies/prime-continual-improvement.json` | `prime.candidate-store`, `prime.p6-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend` | `asterion-prime-p6-run` |
| P7 | `prime.arc-agi-3-solving` | `prime-arc-agi-3-solver` | `src/asterion/applications/prime/assemblies/prime-arc-agi-3-solving.json` | `prime.arc-broker`, `prime.ipython`, `prime.pi-extension`, `prime.private-trace` | `asterion-prime-p7-solve` |

Each new package lives at
`src/asterion/capabilities/<package_id_with_underscores>/payload/` with the
same application capability ID and exact version. The package owns only its
application capability and implementation bindings; shared session behavior
stays in the Asterion Prime substrate.

The service names in this table are closed application-integration names for
the migration. A service may be implemented by reusing a narrower existing
Asterion protocol, but the assembly must not substitute a legacy
`*-development` host-service entry point.

## Legacy release-surface inventory

Removal is complete only when the following owned surfaces no longer expose a
Prime-backed execution edge:

- `pyproject.toml`: `prime-agent` application provider, legacy application
  index rows, `model.bounded-session`, every `prime.*-development` or
  `prime.ipython-production` host-service entry point, Prime operator artifacts,
  and `prime-gateway`/`control.providers.prime` force-includes;
- `src/asterion/applications/prime_agent/`: provider, assemblies, runtime
  binding, source lock, preparation, CLI hosts, SDK providers, gateways, and
  execution operators;
- `src/asterion/applications/first_party_packages.py`: the
  `PRIME_AGENT_PACKAGE` registration and factory;
- `src/asterion/capabilities/prime_agent/`: the legacy aggregate package;
- `src/asterion/runtimes/prime_agent.py`: the legacy runtime;
- `src/asterion/control/providers/prime/`: Prime Gateway control provider and
  packaged execution resources;
- `packages/typescript/prime-gateway/`: SDK/source-coupled application
  sessions, bridges, daemon launchers, and their build/test entry points;
- `Makefile`: Prime setup/check variables and targets, `prime-p1-run` through
  `prime-p7-run`, source-root propagation, and legacy gateway checks;
- `tools/`: setup, preparation, promotion, smoke, and bounded-loop commands
  that locate or launch a Prime checkout; and
- tests and fixtures whose success requires Prime source or whose expected
  selector is `prime-agent`/`prime.agent`.

Source-independent schemas, generic control protocols, and neutral log
comparison code are retained only after an import and package-data audit proves
they have no execution edge to the removed surfaces.

The current `asterion-prime-p7-solve` is retained as a research preset but must
be converted to an installed-wheel invocation. `asterion-prime-p1-run` is
replaced with a new native operator invocation rather than patched around its
current source-root preflight. P2-P6 receive equivalent installed-wheel presets
when their selectors return.

## Shared native substrate

P7 is the implementation anchor. P1-P6 extend the existing Asterion Prime
path; they do not create a parallel agent/runtime.

The shared substrate has one implementation of each responsibility:

- reusable Pi session lifecycle: prompts, normalized events, deadlines,
  cancellation, and close;
- Asterion control/session backend: admission, budgets, persistence, recovery
  fences, and safe state projection;
- Asterion-owned tool integration: exact injected host services, restricted
  workers, immutable inputs/results, and effect classification;
- Asterion runner boundary: resolved plan, exact implementations, cancellation
  signal, and read-only host services;
- private trace and public receipt infrastructure; and
- provider/model configuration injection by the operator, never by framework
  modules.

Applications supply assemblies, policies, prompts, application services, and
oracles. They do not own another runner or session engine.

## Reuse versus rewrite

The execution spine is rewritten. Domain-neutral or Asterion-owned components
are retained when their behavior is independently verified.

Retain where applicable:

- task definitions and deterministic fixtures;
- application oracles and scoring;
- restricted workers and process ownership;
- budgets, authority records, coordination, receipts, and redaction;
- generic Asterion control/recovery code; and
- neutral external-log normalization.

Retire rather than incrementally adapt:

- `applications/prime_agent` P1-P7 execution operators;
- Prime SDK development sessions and bridges;
- shared Prime development preparation/source-lock flow; and
- application contracts carrying a Prime source root.

This avoids both a full rewrite of proven domain logic and a partial retrofit
that leaves the forbidden trust boundary embedded in interfaces.

## Application migration

### P7: ARC-AGI-3 solving

P7 remains the native reference application. Its application logic is not
rewritten. It must pass the expanded source-detachment, wheel, installed-route,
and focused native regression gates after all legacy release surfaces are
removed.

### P1: persistent IPython coding

Retain the Asterion-owned task, worker, oracle, coordination, receipt, and
generic control/backend components. Replace the operator preflight, Pi launch,
session integration, context compaction, extension dependency injection, and
live acceptance. No Prime internal module may supply compaction semantics.
In particular, the existing `_PRICE_PROBE`, `_pi_command`, `source_root`,
`ASTERION_PRIME_SOURCE_ROOT`, `packages/coding-agent/dist/main.js` launch,
Prime compaction imports, and `asterion.control.providers.prime` artifact lock
are removed. The replacement resolves only an Asterion-owned Pi distribution
and Asterion-owned extension resources.

### P2: programmatic long context

Build on P1's native persistent session and Asterion-owned context service.
Programmatic context processing is an application capability, not a Prime SDK
session wrapper.

### P4: long-session continuity

Build detach, checkpoint, attach, and recovery on the native P2 context and
control substrate. This phase owns genuine cross-process recovery semantics;
it does not import a Prime daemon or client.

### P3: recursive workflow

Use an Asterion-owned session factory and controlled child runner. Preserve
depth, concurrency, budget, and cancellation limits without importing Prime
RLM or child-session APIs.

### P5: bounded autonomy

Compose native tool execution, child work, verification, and recovery into a
finite propose/verify/repair loop. It must have exact stopping conditions and
must not inherit an SDK agent loop.

### P6: continual improvement

Compose the preceding native capabilities into bounded evaluation, candidate
change, and explicit promotion. Prior evidence or cached configuration never
grants execution or promotion authority.

## Migration order

The implementation order is:

1. remove or disable forbidden release and execution surfaces;
2. expand the source-detachment and distribution gate;
3. revalidate P7 as the native anchor;
4. rebuild P1;
5. rebuild P2;
6. rebuild P4;
7. rebuild P3;
8. rebuild P5; and
9. rebuild P6.

An application becomes available only when its native installed route passes.
Intermediate unavailability is preferable to a legacy fallback or false native
claim.

## Failure behavior

- Missing native implementation: explicit `unavailable`; no model or worker
  starts.
- Pre-execution contract failure: safe rejection before side effects.
- Failure after dispatch with uncertain effects: `recovery-required`; no
  automatic replay or retry.
- Oracle failure: application failure, not framework or runtime success.
- Cancellation: bounded cleanup with one terminal result.

Public output must not include prompts, model prose, generated code, worker
output, credentials, provider bodies, private paths, source locations, or raw
external logs.

## Source-detachment gate

The authoritative gate scans every Asterion-owned release surface, including:

- Python and TypeScript implementation paths;
- Makefile and command launchers;
- `pyproject.toml` entry points and package-data mappings;
- application assemblies and provider registrations;
- packaged JavaScript and JSON resources;
- generated wheel and sdist contents; and
- commands captured from installed-route tests.

It detects checkout locators and forbidden execution edges, not only one
literal directory name. The distribution test runs with no Prime checkout and
no Prime source environment variable. The renamed external baseline directory
is outside the test and execution inputs and is never inspected.

## Verification strategy

This is research development, not a production release exercise. Verification
is proportional and focused.

For each application:

1. run small boundary tests for identity, authority, budget, cancellation,
   failure closure, immutability, and redaction;
2. build a wheel and run one provider-free installed-route closed loop without
   a Prime checkout;
3. run the focused P7 native-anchor regression when shared substrate changes;
4. only after those pass, run one fixed bounded live preset; and
5. record the exact evidence boundary without promoting unrun checks.

The prior multi-thousand-test promotion suite is not a P1-P7 research gate.
Broad checks are reserved for a later explicit release decision.

### Minimal application witnesses

These are narrow research witnesses, not exhaustive matrices:

- P1: two model-driven cells share one restricted worker; immutable stage-one
  file bytes survive Asterion-owned context compaction and host reconstruction;
  the final oracle passes and cleanup precedes the public terminal.
- P2: source material remains outside the prompt; the model performs at least
  one bounded programmatic retrieval/transform through an injected service;
  the answer oracle passes within the context and cost caps.
- P3: one root run starts an admitted child through `prime.child-runner`, the
  child result is joined into the root result, and exact depth/concurrency/
  budget limits reject further spawning without Prime RLM APIs.
- P4: a committed checkpoint is detached, the controlling process is replaced,
  the new host attaches with a higher generation, and continuation completes
  without replaying a committed effect.
- P5: a finite propose/verify/repair run performs at least one failed
  verification and one bounded repair, then stops on success or the exact
  iteration cap with no autonomous continuation afterward.
- P6: a candidate is evaluated against a fixed baseline, a non-improving
  candidate is rejected without promotion, and an improving candidate requires
  an explicit admitted promotion action before becoming current.
- P7: the installed native selector reaches the existing offline ARC broker,
  performs bounded model/tool/actions, and preserves the previously verified
  replay/score/cleanup evidence boundary.

Shared-substrate changes run only the relevant application witness plus the P7
provider-free native anchor. They do not trigger every live preset.

## Evidence correction

Status documents and inventories must distinguish:

- P7 native verified evidence;
- P1-P6 historical Prime-backed compatibility evidence;
- implemented-but-not-yet-live native components; and
- unavailable applications awaiting native replacement.

No historical Prime-backed result may be renamed or reclassified as native
evidence. The current Prime-backed P1 attempts are invalid as native acceptance
regardless of whether their command eventually succeeds.

## Completion criteria

The migration is complete only when:

- P1-P7 formal selectors resolve exclusively through `prime-applications` and
  `asterion.prime`;
- the legacy provider/runtime and SDK execution wrappers are absent from the
  distribution and formal command surface;
- wheel and installed-route tests pass with no Prime checkout;
- every P1-P7 application has a native provider-free closed-loop witness;
- each claimed live result comes from its native bounded preset; and
- the source-detachment gate covers the complete release surface and fails on
  representative forbidden references.

## Out of scope

- reproducing every undocumented Prime Agent internal behavior;
- keeping legacy execution working inside the Asterion distribution;
- production hardening or exhaustive release testing;
- full benchmark or paper reproduction; and
- changing the closed Asterion v1 protocols unless a later phase proves it is
  unavoidable.
