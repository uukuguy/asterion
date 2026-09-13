# Live Session Checkpoint

> Updated: 2026-09-14 00:42. **Session remains active — not a final handoff.**

## TL;DR

- Canonical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`. Phase 1 is **4 of 11 tasks done**.
- Gate is finished and trusted: 15 tests, real tree **1856** (1105 `legacy-prime-import`, 614 `prime-source-locator`, 137 `prime-sdk-edge`, 0 `undecodable-surface-file`).
- **Phase 1 runs one writer at a time.** The gate scans the whole tree, so a scan is never valid while anything anywhere is uncommitted. This is a recorded discipline, not a preference — see the plan's "Execution discipline".

## 已验证事实

- Task 1 `9582dab0` — semantic release-surface gate. 15 tests OK.
- Task 2 `6fadf9b7` — red baseline. `test_gate_detects_the_known_p1_operator_edges` is the meaningful one and it passes (the gate sees `applications/prime/p1/operator.py`).
- Task 3 `bb6e23ee` — packaging surface removed. Entry points now **3 / 5 / 2** (`asterion.applications` / `application_index` / `host_services`). Gate 1881 → 1856, delta exactly the 25 `pyproject.toml` hits (−16 legacy-import, −9 locator, 0 sdk-edge). Protected ranges (`:91-108` schemas, `:110-115` sdist) intact.
- Task 3b `d57f7808` — an unreadable surface file is recorded as an `undecodable-surface-file` violation instead of aborting the scan. Fail-closed preserved at the assertion boundary; one bad file no longer masks every other finding.
- **Six gate defects were introduced by the plan and all were caught before shipping.** The three that mattered most: a coverage regression that dropped the Prime SDK tokens (137 real hits, 85 of them Prime SDK session construction in `prime-gateway/src/p*-development-session.ts`); a fail-open that treated undecodable files as clean; and a codec probe written as `info.encode(...) != b"..."` when `CodecInfo.encode` returns a `(bytes, length)` **tuple**, making it true for every codec and refusing every `.py` file.
- `pyproject.toml:79-80` shipped a **Prime checkout lock** (`pi-compaction-lock.json`, 394 KB, `source_commit a18809e0…`, `entry_points` under `packages/coding-agent/dist/*`) mislabelled as a native compaction lock. Both the spec inventory and the manual inventory had it as native. The gate caught it on its first run. Now REMOVE.
- **A concurrent-agent incident, resolved.** One agent's in-flight broken edit made another agent's scan abort on `src/asterion/immutable.py`; the second agent reported it as a transient concurrent read. It was deterministic — `immutable.py` is index 0 in `Path("src/asterion").rglob("*.py")`, the first `.py` the broken gate tried.

## 当前判断

- Delete-first per the spec's order. P1-P6 go unavailable.
- Prime Gateway leaves, so H-035/H-036/H-037 evidence is reclassified historical in Task 11.
- The gate's limits are documented rather than implied: line-local literal matching only; `SCAN_ROOTS` excludes `docs/scripts/schemas`; the allowed-env-var scrub can manufacture a false positive; no line-continuation awareness.

## 未完成边界

- Phase 1 Tasks 4-11 **not started**. No legacy package, Make target, TypeScript surface, or test has been deleted yet — only `pyproject.toml` references.
- P7 not revalidated; no P1-P6 rebuilt.
- Open: `agent-client/v1` retention (Task 9 audit, explicit report required).
- Open: `../external-prime/arc-agi-3/venv/bin/python` — Phase 2 decides whether the ARC broker becomes an injected host service.

## Risks carried into later phases

1. **Native P7 may resolve compaction through the Prime checkout lock.** Expected; the migration order places P7 revalidation after removal to surface it. Do not restore the lock to make P7 pass.
2. **No detached Pi artifact has been shown to exist.** Every "pi"-named artifact inspected resolves under `ASTERION_PRIME_SOURCE_ROOT`. Phase 3 must name a genuinely detached one or report that none exists.
3. **CI hard-fails on cache-key change.** `.github/workflows/ci.yml:26` hashFiles names prime-gateway lockfiles and `:27-29` exits 1 on a miss.

## 下一动作

1. Task 4 — remove the legacy Make surface: `ASTERION_PRIME_SOURCE_ROOT` / `_AUTHORITY` / `_MAX_COST_MICROS`, `prime-check`, `prime-setup`, `prime-p{1..7}-run`, `prime-apps-preflight`, `prime-verify-bounded`, `prime-verify-native-rlm-bounded`, `test.prime-long-running.bounded`, `test.prime-continual-harness.bounded`; strip the variable from `promotion-check`; sync `.PHONY` and `help`.
2. Tasks 5-11 in order, **one writer at a time**. Task 11 Step 3 is the green-gate acceptance.

## Ready-to-paste commands

```bash
project-state resume
uv run python -m unittest tests.test_prime_source_detachment
uv run python -c "from pathlib import Path; from collections import Counter; from asterion.agents.prime.detachment import find_source_detachment_violations as f; v=f(Path('.')); print(len(v), dict(Counter(x.rule for x in v)))"
git log --oneline -8
```

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`. `../external-prime/` is a separate external resource and is not covered by that prohibition.
- Do not restore Prime checkout dependencies to satisfy old tests, and do not weaken the gate to silence a red.
- Do not revive the multi-thousand-test promotion suite as a P1-P7 gate.
- Three stale sibling worktrees exist on `codex/*` branches (`asterion-p1-workload`, `asterion-p2-worker`, `asterion-p3-real-rlm`, all 2026-09-03). They are outside this work and were not touched.
