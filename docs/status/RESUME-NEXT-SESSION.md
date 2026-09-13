# Live Session Checkpoint

> Updated: 2026-09-14 00:05. **Session remains active — not a final handoff.**

## TL;DR

- Canonical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`. 9-phase roadmap + task-level Phase 1.
- **Phase 1 Task 1 landed, was reviewed, and was reopened.** The gate now covers the full release surface and reports **1881 violations** on the real tree. A second defect round (BOM-gating the UTF-16 fallback) is dispatched and not yet committed.
- The gate is the right thing to have built first: on its first two runs it caught a Prime source lock that both the spec inventory and the manual inventory had classified as native.

## 已验证事实

- Gate landed at `206dc04c`, defects fixed at `8c41f2cb`. 11 tests pass. Real-tree total **1881**: `legacy-prime-import` 1121, `prime-source-locator` 623, `prime-sdk-edge` 137.
- **The gate this one replaced was green while `src/asterion/applications/prime/p1/operator.py` carried six Prime execution edges** (`:934, :935, :963, :1019, :1035, :1083`). The old gate scanned only two paths against five literals.
- **`pyproject.toml:79-80` ship a Prime checkout lock.** `packages/typescript/asterion-prime-extension/resources/pi-compaction-lock.json` is 394 KB / 2891 digests, `format: asterion.pi-compaction-lock/v1`, `package_name: @earendil-works/pi-coding-agent`, `version 0.7.1`, `source_commit: a18809e00ea30638584d87b3afea7285a9d7296c` — the commit `CURRENT-STATE.md` calls "the pinned Prime source". Confirmations: the P1 shared-kernel plan resolves that package beneath `ASTERION_PRIME_SOURCE_ROOT`; `check_promotion.py:963-966` maps `pi-ai`/`pi-agent-core`/`pi-tui` to `external_prime_root/packages`; `npm view` returns E404 for the version. The detachment spec anticipates the relabeling. → REMOVE, corrected from an earlier native-KEEP call.
- **Three gate defects were introduced by the plan and found by independent review** (implementing agent, then a background security review): a coverage regression that dropped `primeSourceRoot`/`createAgentSession`/`loadPrimeSdk`; a fail-open that treated undecodable files as clean; and a fail-open where `SKIP_DIRS` matched absolute path parts, so a checkout under `build/`/`dist/`/`.venv/` silenced the whole scan. All fixed. A fourth (blind UTF-16 fallback) is dispatched.
- `ASTERION_PRIME_OPERATOR_ROOT` resolves to the Asterion repo root (`Makefile:302` passes `$(CURDIR)`, consumed at `operator.py:987`) and `ASTERION_PRIME_NODE` to a node executable — both legitimate, and a substring rule would false-positive on them.
- `asterion-prime-p1-run` is already installed-wheel and `operator.py:987-991` refuses source execution. `asterion-prime-p7-solve` is not (`PYTHONPATH=$(CURDIR)/src` + `../external-prime/arc-agi-3/venv/bin/python`).
- Scale: 429 test modules → **192 REMOVE / 10 REWRITE / ~205 SURVIVES** / 6 with-edit / 6 ambiguous. `prime-gateway` is 469 raw files but only **95 hand-written**.
- Only two fixture trees are coupled (`prime_gateway/`, `prime-parity/`); `prime_ecosystem/` content is clean.
- There are **no npm workspaces** in this repo.

## 当前判断

- Delete-first, per the spec's migration order. P1-P6 become unavailable; the spec prefers intermediate unavailability to a legacy fallback.
- Prime Gateway leaves, so H-035/H-036/H-037 evidence becomes historical and is reclassified in Task 11.

## 未完成边界

- Phase 1 Tasks 2-11 not started. No legacy surface removed yet.
- P7 not revalidated; no P1-P6 rebuilt.
- Open: `agent-client/v1` retention (Task 9 audit, explicit report required).
- Open: `../external-prime/arc-agi-3/venv/bin/python` — Phase 2 decides whether the ARC broker becomes an injected host service.

## Risks carried into later phases

1. **Native P7 may resolve compaction through the Prime checkout lock.** Expected, not a regression: the migration order places P7 revalidation after removal to surface exactly this. Do not restore the lock to make P7 pass.
2. **No detached Pi artifact has been shown to exist.** Every "pi"-named artifact inspected resolves under `ASTERION_PRIME_SOURCE_ROOT`. Phase 3 must name a genuinely detached one or report that none exists. If confirmed, P7's "already detached" premise needs re-evaluation.
3. **CI hard-fails on cache-key change.** `.github/workflows/ci.yml:26` hashFiles names prime-gateway lockfiles and `:27-29` exits 1 on a cache miss, so editing it fails the job until the npm cache is repopulated.

## 下一动作

1. Land the BOM-gating fix; confirm 13 tests and unchanged real-tree totals (1881 / `prime-sdk-edge` 137).
2. Task 2: pin the red baseline.
3. Tasks 3-11 in order. Task 11 Step 3 is the green-gate acceptance.

## Ready-to-paste commands

```bash
project-state resume
uv run python -m unittest -v tests.test_prime_source_detachment
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
git log --oneline -8
```

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`. `../external-prime/` is a separate external resource and is not covered by that prohibition.
- Do not restore Prime checkout dependencies to satisfy old tests, and do not weaken the gate to silence a red.
- Do not revive the multi-thousand-test promotion suite as a P1-P7 gate.
