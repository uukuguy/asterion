# Asterion Prime System Parity Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make every mandatory capability in the Prime 0.7.1 baseline reachable through the Asterion control host, with stable machine-readable feature/scenario identities and evidence sufficient for an honest `Verified-system-parity` claim.

**Architecture:** Keep `asterion.agent-control/v1` as the provider-neutral authority, identity, journal and recovery boundary. Extend behavior through the Prime Gateway and Asterion-owned clients only when a parity scenario demands it. Treat the parity ledger as verification metadata rather than a runtime manifest: it pins the external oracle, maps each baseline feature to an Asterion entry point and common conformance scenario, and gates claims without granting execution authority.

**Tech Stack:** Python 3.10+ and `unittest` for the ledger model, claim checks and host conformance; TypeScript and Node 22 for Prime Gateway translation and shared client validation; pinned Prime Agent 0.7.1 at commit `a18809e00ea30638584d87b3afea7285a9d7296c`; JSON fixtures for stable parity metadata; existing Asterion control journal, authority, recovery, private-store and Pathlight components.

---

## Non-negotiable boundaries

- Phase 1 remains open until a separately authorized bounded real-provider run passes. Phase 2 work may proceed provider-free, but it cannot upgrade `Verified-loop` or `Verified-system-parity` by implication.
- The Prime baseline is the existing artifact lock. The parity ledger references and cross-checks that lock; it does not create a second independently movable version pin.
- The ledger is not a public runtime protocol and is not packaged as an authority-bearing manifest. It contains no credentials, prompts, commands, executable paths, environment values, provider payloads, raw outputs or mutable engine state.
- A source evidence record names an explicit repository-relative Prime file and stable symbol/command anchor. The checker reads only those declared children under an explicitly supplied Prime root; it does not scan for replacements or infer compatibility.
- `agent-control/v1` changes only when a feature needs provider-independent observable semantics. Prime-only transport details remain private Gateway messages.
- Prime delegation never bypasses Asterion admission, exact identities, canonical journal persistence, public/private projection, checkpoint binding or uncertain-side-effect handling.
- Pixel-identical TUI rendering and byte-identical hidden reasoning are the only approved exclusions. Every functional command or interaction remains mandatory through an Asterion CLI, SDK or interactive client.
- `Implemented`, provider-free evidence and documentation mappings cannot satisfy a provider-backed requirement. `Missing`, `Not run` and `External-limited` never count as PASS.

## Closed inventory

The first ledger revision contains 63 stable feature IDs: 61 mandatory functional features and 2 explicit non-functional exclusions.

| Domain | Stable feature IDs | Count |
|---|---|---:|
| `session.context` | `session.persistence-naming`, `session.resume-delete`, `session.tree-navigation`, `session.fork-clone`, `session.compaction`, `session.branch-summaries-labels`, `session.delivery`, `session.usage-status`, `session.rich-attachments` | 9 |
| `rlm.programmatic` | `rlm.environment`, `rlm.generated-program`, `rlm.child-model`, `rlm.recursion-depth`, `rlm.registry-lifecycle`, `rlm.messaging`, `rlm.cancellation-teardown`, `rlm.usage-cost`, `rlm.recovery` | 9 |
| `operation.long-running` | `operation.resident-workers`, `operation.detach-attach-replay`, `operation.goals`, `operation.autonomous-quality`, `operation.heartbeat-user`, `operation.heartbeat-agent`, `operation.schedule-once-cron`, `operation.restart-update-recovery`, `operation.worker-residency-eviction`, `operation.orphan-cleanup` | 10 |
| `harness.continual` | `harness.prompt-entries`, `harness.memory-entries`, `harness.skill-descriptions`, `harness.subagent-specifications`, `harness.evidence-refinement`, `harness.history-snapshots`, `harness.rollback`, `harness.scope-isolation` | 8 |
| `ecosystem.capabilities` | `ecosystem.context-files`, `ecosystem.prompt-templates`, `ecosystem.skills`, `ecosystem.extensions-lifecycle`, `ecosystem.tools`, `ecosystem.extension-state-commands`, `ecosystem.packages`, `ecosystem.mcp`, `ecosystem.custom-providers-models`, `ecosystem.collision-diagnostics` | 10 |
| `interfaces.operations` | `interface.sdk`, `interface.cli-interactive`, `interface.rpc`, `interface.acp`, `interface.json-stream`, `interface.headless-print`, `interface.tui-commands`, `interface.tui-extension-ui`, `interface.export-share`, `operation.auth`, `operation.model-selection`, `operation.settings-keybindings`, `operation.telemetry-usage`, `operation.doctor`, `operation.controlled-update-restart` | 15 |
| exclusions | `excluded.tui-pixel-identity`, `excluded.hidden-reasoning-identity` | 2 |

Each mandatory feature owns exactly one primary scenario ID in the form `prime-parity.<feature-id>`. Additional fault, redaction, upgrade and provider-backed scenarios may reference the same feature, but may not replace its primary scenario.

## Evidence states and claim algorithm

Provider results use this monotonic vocabulary:

```text
missing < implemented < provider-free-pass < bounded-pass
                 \-> external-limited
excluded (only when disposition == excluded)
```

`external-limited` is descriptive and non-passing; it is not greater than `implemented`. A scenario declares one of `provider-free`, `real-prime-provider-free`, or `bounded-provider` as its minimum evidence boundary. Claim evaluation is mechanical:

```python
required_status = {
    "provider-free": {"provider-free-pass", "bounded-pass"},
    "real-prime-provider-free": {"provider-free-pass", "bounded-pass"},
    "bounded-provider": {"bounded-pass"},
}
```

`Verified-system-parity` requires every mandatory feature's Prime Gateway result to meet its scenario boundary, every referenced evidence command to be recorded PASS for the exact baseline, no unresolved compatibility difference, and both exclusions to retain their approved reasons. `Verified-native-parity` applies the same rule to the native provider in Phase 4.

## Delivery order

```text
ledger + claim checker
  -> session/context
  -> RLM/messaging
  -> daemon/heartbeat/schedules
  -> continual harness
  -> ecosystem/packages/MCP/providers
  -> SDK/CLI/RPC/ACP/JSON/TUI/export/share
  -> auth/settings/model/telemetry/doctor/update
  -> pinned + next-accepted-build system gate
```

The ordering is dependency-driven. Session identities and snapshots precede recursive agents; recursive ownership precedes scheduled autonomous work; those foundations precede mutable harness and extension surfaces; operational clients are completed only after the underlying behavior is stable.

### Task 1: Add the provider-neutral parity ledger model

**Status:** Complete. Fifteen focused tests, Pyright, Ruff, full repository Python tests and independent review pass.

**Files:**
- Create: `src/asterion/control/parity.py`
- Modify: `src/asterion/control/__init__.py`
- Create: `tests/test_prime_parity_ledger.py`
- Create: `tests/fixtures/prime-parity/v1/valid-ledger-minimal.json`
- Create: `tests/fixtures/prime-parity/v1/invalid-ledger-secret.json`
- Create: `tests/fixtures/prime-parity/v1/invalid-ledger-noncanonical.json`

**Step 1: Write the failing closed-contract tests**

Cover recursive immutability, exact top-level and nested fields, canonical sorted/unique arrays, stable identifier syntax, one primary scenario per feature, scenario-to-feature referential integrity, exclusion restrictions, result/evidence consistency, and sentinel-safe errors.

The public Python surface is:

```python
PARITY_LEDGER_FORMAT = "asterion.parity-ledger/v1"

class ParityLedgerError(ValueError):
    """Raised when parity verification metadata is invalid."""

def validate_parity_ledger(value: object) -> Mapping[str, object]:
    """Return a recursively immutable, canonical parity ledger snapshot."""

def evaluate_parity_claim(
    ledger: Mapping[str, object],
    *,
    provider_id: str,
) -> ParityClaimReport:
    """Evaluate a provider without executing it or granting authority."""
```

`ParityClaimReport` is a frozen dataclass with `provider_id`, `eligible`, `passed_feature_ids`, `blocking_feature_ids`, `excluded_feature_ids`, and `reason_codes`. All arrays are sorted tuples.

Run:

```bash
uv run python -m unittest -v tests.test_prime_parity_ledger
```

Expected: FAIL because `asterion.control.parity` does not exist.

**Step 2: Implement the smallest closed validator and evaluator**

Use explicit field sets and recursive copying into `MappingProxyType`/tuples. Do not add `jsonschema` as a runtime dependency. Reject values rather than normalizing noncanonical input.

The ledger shape is:

```json
{
  "format": "asterion.parity-ledger/v1",
  "ledger_id": "prime-agent-0.7.1",
  "baseline": {
    "artifact_lock": "asterion.prime-artifact-lock/v1",
    "source_commit": "a18809e00ea30638584d87b3afea7285a9d7296c"
  },
  "providers": ["asterion.native", "asterion.prime-gateway"],
  "features": [
    {
      "feature_id": "session.persistence-naming",
      "domain_id": "session.context",
      "disposition": "mandatory",
      "description": "Persistent named sessions are addressable by stable public identities.",
      "prime_evidence": [
        {
          "path": "packages/coding-agent/src/core/session-manager.ts",
          "anchors": ["export class SessionManager"]
        }
      ],
      "asterion_entrypoint": "control.session.persistence-naming",
      "primary_scenario_id": "prime-parity.session.persistence-naming",
      "compatibility_impacts": ["gateway-private", "host-api"],
      "provider_results": [
        {
          "provider_id": "asterion.native",
          "status": "missing",
          "evidence_ids": []
        },
        {
          "provider_id": "asterion.prime-gateway",
          "status": "missing",
          "evidence_ids": []
        }
      ]
    }
  ],
  "scenarios": [
    {
      "scenario_id": "prime-parity.session.persistence-naming",
      "feature_ids": ["session.persistence-naming"],
      "boundary": "real-prime-provider-free",
      "deterministic": true,
      "fault_ids": ["restart-after-create"],
      "assertion_ids": ["identity-stable", "name-redacted", "resume-exact"]
    }
  ],
  "evidence": []
}
```

Forbidden key fragments are `credential`, `environment`, `executable`, `prompt_body`, `provider_payload`, `raw_output`, `secret`, `socket`, `token_value` and `transcript`. Error messages name only the invalid structural field or stable ID, never values or complete objects.

Run the focused command again. Expected: PASS.

**Step 3: Prove claim evaluation fails closed**

Add subtests showing:

- `implemented` cannot satisfy any scenario;
- `provider-free-pass` cannot satisfy `bounded-provider`;
- absent/failed evidence IDs block a result that otherwise says PASS;
- an unknown provider blocks every mandatory feature;
- exclusions cannot contain provider results and require one approved reason code;
- only `excluded.tui-pixel-identity` and `excluded.hidden-reasoning-identity` may be excluded in the Prime ledger fixture.

Run:

```bash
uv run python -m unittest -v tests.test_prime_parity_ledger
uv run pyright src/asterion/control/parity.py tests/test_prime_parity_ledger.py
```

Expected: PASS with zero errors and zero warnings.

**Step 4: Commit**

```bash
git add src/asterion/control/parity.py src/asterion/control/__init__.py tests/test_prime_parity_ledger.py tests/fixtures/prime-parity/v1
git commit -m "feat: add closed parity ledger model"
```

### Task 2: Pin the exhaustive Prime feature and scenario ledger

**Status:** Completed.

**Files:**
- Create: `tests/fixtures/prime-parity/v1/prime-agent-0.7.1.json`
- Create: `tests/fixtures/prime-parity/v1/feature-index.json`
- Modify: `tests/test_prime_parity_ledger.py`
- Create: `tools/check_prime_parity.py`
- Modify: `Makefile`

**Step 1: Write the failing exhaustive-inventory test**

Assert exactly the 63 feature IDs in this plan, exactly 61 mandatory entries, exactly 2 exclusions, all six mandatory domains, exact equality between `feature-index.json` and the ledger, and one primary scenario per mandatory feature.

For every `prime_evidence` record, assert:

- the path is POSIX-relative, has no `..`, and starts with `packages/`;
- the path is an explicit regular-file child of the supplied pinned source root;
- every declared anchor occurs in that exact file;
- the artifact lock commit equals the ledger baseline commit;
- no evidence check scans alternate paths, follows symlinks or accepts a later build.

Run:

```bash
uv run python -m unittest -v tests.test_prime_parity_ledger
```

Expected: FAIL because the exhaustive fixture and checker do not exist.

**Step 2: Populate source/RPC evidence from the pinned tree**

Use these source families; each ledger entry names the narrowest exact file and exported symbol, type, command or class that proves the baseline feature exists:

- session/context: `core/session-manager.ts`, `core/session-resolver.ts`, `core/session-file-actions.ts`, `core/context-tree.ts`, `core/compaction/`, `core/messages.ts`, `core/session-stats.ts`;
- RLM: `core/rlm-runtime.ts`, `core/rlm-max-depth.ts`, `core/kernel/`, `core/agent-messages.ts`, `core/agent-observe.ts`, `core/usage.ts`;
- long-running: `modes/daemon/daemon-protocol.ts`, `active-session-state.ts`, `heartbeat-catalog.ts`, `core/goals.ts`, `core/autonomous.ts`, `core/cron-jobs.ts`, `core/orphan-process-journal.ts`, `package-manager-cli.ts`;
- continual harness: `core/refinement/refinement.ts`, `core/resource-loader.ts`, `core/skills.ts`, and the bundled `skills/refine`/`skills/skill-creator` entry points;
- ecosystem: `core/prompt-templates.ts`, `core/extensions/`, `core/tools/`, `core/package-manager.ts`, `core/mcp/mcp-manager.ts`, `core/model-registry.ts`, `core/model-resolver.ts`;
- interfaces/operations: `core/sdk.ts`, `cli-main.ts`, `modes/rpc/`, `modes/acp/`, `modes/print-mode.ts`, `modes/interactive/`, `core/export-html/`, `core/auth-storage.ts`, `core/settings-manager.ts`, `core/keybindings.ts`, `core/telemetry.ts`, `core/diagnostics.ts`, `package-manager-cli.ts`.

Status initialization is honest:

- mark a feature `provider-free-pass` only when an existing named Phase 1 scenario proves that exact behavior;
- mark it `implemented` only when a public Asterion entry point exists but its primary scenario has not passed;
- otherwise mark it `missing`;
- use `external-limited` only where the implementation exists and the remaining scenario semantically requires a bounded provider;
- keep all native results `missing` until Phase 3 evidence exists.

**Step 3: Add a provider-free checker CLI**

The command is metadata-only unless `--source-root` is explicitly supplied:

```bash
uv run python tools/check_prime_parity.py --claim inventory
uv run python tools/check_prime_parity.py \
  --claim inventory \
  --source-root 3th-party/prime-agent
uv run python tools/check_prime_parity.py --claim verified-system-parity
```

It writes one redacted JSON object with stable IDs and counts. `inventory` succeeds when the ledger is structurally closed; source verification succeeds only for the exact pinned clean checkout. `verified-system-parity` must initially exit nonzero and report blocking feature IDs without rendering paths, anchors, provider values or fixture bodies.

Add Make targets:

```make
.PHONY: prime-parity-inventory prime-verify-system-parity

prime-parity-inventory:
	$(UV_BIN) run python tools/check_prime_parity.py --claim inventory

prime-verify-system-parity:
	$(UV_BIN) run python tools/check_prime_parity.py --claim verified-system-parity
```

Run:

```bash
make prime-parity-inventory
uv run python tools/check_prime_parity.py --claim inventory --source-root 3th-party/prime-agent
! make prime-verify-system-parity
```

Expected: the two inventory checks PASS; the system-parity claim fails closed with 61 or fewer explicit blocking mandatory IDs according to already proven Phase 1 coverage.

**Step 4: Commit**

```bash
git add tests/fixtures/prime-parity/v1 tests/test_prime_parity_ledger.py tools/check_prime_parity.py Makefile
git commit -m "test: pin prime system parity inventory"
```

### Task 3: Create the shared parity-scenario registry

**Status:** Completed.

**Files:**
- Create: `src/asterion/control/parity_testing.py`
- Create: `tests/test_prime_parity_conformance.py`
- Modify: `src/asterion/control/testing.py`
- Modify: `tools/check_prime_parity.py`

**Step 1: Write failing registry tests**

Define a registry whose keys are exactly the ledger scenario IDs. A scenario implementation carries `scenario_id`, `provider_factory`, `clock`, `private_fixture_store`, and `fault_injector`. Registration must fail on unknown IDs, duplicates, boundary mismatch, nondeterministic clock use or a scenario that attempts to read a model credential during a provider-free boundary.

Run:

```bash
uv run python -m unittest -v tests.test_prime_parity_conformance
```

Expected: FAIL because the registry does not exist.

**Step 2: Implement registry/report plumbing without fake passes**

Expose:

```python
@dataclass(frozen=True)
class ParityScenarioResult:
    scenario_id: str
    provider_id: str
    status: str
    evidence_id: str | None
    reason_code: str

class ParityScenarioRegistry:
    def register(self, scenario_id: str, runner: ParityScenarioRunner) -> None: ...
    async def run(self, scenario_ids: Sequence[str]) -> ParityScenarioReport: ...
```

Unimplemented scenarios are reported `missing`; they are never treated as skipped PASS. Reuse Phase 0/1 scenarios only through explicit adapter functions that assert their narrower feature coverage.

**Step 3: Register the proven Phase 1 subset**

Map existing Phase 1 evidence only to the exact primary scenarios it proves: session create/attach/detach/replay, input delivery, checkpoint/restart, goal terminal intents, admitted child spawn/message/cancel subset, budget/redaction and orphan-free shutdown. Do not map the disabled native `rlm.run`, heartbeat, schedules, ecosystem or client breadth.

Run:

```bash
uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_prime_parity_conformance tests.test_prime_verified_loop
make prime-parity-inventory
```

Expected: PASS, while `prime-verify-system-parity` still fails closed.

**Step 4: Commit**

```bash
git add src/asterion/control/parity_testing.py src/asterion/control/testing.py tests/test_prime_parity_conformance.py tools/check_prime_parity.py
git commit -m "test: register prime parity scenarios"
```

### Task 4: Deliver session and context parity

**Status:** In progress. The approved code-level subplan is complete; Task 4.1
(`asterion.session-context/v1`) is next.

**Files:**
- Create before implementation: `docs/superpowers/plans/2026-08-10-asterion-prime-session-context-parity.md`
- Modify as the subplan proves necessary: `packages/typescript/prime-gateway/src/daemon-wire.ts`, `daemon-client.ts`, `prime-session.ts`, `gateway.ts`, `durable-store.ts`
- Modify: `src/asterion/control/host.py`, `protocol.py`, `manager.py`, `parity_testing.py`
- Modify shared TypeScript schemas/types only if provider-neutral commands/events are required.
- Create focused Python and Gateway tests for all nine `session.*` features.

The subplan must use the nine primary scenario IDs, specify exact daemon command/event mappings, preserve separate Asterion/active/transcript identities, and cover delete/fork/clone and compaction crash windows. Rich attachment bodies remain private references; public events expose media type, digest, size and causal identity only.

Exit command:

```bash
uv run python tools/check_prime_parity.py --domain session.context --provider asterion.prime-gateway
```

Expected: all nine session features meet their declared boundaries; every other missing domain remains visible.

### Task 5: Deliver full RLM and messaging parity

**Files:**
- Create before implementation: `docs/superpowers/plans/2026-08-10-asterion-prime-rlm-messaging-parity.md`
- Modify: Prime Gateway daemon/skill bridge, Asterion Prime skill package, child registry, capsule binding, authority/admission and common parity tests.

The subplan must resolve the Phase 1 `rlm.run` gap. Use a public pre-admission hook if the pinned Prime surface supplies one; otherwise require a separately reviewed exact-version adapter/patch with an isolated compatibility test. Every generated program action is proposed before effect, recursive depth and model choice are authority-bounded, messaging preserves parent/child/sibling identities, usage is attributed monotonically, and root teardown leaves no child process.

Exit command:

```bash
uv run python tools/check_prime_parity.py --domain rlm.programmatic --provider asterion.prime-gateway
```

### Task 6: Deliver resident operation, heartbeat and schedule parity

**Files:**
- Create before implementation: `docs/superpowers/plans/2026-08-10-asterion-prime-long-running-operations-parity.md`
- Modify: Gateway daemon wire/client/session, control host schedule/heartbeat services, virtual-clock conformance and recovery journals.

The subplan must distinguish user heartbeat from multiple agent-created heartbeats, one-time schedules from cron, controller residency from task authority, and transport retry from side-effect retry. Accelerated 24-hour virtual-clock tests cover restart, update, eviction and repeated attach. Cancellation and shutdown run an orphan-process audit.

Exit command:

```bash
uv run python tools/check_prime_parity.py --domain operation.long-running --provider asterion.prime-gateway
```

### Task 7: Deliver continual-harness parity

**Files:**
- Create before implementation: `docs/superpowers/plans/2026-08-10-asterion-prime-continual-harness-parity.md`
- Add a host-owned refinement proposal/admission service and private scoped storage binding.
- Modify Gateway translation and common parity/fault/redaction tests.

The subplan must keep local/global/project scopes isolated, store append-only proposal/history/snapshot identities in the canonical journal, keep bodies private, and require an evidence gate before activation. Rollback creates a new monotonic active revision; it never mutates history or lets Prime rewrite authority.

Exit command:

```bash
uv run python tools/check_prime_parity.py --domain harness.continual --provider asterion.prime-gateway
```

### Task 8: Deliver ecosystem, package, MCP and provider parity

**Files:**
- Create before implementation: `docs/superpowers/plans/2026-08-10-asterion-prime-ecosystem-parity.md`
- Add exact Asterion portfolio/resource bindings; modify Gateway extension/package/MCP translations and host preflight services.

The subplan must preserve Asterion's no-scanning catalog rule. Every context file, prompt template, skill, extension, tool, package, MCP server and custom provider/model is an explicit exact child of an approved local root or installed distribution. Collisions fail closed with deterministic diagnostics. Credential refresh is a host service with sentinel redaction and cannot be inferred from settings or caches.

Exit command:

```bash
uv run python tools/check_prime_parity.py --domain ecosystem.capabilities --provider asterion.prime-gateway
```

### Task 9: Deliver functional clients and sharing parity

**Files:**
- Create before implementation: `docs/superpowers/plans/2026-08-10-asterion-prime-client-interfaces-parity.md`
- Modify/add Asterion SDK, CLI interactive, RPC, ACP, JSON event stream, headless/print, TUI functional commands, extension UI requests, export and share surfaces.

All clients consume the same validated public event stream and private value service; they do not create alternate runners or composers. Export/share defaults to safe public projections and requires explicit private export authority for bodies. TUI scenarios compare commands, state transitions and accessible content, never pixel layout.

Exit command:

```bash
uv run python tools/check_prime_parity.py --features interface.sdk,interface.cli-interactive,interface.rpc,interface.acp,interface.json-stream,interface.headless-print,interface.tui-commands,interface.tui-extension-ui,interface.export-share --provider asterion.prime-gateway
```

### Task 10: Deliver operational settings and lifecycle parity

**Files:**
- Create before implementation: `docs/superpowers/plans/2026-08-10-asterion-prime-operational-parity.md`
- Modify/add host-owned auth/settings/model selection, telemetry/usage, doctor and controlled update/restart surfaces and Gateway translations.

Settings describe preference, never authority. Auth values remain private host services. Model/thinking/service-tier/transport choices are exact admitted selections. Telemetry failure is observation-only but a missing required parity record blocks the claim. Update/restart verifies the next artifact before handoff, seals a checkpoint, fences daemon identity, and resumes only exact compatible capsules.

Exit command:

```bash
uv run python tools/check_prime_parity.py --features operation.auth,operation.model-selection,operation.settings-keybindings,operation.telemetry-usage,operation.doctor,operation.controlled-update-restart --provider asterion.prime-gateway
```

### Task 11: Prove pinned and next-build compatibility

**Files:**
- Create: `tests/fixtures/prime-parity/v1/compatibility-matrix.json`
- Modify: artifact lock verifier, Gateway compatibility tests and parity checker.
- Update documentation only after commands pass.

Run every provider-free primary scenario against the pinned build and one separately accepted next build. The next build receives its own exact artifact lock and difference records; acceptance never rewrites the 0.7.1 baseline. For each difference record, require old/new Gateway behavior, resume compatibility, daemon capability negotiation, event mapping and capsule decision (`compatible`, `migration-required`, or `rejected`).

Bounded-provider scenarios may reuse an explicitly authorized finite evidence run only when its artifact identity and authority envelope match exactly.

### Task 12: Run the Phase 2 exit gate

**Step 1: Run focused provider and parity gates**

```bash
uv run python -m unittest -v tests.test_prime_parity_ledger tests.test_prime_parity_conformance
npm test --prefix packages/typescript/asterion-runtime
npm test --prefix packages/typescript/prime-gateway
make prime-verify-provider-free
make prime-parity-inventory
make prime-verify-system-parity
```

Expected: all PASS. The final command reports zero blocking mandatory Prime Gateway features and cites exact evidence IDs.

**Step 2: Run repository and packaged-resource gates**

```bash
make test
make lint
make docs-check
make check
make promotion-check
git diff --check
```

Expected: all PASS with provider operation counts stated honestly. Add the parity ledger/checker to wheel smoke only if a supported installed CLI consumes them; test fixtures themselves remain development evidence.

**Step 3: Audit privacy, authority and resources**

Run sentinel scans over public events, canonical journal, Pathlight, stdout/stderr, exported/shared artifacts and expected exception strings. Audit orphan processes and resource caps after cancellation/shutdown. Confirm every cost-bearing command names a finite authority envelope and no environment/cache/settings file is treated as authorization.

**Step 4: Publish the claim without closing the full program**

Update `docs/status/PRIME-PARITY-LEDGER.md`, `docs/status/CURRENT-STATE.md`, `docs/status/JOURNAL.md`, and `docs/status/RESUME-NEXT-SESSION.md` with named passing commands, exact pinned/accepted build identities, provider/application operation counts and any external limitation.

Record `Verified-system-parity` only if the mechanical checker and all exit gates pass. The full project objective remains open until Phase 4 records `Verified-native-parity` from the same mandatory scenario set.

## Plan self-review checklist

- [ ] The fixture contains exactly the approved 61 mandatory functions and 2 exclusions.
- [ ] Every feature has exact Prime source evidence, a target Asterion entry point, one primary deterministic scenario and compatibility impacts.
- [ ] Existing Phase 1 evidence is mapped narrowly and never inflates full RLM or system parity.
- [ ] Missing scenario implementations fail as missing, not skipped or expected PASS.
- [ ] Public contracts change only for provider-independent observable semantics.
- [ ] Domain subplans are created and reviewed before their implementation begins.
- [ ] Bounded evidence has exact authority, cost, artifact and operation counts.
- [ ] Pinned and next accepted builds are tested without moving the baseline silently.
- [ ] `Verified-system-parity` does not imply native parity or full program completion.
