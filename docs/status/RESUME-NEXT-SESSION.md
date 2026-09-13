# Live Session Checkpoint

> Updated: 2026-09-14 01:40. **Session remains active — not a final handoff.**

## TL;DR

- Canonical worklist: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`. Phase 1 is **7 of 11 tasks done**; Task 6 is executing.
- Gate is complete: **23 tests**, real tree **1908** (1102 `legacy-prime-import`, 593 `prime-source-locator`, 76 `prime-gateway-reference`, 137 `prime-sdk-edge`).
- **Phase 1 runs one writer at a time.** The gate walks the whole tree, so a scan is never valid while anything anywhere is uncommitted.
- **P1 is now genuinely unavailable** — `_preflight` raises `P1OperatorError()` and `main()` exits 2. That is the spec's required intermediate state, not a regression.

## 已验证事实

- **T1** `9582dab0` — semantic release-surface gate. **T2** `6fadf9b7` — red baseline; the meaningful test (gate sees `applications/prime/p1/operator.py`) passes.
- **T3** `bb6e23ee` — packaging surface. Entry points **3 / 5 / 2**. **T3b** `d57f7808` — an unreadable file is recorded, not an abort.
- **T4** `701bde75` — Make surface: −122 lines, all legacy targets and `ASTERION_PRIME_SOURCE_ROOT`/`_AUTHORITY`/`_MAX_COST_MICROS` gone; `promotion-check` keeps `ASTERION_PRIME_NODE`. Verified: `make help` and `make -n test.framework-core` both exit 0.
- **Round 5** `8291f192` — 15 → 23 tests. Closed the silent-skip class: `os.walk` per root, `followlinks=False`, prune `SKIP_DIRS` then record `symlinked-directory`, `ENOENT` = absent, case-insensitive suffixes, `.github/` + `.yml`, and a new `prime-gateway-reference` rule (**+76**). Delta: `legacy-prime-import` +0, `prime-sdk-edge` +0, `prime-source-locator` +1 (the newly visible `ci.yml`).
- **`#1` confirmed in the strongest form:** all four structural rules are 0 on the real tree and *the set of disappeared findings is empty* — swapping `rglob` for `os.walk` lost nothing.
- **The gateway rule found a plan gap on a retained file.** `tools/check_promotion.py` has six sites, not the two the plan enumerated: `:240,242` assembly paths and `:1090,1372,1374,1450` gateway paths. `:1090` copied the deleted package's `prime-artifact-lock.json` into the distribution. All six now specified in Task 10.
- **T5** `ba89a4de` — the six Prime execution edges excised from `applications/prime/p1/operator.py`. Gate 1925 → 1908. `_preflight` keeps only its native source-execution guard and then raises `P1OperatorError()`; `main()` prints `preflight-rejected` and exits 2. `_Preflight`, `_pi_command`, `_PRICE_PROBE`, `_build_resources` and twelve unused imports are fully deleted — no stub, no fallback, no vestigial field.
- **Six native functions are now unreachable from `main()` and deliberately retained:** `P1OperatorResources`, `run_fixed_small_verification`, `_P1Bridge`, `_force_close_pi`, `_run_operator`, `_public_progress`. They carry no Prime edge, 18 passing tests pin their contracts, and Phase 4 rebuilds on them. **A type checker reports all six as unaccessed — do not delete them as dead code.** Recorded in the plan as a Task 5 post-condition.
- **Six gate defects, all introduced by the plan, all caught before shipping.** The three worst: dropped Prime SDK tokens (137 real hits); undecodable files treated as clean; and a codec probe `info.encode(...) != b"..."` where `CodecInfo.encode` returns a `(bytes, length)` **tuple**, making it true for every codec and refusing every `.py` file.
- **`pyproject.toml:79-80` shipped a Prime checkout lock** (`pi-compaction-lock.json`, `source_commit a18809e0…`, entry points under `packages/coding-agent/dist/*`) mislabelled native. Both the spec inventory and the manual inventory had it as native; the gate caught it on its first run.

## 当前判断

- Delete-first per the spec's order. P1-P6 go unavailable; the spec prefers that to a legacy fallback.
- Prime Gateway leaves, so H-035/H-036/H-037 evidence is reclassified historical in Task 11.
- The gate is a **regression guard, not an adversarial control**. Its docstring now states the precise claim: no forbidden token as a contiguous literal on one line, in a readable file with a scanned suffix under a scanned root. Known accepted evasion: runtime-assembled tokens (`"ASTERION_PRIME_" "SOURCE_ROOT"`, `importlib`, f-strings, cross-line splits) — documented beside that claim, not deferred.

## 未完成边界

- Tasks 6-11 open. No legacy Python package, TypeScript surface, tool, or test has been deleted yet — only `pyproject.toml` and `Makefile` references, plus the P1 operator's inner couplings.
- P7 not revalidated; no P1-P6 rebuilt.
- Open: `agent-client/v1` retention (Task 9 audit, explicit report required).
- Open: `../external-prime/arc-agi-3/venv/bin/python` — Phase 2 decides whether the ARC broker becomes an injected host service.

## Risks carried into later phases

1. **Native P7 may resolve compaction through the Prime checkout lock.** Expected; migration order surfaces it. Do not restore the lock to make P7 pass.
2. **No detached Pi artifact has been shown to exist.** Every "pi"-named artifact inspected resolves under `ASTERION_PRIME_SOURCE_ROOT`. Phase 3 must name a genuinely detached one or report that none exists.
3. **CI hard-fails on cache-key change.** `.github/workflows/ci.yml:26` hashFiles names prime-gateway lockfiles; `:27-29` exits 1 on a miss. The gate now sees this file (the +1 locator hit).

## 下一动作

1. Task 6 — delete `applications/prime_agent/`, `capabilities/prime_agent/`, `runtimes/prime_agent.py`, `runtimes/prime_agent_host.py`, `control/providers/prime/`; edit `first_party_packages.py` (preserving the two native packages) and `tests/core_module_allowlist.py` (dropping legacy prefixes only). Its Step 1 external-importer grep is a gate: any hit means stop.
2. Tasks 7-11 in order, one writer at a time. Task 11 Step 3 is the green-gate acceptance.

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
- Three stale sibling worktrees exist on `codex/*` branches (`asterion-p1-workload`, `asterion-p2-worker`, `asterion-p3-real-rlm`, 2026-09-03). Outside this work; untouched.
