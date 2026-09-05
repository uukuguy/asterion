# Prime Seven-Scenario Closure Worklist

> Updated: 2026-09-05. Canonical active worklist for the Prime capability program.

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
| P1 `prime.ipython-coding/v1` | Fixture, package/assembly, default inert runtime, authority/resource contracts exist; actual basic is NOT RUN | P1-A: authenticated real execution spine and bounded coding oracle. P1-B: persistent namespace/imports/functions/cwd/files across turns and compaction, with real restricted-worker evidence | **Active**. Empty promoted image/seccomp/authority ELF catalogs; trusted supervisor/service-manager/real model transport and public runtime wiring incomplete |
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
2. **P1 execution/deployment contract — bundle admission verified, launch pending:** use the reviewed Linux
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
   passed admission/revalidation/cleanup. Actual authority IPC launch remains next.
3. **P1-A real spine:** promoted resources, exact launch, authenticated terminal,
   killable model transport, trusted oracle and cleanup connect to one public
   preset. First prove the complete process path with a deterministic backend,
   then its finite actual model execution. This is a spine/coding smoke gate.
4. **P1-B semantic closure:** current production workload permits one model
   request/IPython call, while the original P1 fixture requires multiple turns
   and post-compaction witnesses. Preserve P1-A's exact contract; add a reviewed
   exact semantic scenario rather than relabeling one-cell evidence as full P1.

The P1-A/P1-B split records existing contract differences, not permission to
weaken the seven-scenario goal. Production deployment must preserve separate
authority identity and all approved security constraints. No same-uid fake,
Python source digest, image digest or empty catalog can stand in for a promoted
authority executable.

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
