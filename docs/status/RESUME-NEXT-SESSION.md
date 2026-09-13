# Live Session Checkpoint

> Updated: 2026-09-13 23:14. **Session remains active — not a final handoff.**

## TL;DR

- Canonical worklist exists now: `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md` (commit `1c9d2a67`). It supersedes the previous handoff's "no unified implementation plan has been written" boundary.
- Phase 1 is **gate-first**: the semantic source-detachment gate is implemented *before* any deletion, and becomes the executable definition of "removal complete". The plan therefore does not enumerate the removal in prose.
- Currently executing **Task 1** (expand the gate + its tests) via subagent.

## 已验证事实

- The design spec was read in full and is consistent with `DECISIONS.md` D-2026-09-12-01 — no conflict, no supersession needed.
- Pre-change baseline: `make docs-check` PASS (207 markdown files, 57 local links). Working tree clean at `f1d28b9e`; `main == origin/main`.
- **The existing gate's coverage gap is proven, not assumed.** `src/asterion/agents/prime/detachment.py` scans only `src/asterion/agents/prime/` + `src/asterion/runtimes/asterion_prime.py` against 5 literal tokens, and is **green today** while `src/asterion/applications/prime/p1/operator.py` carries six Prime execution edges at `:918` (`source_root` field), `:934-935` (dynamic import of `packages/coding-agent/dist/config.js` and `.../core/compaction/compaction.js`), `:963` (launches `coding-agent/dist/main.js`), `:1019` (`ASTERION_PRIME_SOURCE_ROOT` default `3th-party/prime-agent`), `:1035` (locks `asterion.control.providers.prime`), `:1154` (threads `source_root`).
- `ASTERION_PRIME_OPERATOR_ROOT` is **not** a Prime checkout locator: `Makefile:302` sets it from `$(CURDIR)` (the Asterion repo root) and `operator.py:987` consumes it. `ASTERION_PRIME_NODE` is a resolved node-22 executable path. Both are legitimate; the gate must not reject them. A substring rule on `PRIME.*ROOT` would false-positive — this is why the gate must be semantic.
- `asterion-prime-p1-run` (`Makefile:297-302`) is already an installed-wheel invocation, and `operator.py:987-991` actively refuses source execution of the *asterion* package. `asterion-prime-p7-solve` (`Makefile:293-295`) is **not** — it exports `PYTHONPATH="$(CURDIR)/src"` and uses `../external-prime/arc-agi-3/venv/bin/python`.
- `prime.ipython-coding__1.0.0` already resolves to the native provider `asterion.applications.prime`, but its assembly requires five host services (`prime.ipython`, `prime.p1-oracle`, `prime.pi-extension`, `prime.private-trace`, `prime.session-backend`) that have **no entry point**; only the forbidden legacy `prime.ipython-production` supplies P1 today. Its index row must therefore be omitted in Phase 1.
- Scale: ~180 of 428 test modules are coupled to a legacy surface.
- Breakage radius of the removal (KEEP targets that die): `check`, `promotion-check`, `test-typescript`, `help`, ~17 `test.prime-*.provider-free` targets, `prime-parity-inventory`, `prime-verify-system-parity`. Five `test.prime-*.provider-free` targets are Python-only and survive.

## 当前判断

- **Delete-first order**, per the spec's mandated migration order. P1-P6 become unavailable; the spec explicitly prefers intermediate unavailability to a legacy fallback or a false native claim.
- The Prime Gateway stack leaves the distribution, so the H-035 / H-036 / H-037 evidence machinery goes with it and its evidence is reclassified **historical** in Task 11. `CURRENT-STATE.md`'s "Verified Boundary" section leans on those claims today and will be corrected there.
- Phases 3-9 get their own plans when reached; they are not pre-choreographed in the current plan.

## 未完成边界

- Phase 1 Tasks 1-11 are **not** complete. No legacy surface has been removed yet.
- P7 has **not** been revalidated after detachment. No P1-P6 application has been rebuilt.
- Open decision (Task 9, audit-gated): retention of the non-core v1 schemas, especially `agent-client/v1`. Its evidence was Prime Gateway-backed but the contract may be framework-level; flagged for explicit reporting rather than a silent call.
- Open decision (Phase 2): whether the ARC broker is injected as a host service rather than referenced as `../external-prime/arc-agi-3/venv/bin/python`.
- The Rust `executor.controlled` surface has not been checked for Prime references.

## 下一动作

1. Land Task 1 (expanded gate + 8 tests). Confirm the real-tree test from Task 2 fails and **names `src/asterion/applications/prime/p1/operator.py`** — a gate that misses the documented P1 edges must be fixed before proceeding.
2. Execute Phase 1 Tasks 2-11 in order. Task 11 Step 3 is the green-gate acceptance.

## Ready-to-paste commands

```bash
project-state resume
sed -n '1,120p' docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md
uv run python -m unittest -v tests.test_prime_source_detachment
git log --oneline -5
```

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`.
- `../external-prime/` is a separate external resource and is **not** covered by that prohibition.
- Do not restore Prime checkout dependencies to satisfy old tests.
- Do not push unless explicitly requested. Do not revive the multi-thousand-test promotion suite as a P1-P7 gate.
