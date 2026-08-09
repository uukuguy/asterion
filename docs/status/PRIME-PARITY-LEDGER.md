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
runtime or application was contacted by the Phase 0 provider-free suite.

## Phase evidence

| Phase claim | Current state | Evidence command | Boundary and notes |
|---|---|---|---|
| `control-plane-foundation` | PASS | Phase 0 gate below | Provider-free fake only; no Prime/model/runtime/application operation. |
| `Verified-loop` | Missing | Not run | Requires bounded Prime Gateway end-to-end and fault evidence. |
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

## Stable parity domains

These domain IDs remain stable when later phases expand them into individual
machine-readable feature/scenario entries.

| Domain ID | Required final behavior | Prime Gateway | Native kernel | Current evidence | Notes |
|---|---|---|---|---|---|
| `foundation.control-contracts` | Closed cross-language system/provider/control contracts | Not applicable | Not applicable | PASS — Phase 0 gate | Shared host foundation, not a provider parity claim. |
| `foundation.system-resolution` | Exact immutable provider and application portfolio closure | Not applicable | Not applicable | PASS — Phase 0 gate | Provider construction follows complete preflight. |
| `foundation.authority-admission` | Host-owned revisioned authority, budgets and one decision per proposal | Not applicable | Not applicable | PASS — Phase 0 gate | Phase 0 does not execute admitted applications. |
| `foundation.journal-recovery` | Persist-before-send, contiguous reduction, replay and honest uncertainty | Not applicable | Not applicable | PASS — Phase 0 gate | Real process/capsule crash recovery is not run. |
| `foundation.safe-evidence` | Body-free causal projection and explicit evidence gaps | Not applicable | Not applicable | PASS — Phase 0 gate | Pathlight recorder failures are observation-only. |
| `session.context` | Persistent session tree, resume/delete/fork/clone, compaction, queues, usage and rich attachments | Missing | Missing | Not run | Phase 2/4 parity domain. |
| `rlm.programmatic` | Persistent program environment, recursive children, messaging, cancellation, usage and recovery | Missing | Missing | Not run | Phase 1 covers only the verified-loop subset first. |
| `operation.long-running` | Detach/attach, goals, autonomy, heartbeat, schedules, restart, residency and cleanup | Missing | Missing | Not run | Fake lifecycle is foundation evidence only. |
| `harness.continual` | Scoped prompt/memory/skill/subagent refinement, history, isolation and rollback | Missing | Missing | Not run | Mandatory full-parity domain. |
| `ecosystem.capabilities` | Context files, skills, extensions, tools, packages, MCP and provider/model integration | Missing | Missing | Not run | Existing Asterion packages do not establish Prime ecosystem parity. |
| `interfaces.operations` | SDK/CLI/RPC/ACP/JSON/TUI/headless/export/auth/settings/telemetry/doctor/update | Missing | Missing | Not run | Pixel-identical TUI and hidden reasoning are excluded; functional reachability is mandatory. |

## Next evidence boundary

After the Phase 0 gate passes, freeze the common control APIs and write the
Phase 1 Prime verified-loop plan. The next claim requires exact Prime artifact
and RPC capability negotiation, application receipts, recursive child work,
detach/attach, real capsule checkpoint/recovery, cancellation, finite budgets,
sentinel redaction and complete causal evidence. Source mapping or fake-only
tests cannot satisfy it.
