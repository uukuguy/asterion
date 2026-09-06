# Prime Seven-Scenario Closure Worklist

> Updated: 2026-09-06. Canonical active worklist for the Prime capability program.

## Goal and authority

Asterion is a unified agent framework integrating capability packages. Prime
and Native are parallel runtime implementations. The user explicitly selected
closure of the existing seven Prime end-to-end reproductions as the immediate
priority, before broad framework restructuring. Native completion is not a
dependency of this work.

The semantic contract is
`docs/superpowers/specs/2026-09-02-asterion-prime-capability-program-design.md`.
The older ten-application ordering in this file is superseded by these seven
scenarios; retained parity/Smoke evidence keeps its original scope. Existing
wire IDs (`prime.agent`, `asterion.prime-gateway`, `asterion.native`) retain
their respective runtime/control roles; this priority decision does not rename
or merge contracts.

## Closure matrix

| Package | Current evidence | Remaining closure | Dependencies / status |
|---|---|---|---|
| P1 `prime.ipython-coding/v1` | P1-A and P1-B real Prime SDK/provider/Docker/IPython/oracle/cleanup runs pass; the exact installed CLI route also completed five callbacks, two cells and cleanup | Production authority promotion remains a separate release task | **Development closure / CLI verified**. Standard exact-selector command exited 0 with an unpromoted safe trace and zero residue |
| P2 `prime.programmatic-long-context/v1` | One real installed CLI run completed two model callbacks, one Docker-backed IPython cell, fixed corpus oracle and cleanup | Production authority promotion and long-context scale remain separate release tasks | **Development closure / CLI verified**. Exact-selector command exited 0 with an unpromoted safe trace and zero residue |
| P3 `prime.recursive-workflow/v1` | Real installed CLI run completed two RLM children, retained review follow-up, ten model callbacks, four Docker-backed IPython cells, host oracle and cleanup | Production promotion remains a separate release task | **Development closure / CLI verified**. Exact-selector command exited 0 with an unpromoted safe trace and zero residue |
| P4 `prime.long-session-continuity/v1` | Installed CLI completed direct native daemon checkpoint, exact zero-gap reattach, compact, five model callbacks, two Docker IPython cells, same oracle and cleanup | Production promotion and crash/restart replay remain separate work | **Development closure / CLI verified**. Exact-selector command exited 0 with an unpromoted safe trace and zero residue |
| P5 `prime.bounded-autonomy/v1` | Installed CLI completed one Prime session, two completion-only Docker IPython actions, failed quality feedback, exact source repair, host result/quality gates and cleanup | Production promotion and broader autonomous task classes remain separate work | **Development closure / CLI verified**. Exact-selector command exited 0 with an unpromoted safe trace and zero residue |
| P6 `prime.continual-improvement/v1` | Installed CLI completed task-A/candidate/task-B execution, exact activation-or-rollback, worker evidence and cleanup; 19 Python tests, 2 TypeScript tests and Ruff passed | Production promotion remains a separate release task | **Development closure / CLI verified**. `PRIME_RUN_ID=prime-p6-20260906-final make prime-p6-run` exited 0 with scope `p6-development/unpromoted`, trace `sha256:51f6454e90a2286dfd0fabaa3f3cf7f7870cd57abf95890845b4efd01048b335`, and zero Prime P6 containers |
| P7 `prime.arc-agi-3/v1` | Game broker/score replay/worker/subset-full reducer tests pass | Real isolated game broker and IPython launcher with bounded public-subset functional evidence | **Active / next**. Depends on P1–P6; full multi-game reproduction remains a separate explicitly authorized finite scope |

Six of seven scenarios now have named development CLI closure; P7 remains active. Public
metadata, fixed fixtures, fake workers and compatibility probes are distinct
evidence layers, not alternate ways to close a scenario. P7 still lacks a
complete installed execution route; source-level test suites do not mean
production promotion.

## P1 closure record

1. **P1 resource aggregation — implemented and verified:** the planned opaque
   authority-executable child, canonical resource-set contribution and reverse
   cleanup are implemented. The 42-test focused group passed and Sol approved.
   Pure provider-free work; an empty production catalog continues to
   reject execution. Owner: Terra, with independent Sol review.
2. **P1 execution/deployment contract — bundle launch and qualification IPC verified:** use the reviewed Linux
   execution substrate for the trusted supervisor, application child and
   authority; bind service-manager identity, exact ELF launch and credential
   custody. Astra owns the decision; Sol independently checks feasibility.
   Docker availability alone is not this deployment proof. The reviewed proposal
   is `docs/superpowers/specs/2026-09-05-prime-seven-closure-execution-delta.md`:
   all-Linux processes, authority-owned listener and immutable Python runtime
   bundle with separately versioned executable/code identities. It does not
   modify current v1 receipt or enable launch. The exact bundle contract is
   `docs/superpowers/specs/2026-09-05-prime-authority-bundle-contract.md`; its
   inventory/profile and descriptor admission is implemented and Sol-approved.
   A real root-owned Linux CPython candidate (658 files, five external libraries)
   passed admission/revalidation/cleanup. Development Linux child launch is now
   implemented in `2e6022d`: real fd-exec, identity policy, fixed FD custody,
   cancellation and reaping; 13 focused launch tests pass. This is not full
   authority IPC or a P1 scenario PASS. The user's 2026-09-06 correction limits
   development verification to normal flows and key boundary assertions;
   exhaustive release matrices and repeated promotion are deferred. Next is the
   real worker/model integration. The authority-owned ready/execute/terminal
   qualification exchange is implemented: four focused Linux tests cover normal
   completion, cancellation, identity mismatch and FD handoff ownership. It
   issues no production receipt.
3. **P1-A real spine — development verified:** the private development hook now
   uses the actual Docker worker, killable two-turn model transport, real Prime
   SDK `session.prompt()`, one `ipython` callback, trusted oracle and cleanup.
   The host-side Node Gateway owns SDK session semantics; Python owns admission,
   budgets, model/Docker processes, snapshots and the only final trace. The
   worker retains only its IPython kernel and workspace. One bounded live run
   completed with scope `p1-a-development` and promotion `unpromoted`. Public
   preset wiring and production receipt/catalog publication remain separate.
4. **P1-B semantic closure — development verified:** one real bounded run used
   one Prime SDK session, two prompts, one manual compact, five provider
   callbacks and two Docker-backed IPython cells in one kernel. Namespace,
   import identity, function identity/behavior, cwd and file bytes passed all
   twelve continuity probes. Initial/post snapshots, final AST oracle, provider
   close, Node reap and exact container absence completed. The body-free result
   is `p1-b-development/unpromoted`.
5. **P1 standard CLI route — development verified:** the
   installed provider, assembly, capability package, `prime.agent` runtime and
   one-shot injected host service now compose through `asterion run`. Exact
   application identity, fixed input, image digest, SDK source root, sealed
   seccomp profile, cancellation terminal semantics, redaction and cleanup are
   enforced. A provider-free composed-run E2E passes. The private adapter now
   retains only a fixed, body-free failure category while the public error stays
   unchanged; Sol approved its redaction and child-frame contract. One bounded
   current-source credentialed first callback then returned the required unique
   `ipython` call. A private stage-observed full run completed all five provider
   callbacks and both worker cells without work or cleanup failure. The standard
   exact application selector CLI then exited 0 and returned the safe trace
   `sha256:a8be640bdcee9c93ea3e382729db561e4c29e071d3ff776335daac4ff572c703`.
   Cleanup left zero Prime Node processes and zero P1-B containers. This closes
   the development reproduction; its promotion remains `unpromoted`.

The P1-A/P1-B split records existing contract differences, not permission to
weaken the seven-scenario goal. Production deployment must preserve separate
authority identity and all approved security constraints. No same-uid fake,
Python source digest, image digest or empty catalog can stand in for a promoted
authority executable.

## P2 closure record

P2 now reuses the P1 runtime/host/service spine through the exact installed
application `prime.programmatic-long-context@1.0.0`. One real Prime SDK session
made exactly two model callbacks and one `ipython` tool call. The restricted
Docker worker read the fixed eight-record corpus, while the host independently
verified the canonical aggregate bytes and emitted only a digest-bound trace.
The standard CLI exited 0 with scope `p2-development`, promotion `unpromoted`,
and trace `4ec38c0cb80010941892523610bb9cdbf8b37c213ed6c759fcd794f30d57a62e`.
Post-run inspection found zero P2 containers and zero P2 Node processes. Sol's
final material review approved the contract, cleanup, observations and public
error isolation. This proves the fixed development reproduction, not production
promotion or arbitrary long-context scale.

## P3 closure record

P3 now runs through the installed application
`prime.recursive-workflow@1.0.0`. One root Prime session created real
implementation and review RLM children, retained review for one follow-up, and
then deleted both children. The closed workflow completed ten model callbacks
and four Docker-backed IPython cells. The host independently verified patched
source, expanded tests, four artifacts, bounded usage, depth one and exact
container absence. The clean public command exited 0 with scope
`p3-development`, promotion `unpromoted`, and trace
`sha256:b961b0ffc13a1e686a73361b9b25b9169690c942a5a84a3604d52f87e5ebe796`.
Post-run inspection found zero P3 containers, gateway processes and temporary
socket/workspace directories. This closes the fixed development reproduction;
production promotion and general recursive orchestration remain separate.

## P4 closure record

P4 now runs through the installed application
`prime.long-session-continuity@1.0.0`. One direct Prime native daemon retained
the same runtime, native session, transcript and Docker IPython kernel across
checkpoint persistence, detach and exact zero-gap reattach. The fixed flow then
performed one observed compact and a second diagnostic, completing five model
callbacks and two IPython cells before the host repeated the same AST oracle.
The public `make prime-p4-run` command exited 0 with scope `p4-development`,
promotion `unpromoted`, and trace
`sha256:0bd39b78189f739dcb07123947599276d3f91e7dc24da9407be14ee283e5bebf`.
Post-run inspection found zero related processes, containers, sockets,
checkpoints and temporary workspaces. This closes the fixed development
reproduction. Crash/restart replay and production promotion remain separate.

## P5 closure record

P5 now runs through the installed application
`prime.bounded-autonomy@1.0.0`. One real Prime session used exactly two prompts,
four model callbacks and two completion-only Docker IPython actions. The first
action preserved the known-defective source and wrote bound evidence; the host
result gate passed and quality gate failed. Exact feedback then drove the second
action to repair the source. The host independently validated actual source and
artifact bytes, the AST oracle, both result gates and both quality outcomes.
The public `make prime-p5-run` command exited 0 with scope `p5-development`,
promotion `unpromoted`, and trace
`sha256:64268243e6e95133a7379e7e9819cc8e4d6609608d8af5375a7b4b6164c55103`.
Post-run inspection found zero P5 containers, gateway processes and temporary
workspaces. This closes the fixed development reproduction; production
promotion and broader autonomous task classes remain separate.

## P6 closure record

P6 now runs through the installed application
`prime.continual-improvement@1.0.0`. The bounded route executed task A, a
candidate change, and holdout task B, then applied the exact activation-or-
rollback decision with worker evidence and cleanup. The exact command
`PRIME_RUN_ID=prime-p6-20260906-final make prime-p6-run` exited 0 with scope
`p6-development/unpromoted` and trace
`sha256:51f6454e90a2286dfd0fabaa3f3cf7f7870cd57abf95890845b4efd01048b335`.
Nineteen Python tests, two TypeScript tests, and Ruff passed; residue
inspection found zero Prime P6 containers. This closes the development
reproduction; production promotion remains a separate release task.

## Current development execution evidence

The development path now constructs real Linux/arm64 P1-A and P1-B images,
starts restricted Docker workers, passes their self-checks, and reads live tmpfs
snapshots through the explicitly local-root same-guest operation. P1-A closed
the single-cell SDK/provider path. P1-B then closed the original multi-turn
semantic gap with a real compact operation and one persistent IPython kernel.
The successful P1-B trace digest is
`sha256:21ba3699ff291d98349bf2895b3453adacd1a48dd0b6f9fdfd6803321f403d46`.
Both results remain unpromoted development evidence. The installed CLI now has
the fixed public runtime/host preset and completed the full P1-B flow using the
exact application selector. The public `verify --level acceptance` command
still covers only the provider-free fixture; the real development evidence is:

```bash
asterion run \
  --provider prime-agent \
  --application prime.ipython-coding@1.0.0 \
  --runtime prime.agent \
  --run-id prime-cli-verified-20260906 \
  --input fixed-small-verification

asterion run \
  --provider prime-agent \
  --application prime.programmatic-long-context@1.0.0 \
  --runtime prime.agent \
  --run-id prime-p2-cli-verified3-20260906 \
  --input fixed-small-verification

asterion run \
  --provider prime-agent \
  --application prime.recursive-workflow@1.0.0 \
  --runtime prime.agent \
  --run-id prime-p3-cli-verified-20260906 \
  --input fixed-small-verification
```

The earlier commands that omitted `@1.0.0` failed during exact application
selection and never entered the host. They are not backend execution failures.

## Development execution entrypoints

From the macOS checkout, the following commands execute the fixed development
presets inside the shared Orb Ubuntu machine as root. They use the guest's
isolated `uv` environment and select the exact provider, application version,
runtime, and fixed small-verification input; they do not run promotion or the
full test suite.

```bash
make prime-p1-run
make prime-p2-run
make prime-p3-run
```

Each command generates a legal unique run ID. To correlate a run with external
operator evidence, supply only `PRIME_RUN_ID`, for example:

```bash
PRIME_RUN_ID=prime-p3-investigation-20260906 make prime-p3-run
```

The local proc snapshot is an operator development operation. A reduced-
privilege authority cannot assume it has that root capability; later integration
must inject a narrow manager-owned operation. Prime session, compaction and RLM
semantics remain in the TypeScript Gateway; Python must not grow a second
session engine. P1-B must extend that same gateway with a persistent session/
kernel and one real compact operation.

Development verification follows the user's explicit scope: normal execution
plus identity/isolation, limits, cancellation/cleanup and redaction assertions.
Do not add release matrices or repeat promotion as a prerequisite to functional
progress. Concrete real execution failures justify narrow fixes and checks.

## Work ownership and parallelism

- Astra: cross-scenario contracts, Prime/Native boundaries, critical-path and
  semantic closure decisions; canonical worklist ownership.
- Terra: concrete implementations and integration tests within reviewed slices.
- Luna: inventory, mechanical checks, test/evidence collection, environment
  prerequisite identification; no architecture changes.
- Sol: independent review for material authority/security/contract changes.
- P2–P7 fixtures and adapters may be inspected in parallel, but real execution
  extends the accepted spine. Do not create seven independent authority systems.

## This-session evidence (2026-09-05)

Luna executed 69 provider-free P2–P7 workload/receipt/acceptance tests and 64
worker/launcher/reducer/provider tests; both groups passed. Another 17-test
compatibility/reducer group passed its assertions, including honest
External-limited outcomes. These counts overlap no claim of model execution.

- `tests.test_prime_recursive_workflow_compat`: real local pinned Prime daemon
  and sidecar; two children admitted/bound/completed/deleted, messages both ways,
  aggregation and cleanup passed. Authority budget zero; no model work.
- `tests.test_prime_programmatic_long_context_compat`: initially returned
  External-limited / missing-prerequisite. The existing kernel interpreter was
  located without installation. With it explicitly selected, actual IPython
  execution exposed a fixture oracle bug: Python spaced JSON was compared to JS
  compact JSON and mislabeled unsupported-prime-api. A one-line canonical
  encoding correction now yields PASS/supported with real runtime, cell,
  oracle, disposal and reap all true. The existing unittest also passes. This
  remains local compatibility evidence, not bounded-sandboxed/model evidence.
- Linux live-source P1 verification: all 16 modules, 215 tests, clean exit 0.
  This uses isolated installed distribution metadata; it is not a Linux wheel
  source-execution or production scenario claim.
- P1 resource admission, installed acceptance and strict promotion-map regression:
  root ran 91 combined tests successfully. Exact commands are recorded below.
- `make lint docs-check check-rust build`: PASS, including Ruff, 176 Markdown
  files/57 local links, 19 Rust integration tests, format/Clippy and wheel build.
  Full promotion is tracked separately and has no current PASS claim.
- Root read-only Docker inspection confirmed an available Linux aarch64 daemon
  through the current OrbStack context. No container was launched or promoted.
- P5–P7 real launcher/host gaps are code-inventory findings, not failed real runs.

## Closure rules

- Preserve the exact pinned source `a18809e00ea30638584d87b3afea7285a9d7296c`.
- `list`, `describe`, `acceptance`, `preflight`, repository tests and promotion
  remain provider-free; preflight is readiness only.
- Real presets use operator-owned backend wiring and finite internal controls;
  public output remains safe status/identity/digests/counters only.
- No full dataset, ARC full suite, global harness activation, or publication is
  implied by this worklist. Preserve their separate authorization boundaries.
- Fix core issues only when necessary for these end-to-end paths. Broad package
  splitting, protocol v2, Native feature expansion and new UX parity do not
  displace this closure package.
- After the seven bounded functional scenarios close, return to the framework
  integration assessment and prioritize its remaining work using real reuse
  evidence.

## Focused verification command

```bash
uv run python -m unittest -q \
  tests.test_prime_p1_authority_executable_lock \
  tests.test_prime_p1_authority_resources \
  tests.test_prime_p1_resource_set_identity \
  tests.test_prime_p1_authority_artifact_lock \
  tests.test_setup_pi tests.test_resource_setup \
  tests.test_asterion_dci_verification \
  tests.test_check_promotion.PromotionCheckTests.test_default_plan_runs_every_provider_free_gate_from_the_copy
# 91 tests, OK
```
