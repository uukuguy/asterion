# Asterion Prime Functional Parity Program Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver Asterion-supported Prime functional parity first through a Prime-managed control provider and then through an interchangeable Asterion-native kernel, beginning with a verifiable long-running closure and ending only when both named parity gates pass against pinned Prime commit `a18809e00ea30638584d87b3afea7285a9d7296c`.

**Architecture:** Add a neutral Python-owned long-running control plane above exact application assemblies. A TypeScript Prime Gateway and the later Python-owned native kernel implement the same closed `asterion.agent-control/v1` contract. The Asterion host retains system resolution, authority, admission, budgets, canonical state, application invocation and public evidence; each engine owns only its opaque continuation capsule.

**Tech Stack:** Python 3.12, TypeScript/Node.js, JSON Schema 2020-12, `unittest`, Ajv, Prime public RPC, existing Asterion assembly/runner/runtime/Pathlight surfaces, and Rust only where controlled execution or a separately approved execution-domain service requires it.

## Global Constraints

- Preserve `CLI/host -> selected provider -> assembly -> catalog/composer -> exact implementations -> runner -> runtime/host services`.
- Existing v1 capability, package, application-assembly and runtime contracts remain closed; long-running control uses new contracts above them.
- Python owns orchestration and canonical state; TypeScript validates shared contracts and owns the Prime Node boundary; Rust remains the controlled-execution boundary.
- Prime integration uses public RPC unless a separately documented, tested and capability-gated RPC gap proves a private daemon binding unavoidable.
- A control provider proposes work but never authorizes itself, expands its portfolio, injects host services or selects undeclared implementations.
- Public surfaces contain no prompts, answers, credentials, provider payloads, corpus text, raw output, host-service values, private paths or opaque capsule bodies.
- Command IDs, action idempotency keys, journal positions and receipts are persisted before acknowledgement. An uncertain external effect is reconciled or explicitly superseded; it is never retried blindly.
- Provider-free commands stay provider-free. Provider-backed and long-running verification requires an explicit finite authority and cost budget.
- `Implemented`, `Verified-loop`, `Verified-system-parity` and `Verified-native-parity` are distinct evidence levels. Only Phase 4 completion satisfies the full project objective.
- Each phase gets its own detailed plan before code changes; plans use RED/GREEN/refactor steps, atomic commits and named verification commands.

## Program Deliverables

| Phase | Detailed plan | Required exit | Cost/risk magnitude |
|---|---|---|---|
| 0 — Control-plane foundation | `2026-08-09-asterion-control-plane-foundation.md` | Fake provider proves a complete pause/resume/fault/recovery session without model/runtime access | 4–7 engineer-weeks; abstraction and recovery semantics |
| 1 — Prime verified loop | `2026-08-10-asterion-prime-verified-loop.md` | `Verified-loop`, including bounded Prime/RLM child work, portfolio invocation, detach/attach, checkpoint/recovery, cancellation, budget, redaction and fault injection | 8–14 engineer-weeks; RPC extension points and crash windows |
| 2 — Prime system parity | Create from the pinned parity ledger after Phase 1 | No missing mandatory pinned Prime feature and passing `Verified-system-parity` | 3–6 engineer-months; interface/ecosystem breadth |
| 3 — Native long-running kernel | Create after Phase 1 supplies a stable differential oracle | Native provider passes the common verified-loop suite and foundational parity domains | 5–9 engineer-months; persistent kernel and recursive consistency |
| 4 — Native full parity | Create from the same closed ledger after Phase 3 | No missing mandatory scenario and passing `Verified-native-parity` | 3–7 engineer-months; long-tail ecosystem and governance |

---

### Task 1: Deliver Phase 0 — Control-plane foundation

**Files:**
- Create/modify exactly as listed in `docs/superpowers/plans/2026-08-09-asterion-control-plane-foundation.md`.
- Update: `docs/superpowers/plans/2026-08-09-asterion-prime-parity-program.md` only to record achieved evidence, not to relax its gates.

**Interfaces:**
- Produces closed `asterion.agent-system/v1`, `asterion.control-plane/v1` and `asterion.agent-control/v1` contracts.
- Produces immutable system resolution, authority/admission, journal, state reducer, provider registry, conformance harness and safe Pathlight projection.
- Does not contact Prime, a model provider or an application runtime.

- [x] **Step 1: Execute the detailed Phase 0 plan task-by-task**

Run every focused RED/GREEN command and commit boundary named in the detailed plan.

- [x] **Step 2: Run the Phase 0 exit gate**

Run:

```bash
uv run python -m unittest -v tests.test_agent_system_protocol tests.test_agent_control_protocol tests.test_control_authority tests.test_control_journal tests.test_control_state tests.test_control_provider tests.test_control_host tests.test_control_pathlight
npm --prefix packages/typescript/asterion-runtime test
make test
make lint
make docs-check
make promotion-check
make check
```

Expected: all commands PASS provider-free. The fake provider scenario includes contiguous replay, one terminal event, pause/resume, recoverable fault, rejected unauthorized action, budget-limited behavior and sentinel redaction.

- [x] **Step 3: Record the evidence level honestly**

Record `control-plane-foundation: PASS`. Do not record `Verified-loop`, `Verified-system-parity`, `Verified-native-parity` or full Prime parity.

### Task 2: Deliver Phase 1 — Prime verifiable long-running closure

**Files:**
- Create: a dedicated Phase 1 design delta only if implementation discovers an approved conflict with the baseline design.
- Create: `docs/superpowers/plans/YYYY-MM-DD-asterion-prime-verified-loop.md`.
- Create: TypeScript Prime Gateway package and tests under `packages/typescript/`.
- Create: versioned Asterion Prime package/skill resources under the authoritative Asterion distribution.
- Create/modify: Python control-host adapter, capsule storage binding, application invocation bridge, common conformance tests and bounded verification runbook.
- Create: pinned Prime artifact metadata, compatibility matrix and parity-difference ledger.

**Interfaces:**
- Consumes Phase 0 `ControlPlaneClient`, commands/events, authority decisions, journal cursors and common conformance suite.
- Uses Prime public RPC with exact distribution version/digest and explicit feature negotiation.
- Produces `Verified-loop` evidence only after provider-free and bounded provider-backed commands pass.

- [x] **Step 1: Inventory and lock the public Prime RPC boundary**

Map every required Phase 1 operation to a documented RPC request/event, pin the exact Prime artifact and digest, and fail preflight on any missing capability. Keep RPC request IDs, Prime active-session IDs and Asterion session IDs distinct.

- [x] **Step 2: Write the detailed Phase 1 plan**

The plan must cover gateway process hygiene, authenticated session-private bridge, action admission, application receipts, RLM children, goal/autonomous continuation, cursor replay/resync, capsule sealing, crash-window reconciliation, cancellation cascade, finite budgets, redaction and Pathlight causality.

- [ ] **Step 3: Implement through the common provider conformance suite**

Start with a deterministic fake Prime RPC process, then the pinned local Prime build, then bounded model-backed verification. Every external-effect crash point must result in a proven receipt or `uncertain`.

Provider-free implementation and real-process fault coverage are complete. The
pinned local Prime preflight is currently `External-limited` on Node 23.11.0;
the approved compatibility boundary is Node 22.8.0 through 22.x. Bounded
model-backed verification remains unrun and this step therefore remains open.

- [ ] **Step 4: Run and publish the Verified-loop gate**

The named gate must prove goal continuation, an admitted portfolio invocation, recursive child work, detach/attach, checkpoint, host/gateway/worker crash recovery, root cancellation, budget exhaustion, public sentinel redaction and complete causal evidence. External-limited or not-rerun results remain non-PASS.

### Task 3: Deliver Phase 2 — Prime system parity

**Files:**
- Create: `docs/superpowers/plans/YYYY-MM-DD-asterion-prime-system-parity.md`.
- Create: machine-readable pinned parity ledger and scenario IDs under `tests/fixtures/prime-parity/`.
- Modify: Prime Gateway, Asterion Prime package, supported clients, settings/operations surfaces and documentation as demanded by the ledger.

**Interfaces:**
- Consumes the stable Phase 1 gateway and common conformance APIs.
- Produces Asterion-reachable equivalents for all pinned session/context, RLM, long-running, continual-harness, ecosystem and operations inventory items.
- Delegation to Prime is permitted; bypassing Asterion authority, identity, recovery or evidence is not.

- [ ] **Step 1: Convert the approved inventory into a closed parity ledger**

Give every feature a stable ID, Prime source/RPC evidence, Asterion entry point, deterministic conformance scenario, provider-backed requirement, status and compatibility impact. Classify only genuinely non-functional pixel/hidden-reasoning equivalence as excluded.

- [ ] **Step 2: Plan and implement parity domains in dependency order**

Use separate detailed subplans for: session/context tree; RLM/messaging; daemon/heartbeat/schedules; continual harness; skills/extensions/packages/MCP/providers; SDK/CLI/RPC/ACP/JSON/TUI/export/share; auth/settings/model/telemetry/doctor/update.

- [ ] **Step 3: Run the system-parity gate**

Require zero `missing` mandatory ledger entries, all common scenarios passing through Prime Gateway, bounded real-provider evidence where semantically required, and compatibility tests for the pinned build plus the next explicitly accepted build.

### Task 4: Deliver Phase 3 — Asterion-native long-running kernel

**Files:**
- Create: `docs/superpowers/plans/YYYY-MM-DD-asterion-native-kernel.md`.
- Create: native control provider modules under `src/asterion/control/providers/native/`.
- Create/modify: persistent controller environment, session/context tree, recursive child registry, provider-turn adapter, compaction, queues, autonomous policy, usage attribution, capsules and restart recovery.
- Reuse: application runner, runtime, host-service and common control-provider conformance surfaces; do not fork them.

**Interfaces:**
- Implements exactly the Phase 0 `ControlPlaneClient` contract.
- Uses Prime as a differential behavior oracle but does not copy Prime-private state into Asterion public contracts.
- Produces the same externally observable session, action, recovery, budget and evidence invariants as Phase 1.

- [ ] **Step 1: Write the native-kernel plan from common scenarios**

Partition storage, controller, program environment, recursive children, queues/context, autonomous policy and recovery into independently testable components with explicit crash boundaries.

- [ ] **Step 2: Implement provider-free before provider-backed behavior**

Use deterministic turn/model fakes and virtual clocks for all state/recovery behavior. Add bounded provider-backed tests only for semantics that cannot be established with fakes.

- [ ] **Step 3: Pass Verified-loop and foundational differential gates**

Compare public states, causal events, receipts, artifact projections, usage invariants and failures against Prime; never compare hidden reasoning or demand byte-identical text.

### Task 5: Deliver Phase 4 — Native full parity

**Files:**
- Create: `docs/superpowers/plans/YYYY-MM-DD-asterion-native-full-parity.md`.
- Modify: native provider and client/operations surfaces necessary to close every remaining mandatory ledger item.
- Modify: shared parity ledger only by adding evidence or an explicitly reviewed baseline-difference record.

**Interfaces:**
- Consumes the exact same parity scenarios used for `Verified-system-parity`.
- Produces native equivalents for remaining schedules, heartbeat, continual harness, ecosystem, integration, client and operational domains.

- [ ] **Step 1: Generate the remaining-gap plan from the ledger**

No manually curated subset is sufficient: the plan is the set of mandatory entries not yet passing under the native provider, ordered by dependency and risk.

- [ ] **Step 2: Implement and differentially verify every remaining domain**

Use virtual-clock long runs, repeated real-process restart/attach soak, extension collision matrices, credential-refresh redaction, continual-refinement rollback and resource/orphan audits.

- [ ] **Step 3: Run the final gate and close the objective**

Require zero missing mandatory native entries, passing common and differential scenarios, passing repository promotion checks, named finite provider-backed evidence, and no unresolved security/privacy/cost finding. Only then record `Verified-native-parity` and mark the full Prime-equivalence objective complete.

## Program Review Checklist

- [ ] The pinned Prime baseline has not moved silently.
- [ ] Each implementation phase has a detailed reviewed plan before code changes.
- [ ] Every verification label cites a named passing command and evidence boundary.
- [ ] Application assemblies remain deterministic exact units below the control plane.
- [ ] Prime and native providers pass the same mandatory public conformance scenarios.
- [ ] Public/private state separation and sentinel redaction are tested at every new boundary.
- [ ] Authority changes are monotonic journaled revisions; engine state never grants authority.
- [ ] Crash windows prove receipt, recovery or honest `uncertain` state without duplicate effects.
- [ ] Cost-bearing commands are bounded and separately authorized.
- [ ] Phase 0 or Phase 1 success has not been promoted to full parity.
