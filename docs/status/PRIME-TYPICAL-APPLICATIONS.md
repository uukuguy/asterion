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
| P1 `prime.ipython-coding/v1` | P1-A and P1-B development scopes now complete real Prime SDK/provider/Docker/IPython/oracle/cleanup runs; the standard CLI/provider/assembly/runtime/host route is implemented; one current-source credentialed first callback passes the named `ipython` contract | Identify the later failing stage, obtain one successful CLI trace, then promoted authority resources | **Active / external-limited**. Provider-free composition and the first real callback pass, but the complete CLI run still fails safely |
| P2 `prime.programmatic-long-context/v1` | Workload, worker, launcher, receipt and reducer tests pass; real local Prime/IPython corpus compatibility PASS after canonical JSON fixture correction | Admitted restricted-worker/model execution, fixed oracle, installed public route | Depends on P1 shared execution boundary; existing P2 launcher retained |
| P3 `prime.recursive-workflow/v1` | Provider-free tests pass; real local Prime two-child message/aggregate/delete compatibility PASS | Real admitted restricted-worker/model execution, exact depth/usage/cancellation and public route | Depends on P1/P2 spine; compatibility evidence does not satisfy bounded-sandboxed gate |
| P4 `prime.long-session-continuity/v1` | Diagnostic workload, completion, recovery adapter, worker and reducer tests pass | Actual detach/attach/compaction/recovery launcher/host, same oracle after recovery, no blind effect replay | Depends on P1/P3; real launcher/host absent |
| P5 `prime.bounded-autonomy/v1` | Fixed repair workload, two-gate/digest fencing, worker and reducer tests pass | Actual finite Prime worker/gate loop with result and quality-gate proof | Depends on P1/P4; real launcher/host absent |
| P6 `prime.continual-improvement/v1` | HarnessCoordinator task-A/candidate/task-B, scoped approval and rollback tests pass | Real task/holdout execution, exact activation or rollback, worker evidence and public route | Depends on P1/P5; use local/project scope first, global activation remains explicitly governed |
| P7 `prime.arc-agi-3/v1` | Game broker/score replay/worker/subset-full reducer tests pass | Real isolated game broker and IPython launcher with bounded public-subset functional evidence | Depends on P1–P6; full multi-game reproduction remains a separate explicitly authorized finite scope |

All seven complete only after their named real scenario succeeds. Public
metadata, fixed fixtures, fake workers and compatibility probes are distinct
evidence layers, not alternate ways to close a scenario. P2–P7 currently lack
installed application assembly routes; seven source-level test suites do not
mean seven publicly runnable scenarios.

## Active P1 acceptance slices

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
5. **P1 standard CLI route — implemented, real run not yet verified:** the
   installed provider, assembly, capability package, `prime.agent` runtime and
   one-shot injected host service now compose through `asterion run`. Exact
   application identity, fixed input, image digest, SDK source root, sealed
   seccomp profile, cancellation terminal semantics, redaction and cleanup are
   enforced. A provider-free composed-run E2E passes. The private adapter now
   retains only a fixed, body-free failure category while the public error stays
   unchanged; Sol approved its redaction and child-frame contract. One bounded
   current-source credentialed first callback then returned the required unique
   `ipython` call. The following single complete CLI attempt still failed safely
   before a terminal trace, so a later callback or execution stage remains to be
   isolated. Cleanup left zero Prime Node processes and zero P1-B containers.
   This is `External-limited`, not PASS.

The P1-A/P1-B split records existing contract differences, not permission to
weaken the seven-scenario goal. Production deployment must preserve separate
authority identity and all approved security constraints. No same-uid fake,
Python source digest, image digest or empty catalog can stand in for a promoted
authority executable.

## Current development execution evidence

The development path now constructs real Linux/arm64 P1-A and P1-B images,
starts restricted Docker workers, passes their self-checks, and reads live tmpfs
snapshots through the explicitly local-root same-guest operation. P1-A closed
the single-cell SDK/provider path. P1-B then closed the original multi-turn
semantic gap with a real compact operation and one persistent IPython kernel.
The successful P1-B trace digest is
`sha256:21ba3699ff291d98349bf2895b3453adacd1a48dd0b6f9fdfd6803321f403d46`.
Both results remain unpromoted development evidence. The installed CLI now has
the fixed public runtime/host preset and its first real model callback passes,
but the complete command has not produced a terminal trace in the current
backend environment. The public `verify --level acceptance` command still
covers only the provider-free fixture and must not be cited as real P1.

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
- P4–P7 real launcher/host gaps are code-inventory findings, not failed real runs.

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
