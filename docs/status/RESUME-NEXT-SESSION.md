# Live Session Checkpoint

> Updated: 2026-09-14 17:10. **Session remains active — not a final handoff.**

## TL;DR

- **Phase 2 complete and independently verified.** The P7 research preset is now
  an installed-wheel invocation: it builds a wheel, unsets `PYTHONPATH`, and
  supplies the ARC engine as an operator-owned root plus pure-Python wheels.
- **Gate 0 before and after.** `tests/test_prime_make_presets` passes (2 tests),
  and `make -n asterion-prime-p7-solve` shows the intended shape.
- **Active work package is now Phase 3** — revalidate native P7 with no Prime
  checkout, against the preset Phase 2 built.
- **One open finding, deliberately not pre-cleared:** see below.

## 已验证事实

Evidence: commits, tests, measured counts.

- **Phase 2 commits:** `9a38405a` (feature), `d9aa71b5` (journal),
  `081d5196` (plan + decision + verification docs).
- **Gate: 0** both with the Phase 2 changes stashed and applied.
- **Phase 2 changed:** `Makefile` (+13, `.PHONY` + preset),
  `src/asterion/applications/prime/p7/live.py` (new, 911 lines — operator-side
  plumbing recovered from the deleted driver), `p7/operator.py` (+343,
  `P7Invocation` / `_preflight` / `run_live` / `main` / `_entrypoint`),
  `tests/test_prime_make_presets.py` (+54).
- **`p7/` gained exactly one new module** (`live.py`). The type diagnostics
  naming `run.py` / `entrypoint.py` come from a test-generated temp fixture
  under `/private/tmp/asterion-prime-p7-installed-*/`, not from the repo.
- **The preset asks for no provider, model, cost or deadline knob** — only for
  where the external engine lives (`ASTERION_PRIME_ARC_ROOT`). An unset root
  fails closed at preflight (status 2) before any build or Orb entry.
- **The P7 entrypoint rejects any argv**, mirroring P1: the only external input
  is the literal Make preset invocation.
- **Open question 3 (Rust) closed clean:**
  `grep -rniE 'prime|pi_rpc|pi_extension' packages/rust/` returns nothing.

## 🔴 Open finding — `tests/test_prime_p7_native_installed` is red

Verified on a clean HEAD, not assumed:

- It **fails on the pristine tree**, reproduced with all Phase 2 changes stashed.
- It is **referenced by no gate** — `Makefile`, `.github/` and `tools/` contain
  zero references. Only two historical plan documents mention it. **No gate
  could ever have observed this file going red.**
- Its failure surfaces through a **catch-all `except Exception`** at
  `src/asterion/agents/prime/execution.py:471`, which emits a generic
  `asterion_prime_failed` and **discards the exception**. A temporary
  `print_exc` probe there did **not** fire, so the failure does not originate at
  that site either — the cause is still unlocated.
- The test predates the runtime-seam change (added `1d850d38` 2026-09-09, last
  touched `1f3993dd` 2026-09-10; seam change `d89e48dd` 2026-09-14).

**How to read this.** It is **not** evidence of a Phase 2 regression. It is
**also not** evidence of health: because it sits outside every gate, its
last-green date is unknown. Do not treat it as a pre-cleared item. It is Phase
3's first diagnostic — and the catch-all that hides its cause is itself an
obstacle Phase 3 should remove first.

A bisect attempt was abandoned: a pre-seam worktree fails for an unrelated
reason (no `node_modules`, so the ipython extension `npm run build` exits 2).

## 当前判断

Direction chosen on current evidence; not yet proven end-to-end.

- **Phase 2 proves the invocation shape, not the route.** P7 has not been shown
  to complete a run from the wheel. **P1-P7 native implementations remain 0 of
  7**, all unavailable.
- **D-2026-09-14-02** records the external-engine shape. Rejected and worth not
  re-walking: a cross-process ARC host service (`ArcBroker` already takes its
  engine as a Protocol, so it is reachable — but it rewrites P7 application
  logic, which the spec forbids).

## 历史归档

Rejected or superseded paths, recorded so they are not re-walked.

- **"Phase 2 is a conversion."** It is a rebuild — Phase 1 Task 4 had already
  deleted the target and its 1006-line driver.
- **Sibling-relative engine resolution** (`root.parent / "external-prime" / …`).
  That is the coupling the Phase 1 gate exists to catch.
- **An external venv interpreter for the IPython worker.** The isolated
  environment's own interpreter is used; `ipython` arrives by `--with`.
- **Gate hardening rounds 1-5** (Phase 1). The gate is a support tool, not the
  deliverable. Do not re-harden it.
- **Parallel subagents on "disjoint files".** Not safe: the gate reads the whole
  tree, so any in-flight edit invalidates a concurrent scan. **One writer.**

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **Phases 3-9 unstarted.** No application rebuilt or revalidated.
- **No live P7 solve has been run.** The ARC root and wheels are only
  exercisable inside Orb; `arc_agi` is not importable locally.
- **Phase 3 carries two known risks from the plan**, both *expected* failures:
  P7 may still resolve compaction through the removed Prime checkout lock (do
  **not** restore the lock to make it pass), and the "separately pinned Pi
  runtime" the spec calls an allowed foundation may not exist in detached form
  — Phase 3 must name it or report that it does not exist.
- **A new Pi injection name was introduced by Phase 2:** `ASTERION_PRIME_PI_ENTRY`,
  paired with `ASTERION_PRIME_NODE`, with Asterion owning the fixed RPC flag set.
  It is not yet recorded in DECISIONS.md as its own decision.
- **The fd-pinning (TOCTOU) property** was reported preserved but never
  independently reproduced.

## 下一动作

1. **Phase 3** — revalidate native P7 with no Prime checkout, against the wheel
   preset. Start by locating the `test_prime_p7_native_installed` cause, and
   remove the `execution.py:471` catch-all that hides it.

## Ready-to-paste commands

```bash
project-state resume
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"   # expect 0
uv run python -m unittest -v tests.test_prime_make_presets        # expect 2 OK
make -n asterion-prime-p7-solve                                   # PYTHONPATH must never name a source tree
uv run python -m unittest tests.test_prime_p7_native_installed    # currently FAILS — see open finding
git log --oneline -6
```

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`. `../external-prime/` is a
  separate external resource and not covered by that prohibition.
- **`./pi/` is gitignored and untracked** — Prime Agent's modified Pi, not
  Asterion's. Do not add it to git or reach into it from Asterion code.
- Do not restore Prime checkout dependencies, do not restore the Prime
  compaction lock, and do not weaken the gate to silence a red.
- **On the DeepSeek backend, pass no `model` to any subagent** (see AGENTS.md).
- **Research intensity:** review changed code plus boundary assertions, run small
  targeted regressions. Do not re-run full suites or harden tooling.
- Three stale sibling worktrees exist on `codex/*` branches
  (`asterion-p1-workload`, `asterion-p2-worker`, `asterion-p3-real-rlm`,
  2026-09-03). Outside this work; untouched.
