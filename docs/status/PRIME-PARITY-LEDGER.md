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
| `Verified-system-parity` | PASS | `uv run python tools/check_prime_parity.py --claim verified-system-parity --provider asterion.prime-gateway` | H-037 closed the exact Prime Gateway union at 61 passed, 0 blocking, 2 excluded, and zero provider/application operations. |
| Native controller core | PASS | `make test.native-controller-core.provider-free` | Provider-free durable single-session substrate; all 61 compound Native rows remain Missing. |
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
| `interfaces.operations` | SDK/CLI/RPC/ACP/JSON/TUI/headless/export/auth/settings/telemetry/doctor/update | PASS — 15/15 Prime Gateway rows | Missing | PASS — H-035 + H-036 closure gates | Pixel-identical TUI and hidden reasoning are excluded; functional reachability is mandatory. |

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

## Client interface evidence boundary

H-035 passed exactly once through the four provider-free client receipts:

- `test.prime-client-core.provider-free` — 9 tests
- `test.prime-client-protocols.provider-free` — 15 tests
- `test.prime-client-interactive.provider-free` — 55 tests
- `test.prime-client-export-share.provider-free` — 10 tests

The exact nine-feature Prime Gateway checker selected and passed all nine rows
with zero blocking, provider, and application operations. The receipts bind the
same pinned Prime source and record zero provider/model/credential/network/
upload operations. No full dataset was run.

The nine passed rows are `interface.sdk`, `interface.cli-interactive`,
`interface.rpc`, `interface.acp`, `interface.json-stream`,
`interface.headless-print`, `interface.tui-commands`,
`interface.tui-extension-ui`, and `interface.export-share`. Native rows remain
missing.

The clean H-035 cycle used the four receipts, the exact nine-feature checker,
`make check`, `make promotion-check`, and `git diff --check`; promotion reported
`commands=27 provider_operations=0 full_dataset=no`. Cycle 35 occurs exactly
once with `check.client-interfaces-closure`.

## Operational interface evidence boundary

H-036 passed exactly once through the six provider-free operational receipts:

- `operation.auth` —
  `evidence.operation.b1ad7223aab563156d8991d97e8b216b33ce131fefdc5a4bbc976b2a867031e8`
- `operation.model-selection` —
  `evidence.operation.d607c48b96afe83a2fc1346020dbf914ac40138c6ff04105a7daf06d8c85f92a`
- `operation.settings-keybindings` —
  `evidence.operation.14ec3308d4c777eb349be8f8a79710301d8db0264f2013ad06fe0cbb9e83fe2e`
- `operation.telemetry-usage` —
  `evidence.operation.84a78d29b2fc30cec854b81e32d95072a308d6eae98d7d7288c19b882a48f731`
- `operation.doctor` —
  `evidence.operation.e51e972608257ddd54c7fb1835e08f4da361078d2c145c0f31bb04a5f9f79e02`
- `operation.controlled-update-restart` —
  `evidence.operation.8d973b07690020955820347d724f1a609a808a01ca734fac9f30f56ca4837071`

The accepted provider-free commands are:

```bash
make test.prime-operational-auth.provider-free
make test.prime-operational-model-selection.provider-free
make test.prime-operational-settings-keybindings.provider-free
make test.prime-operational-telemetry-usage.provider-free
make test.prime-operational-doctor.provider-free
make test.prime-operational-controlled-update-restart.provider-free
uv run python tools/check_prime_parity.py --features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart --provider asterion.prime-gateway
```

The exact six-feature Prime Gateway checker selected six, passed six, reported
zero blocking rows, and reported zero provider/application operations. With
H-035, `interfaces.operations` is now PASS at exactly 15/15 Prime Gateway rows.

The clean H-036 cycle used the six receipts, the exact six-feature checker,
`make check`, `make promotion-check`, and `git diff --check`; promotion reported
`commands=28 provider_operations=0 full_dataset=no`. Cycle 36 occurs exactly
once with `check.operational-parity-closure`; H-037 follows it exactly once.

This does not claim live OAuth, live model selection, live telemetry delivery,
actual update/restart effects, or Asterion-native behavior. Those provider-free
operation receipts contribute only their exact functional rows; the broader
system claim requires the complete closed union and production callback gate
below. `Verified-native-parity` remains missing.

## Prime system-parity closure

H-037 passed exactly once with command identity
`prime-system-parity-operation-host-callback`. The gate:

- built the Prime Gateway under Node 22.23.2;
- passed all four real-process callback scenarios, including execute,
  reconcile/cancel, safe failure, cleanup, and no retry;
- passed the exact system checker at 61 passed, zero blocking, two excluded,
  and zero provider/application operations;
- passed `make check`, including 2,338 Python tests, TypeScript, Rust, lint,
  docs, sdist, and wheel checks;
- passed `make promotion-check` with `commands=28`, zero provider operations,
  and `full_dataset=no`; and
- passed `git diff --check` before the canonical transition.

This establishes `Verified-system-parity` only for
`asterion.prime-gateway` at the pinned Prime baseline. Every native-kernel row
remains Missing, and neither provider-free evidence nor H-037 grants future
model, credential, network, application, or native execution authority.

## Native controller-core boundary

H-038 passed exactly once with command identity
`check.native-controller-core-provider-free`. The gate:

- passed `make test.native-controller-core.provider-free` at 189 tests;
- emitted the exact `native-controller-core` receipt with 10 common scenarios,
  five differential cases, eight crash points, zero provider/model/credential/
  network/application/upload operations, `promoted_feature_ids=[]`, and 61/61
  mandatory Native rows still missing;
- passed `make check`, including 2,529 Python tests, TypeScript, Rust, lint,
  docs, sdist, and wheel checks;
- passed `make promotion-check` with `commands=28`, zero provider operations,
  and `full_dataset=no`; and
- passed `git diff --check` before the canonical transition.

This establishes only the provider-free durable single-session Native
controller substrate. It does not claim Native `Verified-loop`, compound
feature parity, provider/model/application execution, or full dataset
reproduction. Canonical Climb state now routes to
`phase-3.2-native-verified-loop-design`.
