# Prime Parity Ledger

## Baseline and claim rules

- Prime baseline: vendored `3th-party/prime-agent` commit
  `a18809e00ea30638584d87b3afea7285a9d7296c`.
- Baseline movement requires an explicit difference record; upstream changes do
  not silently change this target.
- `PASS` requires the named command to pass at the stated boundary.
- `Implemented` means code and a public entry point exist without establishing
  the broader behavioral claim.
- `Missing`, `Not run` and `External-limited` are never promoted to `PASS`.
- Phase 0 may establish only `control-plane-foundation`. Only Phase 4
  `Verified-native-parity` completes the full Prime-equivalence objective.

The baseline commit is pinned source evidence only. No Prime process, model,
runtime or application was contacted by the Phase 0 provider-free suite. Phase
1 now adds a real-process Asterion/Prime-Gateway loop against a deterministic
fake Prime daemon; it still does not establish a real Prime/model run.

## Phase evidence

| Phase claim | Current state | Evidence command | Boundary and notes |
|---|---|---|---|
| `control-plane-foundation` | PASS | Phase 0 gate below | Provider-free fake only; no Prime/model/runtime/application operation. |
| Prime Gateway implemented | Implemented; provider-free gate PASS | `make prime-verify-provider-free` and Phase 1 gate below | Ten real-process fake-Prime scenarios; zero model-provider operations, two fake application executions. |
| `Verified-loop` | External-limited | Bounded gate not run | Provider-free half passes. Real Prime preflight requires compatible Node 22.x; bounded execution also requires separately injected private run configuration and finite authorization. |
| `Verified-system-parity` | Missing | Not run | Requires zero missing mandatory pinned Prime entries. |
| Native `Verified-loop` | Missing | Not run | Requires native provider common and differential evidence. |
| `Verified-native-parity` | Missing | Not run | Final goal; requires every mandatory native parity scenario. |

### Phase 0 gate

The aggregate Phase 0 claim passed on the Phase 0 closure candidate with every
command below successful:

```bash
uv run python -m unittest -v tests.test_agent_system_protocol tests.test_agent_control_protocol tests.test_control_provider tests.test_control_system tests.test_control_authority tests.test_control_journal tests.test_control_state tests.test_control_host tests.test_control_conformance tests.test_control_pathlight
npm --prefix packages/typescript/asterion-runtime test
make test
make lint
make docs-check
make promotion-check
make check
```

Observed results were 61 focused Python tests, 21 shared-contract TypeScript
tests, 1,471 repository Python tests, 32 DCI context-extension TypeScript tests
and 19 Rust tests. Documentation checked 83 Markdown files and 54 local links.
Promotion passed 22 commands from an isolated standalone copy with zero provider
operations and no full dataset. The runtime package audit reported zero known
vulnerabilities after the locked `fast-uri` update.

### Phase 1 provider-free gate

The Prime Gateway closure candidate passed these zero-provider boundaries:

```bash
uv run python -m unittest -v tests.test_control_file_journal tests.test_control_recovery tests.test_control_execution tests.test_control_application_executor tests.test_control_children tests.test_prime_control_client tests.test_prime_control_factory tests.test_prime_skill tests.test_prime_verified_loop tests.test_control_pathlight tests.test_prime_system_actions tests.test_setup_prime_agent tests.test_verify_prime_loop
npm test --prefix packages/typescript/asterion-runtime
npm test --prefix packages/typescript/prime-gateway
make prime-verify-provider-free
make test
make lint
make docs-check
make promotion-check
make check
```

Observed results were 174 focused Python tests, 122 Prime Gateway TypeScript
tests, 21 shared-contract TypeScript tests, 1,650 repository Python tests, 32
DCI context-extension TypeScript tests, and 19 Rust tests. Documentation checked
86 Markdown files and 57 local links. Promotion passed 26 commands from an
isolated standalone copy. The stable ten-scenario ledger observed zero model-
provider operations, two fake application executions, canonical journal/
Pathlight evidence, and no sentinel leakage from public events, journal,
Pathlight, stdout/stderr, or expected exception strings.

External preflight was also attempted with:

```bash
uv run python tools/verify_prime_loop.py --level preflight --source-root 3th-party/prime-agent
```

It reported `External-limited`, not PASS: the current machine has Node 23.11.0,
while the pinned Prime compatibility boundary is Node 22.8.0 through 22.x. A
bounded real-Prime/model run was not authorized and was not run. No model
credential was read and the provider-operation count remained zero.

## Stable parity domains

These domain IDs remain stable when later phases expand them into individual
machine-readable feature/scenario entries.

| Domain ID | Required final behavior | Prime Gateway | Native kernel | Current evidence | Notes |
|---|---|---|---|---|---|
| `foundation.control-contracts` | Closed cross-language system/provider/control contracts | Not applicable | Not applicable | PASS — Phase 0 gate | Shared host foundation, not a provider parity claim. |
| `foundation.system-resolution` | Exact immutable provider and application portfolio closure | Not applicable | Not applicable | PASS — Phase 0 gate | Provider construction follows complete preflight. |
| `foundation.authority-admission` | Host-owned revisioned authority, budgets and one decision per proposal | Not applicable | Not applicable | PASS — Phase 0 gate | Phase 0 does not execute admitted applications. |
| `foundation.journal-recovery` | Persist-before-send, contiguous reduction, replay and honest uncertainty | Implemented | Not applicable | PASS — Phase 1 provider-free gate | Gateway, supervisor and worker crash windows are real processes against fake Prime; real-Prime recovery remains bounded evidence. |
| `foundation.safe-evidence` | Body-free causal projection and explicit evidence gaps | Not applicable | Not applicable | PASS — Phase 0 gate | Pathlight recorder failures are observation-only. |
| `session.context` | Persistent session tree, resume/delete/fork/clone, compaction, queues, usage and rich attachments | Missing | Missing | Not run | Phase 2/4 parity domain. |
| `rlm.programmatic` | Persistent program environment, recursive children, messaging, cancellation, usage and recovery | Partial | Missing | PASS — provider-free child subset | One Asterion-owned child level is admitted and recovered; native Prime `rlm.run` and full RLM parity remain disabled/missing. |
| `operation.long-running` | Detach/attach, goals, autonomy, heartbeat, schedules, restart, residency and cleanup | Partial | Missing | PASS — provider-free verified-loop subset | Create/attach/detach, checkpoint/restart, terminal goal intents and cancellation pass; heartbeat/schedules and real bounded autonomy remain missing. |
| `harness.continual` | Scoped prompt/memory/skill/subagent refinement, history, isolation and rollback | Missing | Missing | Not run | Mandatory full-parity domain. |
| `ecosystem.capabilities` | Context files, skills, extensions, tools, packages, MCP and provider/model integration | Missing | Missing | Not run | Existing Asterion packages do not establish Prime ecosystem parity. |
| `interfaces.operations` | SDK/CLI/RPC/ACP/JSON/TUI/headless/export/auth/settings/telemetry/doctor/update | Missing | Missing | Not run | Pixel-identical TUI and hidden reasoning are excluded; functional reachability is mandatory. |

## Next evidence boundary

The next evidence boundary is a compatible Node 22.x external preflight followed
by one separately authorized finite bounded run through the pinned real Prime
daemon/model. That run must exercise one root goal, an admitted exact
application, one child, detach/attach, checkpoint/restart, cancellation, budget
reporting, a terminal goal, complete causal evidence, and sentinel redaction.
Provider-free success cannot satisfy `Verified-loop`; system/native parity
domains remain separate later phases.
