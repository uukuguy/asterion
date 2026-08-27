# Prime Parity Ledger

## Baseline and claim rules

- Prime baseline: external `3th-party/prime-agent` commit
  `a18809e00ea30638584d87b3afea7285a9d7296c`.
- Baseline movement requires an explicit difference record; upstream changes do
  not silently change this target.
- `PASS` requires the named command to pass at the stated boundary.
- `Implemented` means code and an entry point exist without establishing the
  broader behavioral claim.
- `Missing`, `Not run`, `External-limited`, and pre-existing gate failures are
  never promoted to `PASS`.
- Provider-free success does not grant bounded provider authority, system
  parity, or Asterion-native parity.

## Phase evidence

| Phase claim | Current state | Evidence command | Boundary and notes |
|---|---|---|---|
| `control-plane-foundation` | PASS | Phase 0 gate | Provider-free fake only; no Prime/model/runtime/application operation. |
| Prime Gateway implemented | Implemented; provider-free gate PASS | `make prime-verify-provider-free` | Real-process fake-Prime scenarios; no model-provider operation. |
| `Verified-loop` | PASS | `make ASTERION_PRIME_SOURCE_ROOT=3th-party/prime-agent prime-verify-native-rlm-bounded` | Real finite Prime run under prior explicit bounded authority. |
| `Verified-system-parity` | Missing | Not run | Requires zero missing mandatory pinned Prime entries. Current exact checker remains `BLOCKED` on `interfaces.operations`. |
| Native `Verified-loop` | Missing | Not run | Requires native provider common and differential evidence. |
| `Verified-native-parity` | Missing | Not run | Final goal; requires every mandatory native parity scenario. |

## Stable parity domains

| Domain ID | Required final behavior | Prime Gateway | Native kernel | Current evidence | Notes |
|---|---|---|---|---|---|
| `foundation.control-contracts` | Closed cross-language system/provider/control contracts | Not applicable | Not applicable | PASS — Phase 0 gate | Shared host foundation, not a provider parity claim. |
| `foundation.system-resolution` | Exact immutable provider and application portfolio closure | Not applicable | Not applicable | PASS — Phase 0 gate | Provider construction follows complete preflight. |
| `foundation.authority-admission` | Host-owned revisioned authority, budgets, and one decision per proposal | Not applicable | Not applicable | PASS — Phase 0 gate | Phase 0 does not execute admitted applications. |
| `foundation.journal-recovery` | Persist-before-send, contiguous reduction, replay, and honest uncertainty | Implemented | Not applicable | PASS — Phase 1 provider-free gate | Real Prime recovery remains bounded evidence. |
| `foundation.safe-evidence` | Body-free causal projection and explicit evidence gaps | Not applicable | Not applicable | PASS — Phase 0 gate | Observation failures do not imply execution failure. |
| `session.context` | Persistent session tree, resume/delete/fork/clone, compaction, queues, usage, and rich attachments | PASS | Missing | PASS — provider-free plus bounded gates | Native-kernel parity remains separate. |
| `rlm.programmatic` | Persistent program environment, recursive children, messaging, cancellation, usage, and recovery | PASS | Missing | PASS — provider-free plus bounded gates | Native-kernel parity remains separate. |
| `operation.long-running` | Detach/attach, goals, autonomy, heartbeat, schedules, restart, residency, and cleanup | PASS | Missing | PASS — nine provider-free plus one bounded gate | Native-kernel parity remains separate. |
| `harness.continual` | Scoped prompt/memory/skill/subagent refinement, history, isolation, and rollback | PASS | Missing | PASS — seven provider-free plus one bounded gate | Native-kernel parity remains separate. |
| `ecosystem.capabilities` | Context files, skills, extensions, tools, packages, MCP, and provider/model integration | PASS | Missing | PASS — H-034 closure | Four provider-free gates, exact 10/10 reducer, clean repository gate, and isolated promotion passed. |
| `interfaces.operations` | SDK/CLI/RPC/ACP/JSON/TUI/headless/export/auth/settings/telemetry/doctor/update | Missing | Missing | Not run | Pixel-identical TUI and hidden reasoning are excluded; functional reachability is mandatory. |

## Ecosystem evidence boundary

The ten Prime Gateway `ecosystem.capabilities` rows are
`provider-free-pass`:

- `ecosystem.collision-diagnostics`
- `ecosystem.context-files`
- `ecosystem.custom-providers-models`
- `ecosystem.extension-state-commands`
- `ecosystem.extensions-lifecycle`
- `ecosystem.mcp`
- `ecosystem.packages`
- `ecosystem.prompt-templates`
- `ecosystem.skills`
- `ecosystem.tools`

The accepted provider-free commands are:

```bash
make test.prime-ecosystem-resources.provider-free
make test.prime-ecosystem-extensions.provider-free
make test.prime-ecosystem-packages.provider-free
make test.prime-ecosystem-mcp.provider-free
uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway
```

All evidence rows use boundary `real-prime-provider-free`, pinned source commit
`a18809e00ea30638584d87b3afea7285a9d7296c`, artifact lock
`c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3`, module
lock `959989c9f6afb907db32bdef709cf19b45fa19421095f62714ff80b9a2c44cd6`, zero
provider operations, zero model credential reads, and zero retained owned
processes.

The exact H-034 cycle passed at `ef685f4`:

- `make check` passed 1,954 Python tests plus TypeScript, Ruff, docs, Rust
  test/fmt/clippy, sdist, and wheel;
- `make promotion-check` reported `promotion full PASS commands=27
  provider_operations=0 full_dataset=no`;
- `git diff --check` passed;
- cycle 34 occurs exactly once, H-034 is passed, and H-035 is next.

## Next evidence boundary

H-035 is the closed client-interface inventory. It covers nine `interface.*`
features that must consume one validated public event stream and one private
value service. The six `operation.*` features remain a separate subsequent
package. Passing `ecosystem.capabilities` does not establish
`interfaces.operations`, `Verified-system-parity`, or Asterion-native parity.
