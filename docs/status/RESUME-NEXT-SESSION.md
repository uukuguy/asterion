# Live Session Checkpoint

> Updated: 2026-09-14 10:20. **Session remains active — not a final handoff.**

## TL;DR

- **Phase 1 is complete** (11/11). The detachment gate reports **0** violations on the real tree, down from 1881. Working tree clean.
- Every legacy Prime Agent execution surface is out of the distribution: packaging, Make, the P1 operator's inner couplings, the five legacy Python packages, the Prime Gateway TypeScript package, ~250 coupled test modules, and the tools that drove the checkout.
- **P1-P7 are all unavailable by design.** P1-P6 have no selector and no native implementation. P7 was the working anchor, but its selected route reached into Prime Agent's Pi dependency, so it too is now unavailable pending Phases 2-3. This is the spec's required intermediate state, not a regression.

## 已验证事实

- Task 3 `bb6e23ee` entry points **3 / 5 / 2**. Task 4 `701bde75` removed the Make surface. Task 5 `ba89a4de` excised six Prime edges from the P1 operator. Task 6a/6b `9bb16435` + `6df54d35` deleted the five legacy packages (242 files, −55,606 lines). Task 7 `019e2c48` removed Prime Gateway TS. Task 8 `663a0dab` removed 204 coupled test modules. Tasks 9-10 `47a839dc`. Task 11 `f4fbc250`.
- **The gate is frozen and honest.** 23 tests; its docstring states the precise claim it supports (no forbidden token as a contiguous literal on one line, in a readable file with a scanned suffix under a scanned root) and names the accepted evasion (runtime-assembled tokens). It is a regression guard, not an adversarial control.
- **`pi/` clarified by the user.** `./pi/` is gitignored, untracked, and is *the modified Pi that Prime Agent depends on*. **Asterion never had that premise from the start of its construction.** `runtimes/pi_rpc.py` takes its Pi command by injection, so Asterion does not hardcode a Pi path. The spec's "separately pinned Pi runtime" is therefore a Pi the operator supplies or pins separately — *not* Prime Agent's fork. ASTerion's own Pi extension resources live at `capabilities/dci/resources/pi/`.
- Two hidden import-breaks were caught by construction rather than by test: `capabilities/builtin.py` (a re-export shim) and `tools/check_promotion.py:17` (a top-level import of a to-be-deleted package, consumed by the surviving `make promotion-check`).
- `agent-client/v1` is **retained**: consumed by the surviving `asterion.client` surface, framework-level, not Prime-Gateway-backed.
- The Prime Gateway-backed closure claims (H-035, H-036, H-037, `interfaces.operations` 15/15, system parity 61 passed) are now recorded as **historical**, not native closure.

## 当前判断

- Delete-first is done. The remaining work is construction, not removal.
- The gate will stay at 0 unless something is reintroduced; do not re-harden it.
- P7's revalidation (Phase 3) depends on Phase 2 producing an installed-wheel preset that injects a Pi command *without* reaching Prime Agent's tree.

## 未完成边界

- **Phases 2-9 are all unstarted.** No application has been rebuilt. P1-P7 native implementations: **0 of 7**.
- No legacy surface was removed beyond Phase 1's scope; the Rust `executor.controlled` surface was never checked for Prime references.
- Phase 2 owns: converting `asterion-prime-p7-solve` to an installed-wheel invocation, and removing the `PYTHONPATH=$(CURDIR)/src` + `../external-prime/arc-agi-3/venv/bin/python` source-tree invocation.

## Risks carried into Phases 2-3

1. **P7 needs a Pi the operator supplies.** Its selected route previously reached `pi/packages/coding-agent/dist/rpc-entry.js`. Phase 2 must wire an injected Pi command; if no usable Pi artifact is obtainable, Phase 3 cannot revalidate P7 and that must be reported rather than worked around.
2. **Do not restore the Prime compaction lock** to make P7 pass. It was a Prime checkout lock mislabelled native.
3. **CI cache key.** `.github/workflows/ci.yml` no longer names the prime-gateway lockfiles; the npm cache must be repopulated or the job exits 1 on a cache miss. Operator action, not a code fix.

## 下一动作

1. **Phase 2** — convert the P7 research preset to an installed-wheel invocation and give it an injected Pi command.
2. Then Phase 3 (P7 revalidation), then Phases 4-9 (rebuild P1, P2, P4, P3, P5, P6).

## Ready-to-paste commands

```bash
project-state resume
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"   # expect 0
uv run python -m unittest tests.test_prime_source_detachment   # expect 23 OK
git log --oneline -8
```

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`. `../external-prime/` is a separate external resource and is not covered by that prohibition.
- `./pi/` is gitignored and untracked — it is Prime Agent's modified Pi, not Asterion's. Asterion must not reach into it; do not add it to git.
- Do not restore Prime checkout dependencies to satisfy old tests, and do not weaken the gate to silence a red.
- **Research intensity:** review changed code plus boundary assertions, run small targeted regressions. Do not re-run full suites or harden tooling.
