# Asterion Prime Capability Program

## Decision

Asterion Prime reproduces Prime Agent's semantic RLM-harness core, not its
complete CLI/TUI, authentication, model catalog, or operator UX surface.
The pinned Prime checkout remains read-only.  Prime's persistent IPython,
session, and RLM machinery remain in the TypeScript Gateway; provider-neutral
authority, budgets, journals, evidence, and public-safe projections remain in
Python.

`Smoke Core` is a narrow regression gate.  It is neither the Prime product
roadmap nor evidence for broader capability claims.

## Cross-cutting semantic invariants

Every acceptance product below requires all three invariants:

1. **IPython-only action surface.**  `ipython` is the sole built-in model
   action.  Files, shell commands, tools, skills, data, and task state are
   reached programmatically from its persistent kernel.
2. **Recursive Language Model.**  `rlm(...)` admits asynchronous child
   sessions and returns a stable handle.  Child results travel only via explicit
   message or artifact paths; identities, depth, model selection, cancellation,
   lifecycle, and usage remain exact and attributable.
3. **Continual Harness.**  Prompt notes, memories, skills, and subagent
   specifications are typed, versioned, evidence-backed state.  The immutable
   base prompt is never modified; revisions are isolated and rollbackable.

The host, not model-generated Python, owns authority, provider choice,
credentials, budgets, transcript persistence, schedules, and public evidence.

## Safety boundary

The Prime IPython kernel can otherwise execute arbitrary project commands with
its worker identity.  Formal acceptance therefore runs only in an explicitly
injected restricted worker/sandbox profile with a disposable mount, enforced
network policy, deadlines, output limits, and no operator credentials.  The
Rust controlled executor is command policy, not an OS sandbox, and cannot
satisfy this requirement.  A trusted-local profile may be offered for operator
experimentation but can never produce sandboxed acceptance evidence.

## Seven end-to-end acceptance products

### 1. `prime.ipython-coding/v1`

In a disposable repository, the model uses only IPython to inspect, edit, test,
and repair a bounded defect.  Kernel namespace, imports, functions, cwd, and
files survive turns and compaction.  PASS requires a named test oracle, bounded
reviewable diff, public-safe receipt, and cleanup.

### 2. `prime.programmatic-long-context/v1`

Task corpus and history reside in files or kernel values.  The model writes
code to select, aggregate, and validate relevant evidence rather than copying
the corpus into active context.  A fixed verifier checks the answer; public
outputs never expose corpus text.

### 3. `prime.recursive-workflow/v1`

A root session admits independent bounded children, continues local work,
receives explicit messages or artifacts, follows up with retained children,
and deletes them after an oracle-checked aggregation.  PASS requires exact
depth/model/budget attribution and no unbound child effect.

### 4. `prime.long-session-continuity/v1`

An active task detaches, attaches with exact replay, compacts, and survives a
worker/supervisor recovery to complete the same oracle.  Session identity,
goal, recoverable child registry, and artifacts persist.  Arbitrary live Python
objects and external processes are reconstructed only from saved artifacts or
external services; uncertain effects are fenced and never replayed blindly.

### 5. `prime.bounded-autonomy/v1`

A persistent goal runs under exact turn, token, cost, and time ceilings.  A
deterministic quality gate feeds a failure back to the task, and an unchanged
workspace prevents repeated gate execution.  PASS requires both a valid task
terminal and a passing gate.

### 6. `prime.continual-improvement/v1`

The four harness kinds support CRUD in local, project, and explicitly approved
global scopes.  Evidence from task A creates one small candidate revision;
holdout task B must demonstrate improvement or non-regression.  Snapshots and
an exact inverse rollback restore the prior state.  Global activation requires
operator approval.

### 7. `prime.arc-agi-3/v1`

Each game runs in a fresh isolated session and sandbox.  The model reaches the
game only through an IPython-imported broker exposing `observe`, `status`, and
`act`; the game SDK, engine source, other games, previous runs, network, and
provider credentials are unavailable.  Action shape/caps, score replay, and
public-safe evidence are exact.  A bounded public-subset functional gate and a
separately authorized full multi-game reproduction are distinct evidence levels.

## Product boundary

Add `src/asterion/applications/prime_agent/` for exact application assemblies,
restricted-worker presets, acceptance runners, and scenario adapters.  Keep
manifests compatibility-only: no commands, paths, credentials, environment
values, mutable state, or provider configuration.  The TypeScript Gateway
translates Prime typed host requests and events; it never authorizes effects or
chooses model, scope, budget, or authority.

## Delivery order

1. Freeze contracts, evidence ladder, upstream lock, and sandbox profile.
2. Deliver the runnable Prime application and IPython-only coding acceptance.
3. Deliver long-context processing, then recursive workflow and accounting.
4. Deliver continuity/recovery, then bounded autonomy.
5. Deliver Continual Harness refinement and rollback.
6. Deliver ARC-AGI-3 adapter and bounded functional subset; full reproduction
   needs separate explicit cost authorization.

Every phase supplies provider-free contract, fault, immutability, and redaction
tests plus one named bounded end-to-end receipt.  `make test`, `make check`,
and promotion checks remain provider-free.

## Non-goals

- Full Prime CLI/TUI, login, provider catalog, and settings parity.
- A Python reimplementation of Prime's Jupyter kernel or RLM runtime.
- Treating a trusted-local run, a provider-free test, or ARC subset evidence as
  a sandboxed/full-benchmark PASS.
