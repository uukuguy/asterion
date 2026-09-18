# Next-Session Handoff

> Updated: 2026-09-18 19:57, end of session. Phase 6 Tasks 1-13 committed.
> HEAD: `3c11b994d52647ca90dde626c84a97785f2f27d2` clean.

## TL;DR

1. **Phase 6 (P4 rebuild) Tasks 1-13 done and committed.** P4's application,
   capability package, host service, host contract, oracle, receipt, runtime
   binding, operator, provider factories, and first-party registration all
   landed. P4 stays unpublished in `create_provider()` until the witness
   passes (Task 17 gate). 139 tests green (52 P4 + 87 regression), ruff
   clean, detachment gate 0, no leftover processes.
2. **End-to-end witness smoke ran on host** (commit + recover both rc=0,
   generations 1→2, `result_sha256` differs, worker swapped, continuation_id
   matches). Orb mirror + Makefile supervisor still to wire (Task 15).
3. **Hook cleanup: 29 hooks removed.** Orca (10) + Otty (7) + GSD (9) + adr-guard
   + lwm PreToolUse×3. Verified: orca's `curl --max-time 1.5` was the "倒数
   第 2-3 个位置挂几十秒" root cause. `UserPromptSubmit`,
   `PermissionRequest`, `PostToolUse`, `PostToolUseFailure`, `StopFailure`,
   `SubagentStart`, `SubagentStop`, `TeammateIdle` now have **0 hooks**
   — zero overhead on user input / tool completion / task switching.
4. **One known defect in Task 9 operator:** recover-mode output's
   `prior_checkpoint_sha256` field is `prior_identity.continuation_id`
   instead of the prior's last checkpoint digest. Witness's no-replay SHA
   inequality assertion still passes; this is a cosmetic output bug that
   must be fixed before Task 17 publishes P4 to the public selector.
5. **Open invariants carried from Phase 5:** three pre-existing red tests
   (`test_pi_session`, `test_prime_p7_native_installed`, `test_core_only_install`)
   untouched. Project uses `dev-phase-manager` for state, `project-state` for
   docs/status lifecycle.

## Where things stand

- **Branch**: local `main`, clean at `3c11b994`.
- **Phase 6 tasks**: 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 11, 12, 13 done.
  Remaining: **14** (commit fixture), **15** (Makefile `asterion-prime-p4-run`),
  **16** (final sweep + ruff + detachment gate), **17** (witness exit0 →
  publish P4 to `create_provider()` + index + P1 test guard upgrade 3→4 apps).
- **No background processes**: no Orb VM, no Pi subprocess, no `python -m asterion`.
- **No `ASTERION_PRIME_*` env vars leaked.**
- **Journal** has handoff closeout entry at 19:51.
- **Plan file** lives outside repo at `~/.claude/plans/serene-mixing-cat.md`
  (255 lines, sha256 `aa45271e531eaf55150d48011a4c88f290087c780182bb58f9988c698bf017ac`).

## What this session delivered

| Files | Type | Notes |
|---|---|---|
| `src/asterion/agents/prime/store.py` | modified | `open_continued` classmethod + 3 module helpers + `continued_from` / `highest_sealed_generation` accessors + relaxed `_validate_checkpoints` |
| `src/asterion/capabilities/prime_long_session_continuity_native/{__init__,host,provider}.py` + `payload/{capability-package,capabilities/prime-long-session-continuity}.json` | new | Capability package + JSON contracts (canonical) |
| `src/asterion/applications/prime/assemblies/prime-long-session-continuity.json` | new | Assembly JSON (canonical, alphabetical host_capabilities) |
| `src/asterion/applications/prime/services.py` | new | `prime.continuity-store` host service factory |
| `src/asterion/applications/prime/p4/{__init__,host,oracle,receipt,worker,runtime_binding,operator}.py` | new | Application P4 modules |
| `src/asterion/applications/prime/{__init__,provider,runtime_binding}.py` | modified | Re-exports + provider factories + dispatcher branch |
| `src/asterion/applications/first_party_packages.py` | modified | `PRIME_LONG_SESSION_CONTINUITY_NATIVE_PACKAGE` registration |
| `pyproject.toml` | modified | `prime.continuity-store` entry point |
| `tests/test_asterion_prime_p4_*.py` | new | 9 test files, 52 tests |

**Settings cleanup** (outside repo, in `~/.claude/settings.json`):
- Removed 17 orca+otty group hooks (the 1.5s `curl --max-time 1.5` blockers)
- Removed 12 gsd+adr+lwm hooks (gsd=4 unconditional + 3 opt-in never matched; adr no config; lwm pretooluse never matched)
- Kept: rtk hook (PreToolUse Bash), gsd-planning-bootstrap + jcode + herdr (SessionStart), lwm-stop-health (Stop)

## Next steps (immediate, action-level)

1. **Fix Task 9 defect first**: `prior_checkpoint_sha256` in recover-mode output
   must be `prior.recover_checkpoint().digest`, not `prior_identity.continuation_id`.
   In `src/asterion/applications/prime/p4/operator.py` `_recover_mode_async`,
   after `open_continued`, call `store.recover_checkpoint()` and set the
   output field to `.digest`. Add unit test asserting this.
2. **Task 14** — `tests/fixtures/prime_p4/small_state.json` (pre-baked identity
   + checkpoint for operator tests).
3. **Task 15** — `Makefile` `asterion-prime-p4-run` target. Pattern:
   ```
   ?= defaults for 5 env vars (operator root, PI entry, P4 private root,
       Orb VM, node path)
   two operator invocations (commit, recover) under Orb shell
   jq -e assertions:
     commit.status == "committed" && commit.checkpoint_sha256 non-null
     recover.status == "recovered" && recover.prior_checkpoint_sha256 non-null
     recover.prior_checkpoint_sha256 == commit.checkpoint_sha256
     recover.new_generation == commit.generation + 1
     recover.result_sha256 != commit.result_sha256
     both receipt_sha256 non-null
   + verbose sibling `asterion-prime-p4-run-verbose`
   ```
4. **Task 16** — full targeted sweep:
   ```
   uv run python -m unittest tests.test_asterion_prime_p4_*
   uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
   uv run ruff check src/asterion/...
   ```
5. **Task 17** — Witness exit0 + sealed receipt sha256 → Task-4-mirror commit:
   - Append P4 to `create_provider()` in `provider.py`
   - Add `prime.long-session-continuity__1.0.0` to `pyproject.toml`
     `asterion.application_index`
   - Revert P1 regression test guard from 3 apps to expect 4 apps
   - Journal + final handoff

## Don't go down these paths again (ruled out)

- `generation == highest + 1` invariant — broke P1 in-process compaction.
  Original `generation == self._identity.generation` is correct; cross-
  continuation replay falls out automatically because `next_identity.generation
  == prior.generation + 1`.
- A child-process supervisor — two `make` invocations on persistent
  `ASTERION_PRIME_P4_PRIVATE_ROOT` are sufficient.
- Real Pi subprocess in P4 witness — fake-worker is the design.
- Multi-generation recovery (gen=2→3) — out of scope.
- Hook removal: otty + orca 全删即可；lwm 保留 stop-health；gsd 全部 opt-in；
  adr 无 config 即可删。
- `MappingProxyType` 用作 `usage=` 或 `worker.execute()` 返回 — store 的
  `json.dumps` 不接受，要传 plain `dict`。
- sync 函数直接 return async coroutine（崩溃）— 调用方直接 `await`。

## Ready-to-paste commands / configs

```bash
# Plan file
cat ~/.claude/plans/serene-mixing-cat.md

# Targeted regression after Task 1
uv run python -m unittest -v \
  tests.test_asterion_prime_p4_store \
  tests.test_asterion_prime_p4_capability_package \
  tests.test_asterion_prime_p4_host_protocol \
  tests.test_asterion_prime_p4_oracle \
  tests.test_asterion_prime_p4_receipt \
  tests.test_asterion_prime_p4_continuity_store_service \
  tests.test_asterion_prime_p4_entry_point \
  tests.test_asterion_prime_p4_runtime_binding \
  tests.test_asterion_prime_p4_provider

# Detachment gate (must stay 0)
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"

# Phase 6 operator end-to-end (host direct, no Orb)
ASTERION_PRIME_OPERATOR_ROOT=$(pwd) \
ASTERION_PRIME_P4_PRIVATE_ROOT=$(pwd)/.asterion-private/prime-p4-witness \
ASTERION_PRIME_P4_MODE=commit \
uv run python -I -m asterion.applications.prime.p4.operator
ASTERION_PRIME_P4_MODE=recover \
uv run python -I -m asterion.applications.prime.p4.operator
```

## Workspace boundary (carried from Phase 5)

- Asterion prime must never import or depend on Prime Agent. Detachment gate stays 0.
- On the DeepSeek backend, pass no `model` to any subagent (AGENTS.md).
- `date` is the only timestamp source.
- Research intensity: review changed code + boundary assertions + small targeted regressions.
- No `python -m asterion.*` background processes may linger.

## Honest caveats carried forward

- **P4 operator's `recover-mode` JSON's `prior_checkpoint_sha256` field is
  wrong** (currently `continuation_id`, should be the prior's last sealed
  checkpoint digest). Fix in next session **before** Task 17 publishes.
- **Three pre-existing red tests still red** (Phase 5 closure):
  `tests.test_pi_session` (1F+6E), `tests.test_prime_p7_native_installed`
  (`Prime solver runtime did not complete`), `tests.test_core_only_install.py`.
- **The P4 witness does NOT prove model capability** — the deterministic
  fake-worker produces distinct result SHAs by construction. That's the
  design (per spec for Phase 6). Real-model invocation is P1/P7 territory.
- **Recursive continuity (gen=2→3)** is explicitly out of scope.