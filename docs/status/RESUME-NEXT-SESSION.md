# Next-Session Handoff

> Updated: 2026-09-14 14:15 end of session.

## TL;DR

- **Phase 1 complete (11/11).** Every legacy Prime Agent execution surface is out of the distribution; the detachment gate reports **0** violations, down from 1881.
- **The application layer carries zero Pi references.** `src/asterion/applications/prime/**` no longer names Pi anywhere; the runtime seam is `prime.launch` + `asterion.runtime.{pinned_extension,native_rpc}`.
- **P1-P7 native implementations: 0 of 7. All unavailable by design.** P1-P6 never had native implementations; P7 did, but its route reached into Prime Agent's Pi dependency, so it is unavailable pending Phases 2-3. Not a regression — the spec's required intermediate state.
- **Model routing changed for this backend:** flash only, no per-agent `model` (see AGENTS.md). Passing an alias selects the *most expensive* tier.

## 已验证事实

Evidence: commits, tests, measured counts.

- **Phase 1 tasks, all committed:** gate `9582dab0` (23 tests) → packaging `bb6e23ee` (entry points 3/5/2) → Make `701bde75` → P1 operator `ba89a4de` → legacy packages `9bb16435` + `6df54d35` (242 files, −55,606 lines) → Prime Gateway TS `019e2c48` (97 files) → coupled tests `663a0dab` (204 modules + 2 fixture trees) → gates/docs `47a839dc` → evidence reclassification `f4fbc250`.
- **Gate: 0 violations** on the real tree (from 1881). 23 tests pass. Frozen; do not re-harden.
- **Deleted overall:** ~543 files across packaging, Make, Python packages, TypeScript, tests and tools.
- **Application-layer Pi removal `94bfe017`:** 30 Pi references across 35 files → **0**. `grep -rnE 'Pi[A-Z]|pi_extension|pi_rpc|runtimes\.pi' src/asterion/applications/prime/` returns nothing. 70 targeted tests pass. Gate still 0.
- **Seam neutralization `d89e48dd`:** `prime.pi-extension` (implementation-named, carrying live Pi objects) → `prime.launch` (plain data: argv, env, resource identity, acquired fds).
- **`agent-client/v1` is RETAINED** — consumed by the surviving `asterion.client` surface; framework-level, not Prime-Gateway-backed.
- **Prime Gateway-backed closure claims are now historical:** H-035, H-036, H-037, `interfaces.operations` 15/15, system parity 61 passed.
- **`pi/` clarified by the user:** it is the *modified Pi that Prime Agent depends on*, gitignored and untracked. **Asterion never had that premise.** `runtimes/pi_rpc.py` takes its Pi command by injection, so Asterion does not hardcode a Pi path. The `run_asterion_prime_p7.py` reach into `pi/packages/coding-agent/dist/rpc-entry.js` was therefore a coupling into Prime Agent's dependency tree, and its removal was correct.
- **DeepSeek model routing measured:** the Anthropic-compatible endpoint maps **any** `claude-*` model name to `deepseek-v4-pro` (verified: `claude-opus-4-7` → `deepseek-v4-pro`; bare `opus` is rejected). The `Agent` tool's `model` parameter accepts only `sonnet/opus/haiku/fable`, so any alias selects the most expensive tier — inverting the intent of difficulty-based routing. `ANTHROPIC_SMALL_FAST_MODEL` had been unset until this session and is now set in `~/openai-coding-deepseek.sh`.

## 当前判断

Direction chosen on current evidence; not yet proven end-to-end.

- **Phase 1's work is removal; the remaining work is construction.** The gate is a regression guard, not a proof of detachment — it matches contiguous literals and states its own limits in its docstring.
- **The runtime seam is neutral by *name*, not yet by *type*.** `asterion.runtime.native_rpc` re-exports `PiRpcSession` as `RpcSession`. Deliberate: abstracting for a second runtime that does not exist would likely abstract the wrong shape. Revisit when a second runtime is real.
- **`asterion.runtime.pinned_extension` is a genuine relocation** — the lease machinery was already generic (stdlib + `asterion.immutable` only).
- **P7 cannot be revalidated until Phase 2 supplies an installed-wheel preset with an injected Pi command.** Which Pi the operator supplies is an open question Asterion's architecture does not decide.

## 历史归档

Rejected or superseded paths, recorded so they are not re-walked.

- **"`pi` is a Prime Agent checkout relabelled."** My inference, and it was wrong in mechanism: `packages/coding-agent` etc. are the *pi-monorepo* layout, which both share. The correct statement is the user's: `pi/` is Prime Agent's modified Pi, and Asterion never depended on it.
- **"Find a genuinely detached Pi runtime."** A phantom goal — it assumed Asterion needed one. It does not.
- **Gate hardening rounds 1-5.** Five defect rounds and two silent-skip lists, several hours. The gate is a support tool; the deliverable was never the gate. AGENTS.md already said not to over-invest in testing.
- **"The gate's coverage gap is theoretical."** No — it was green while the native P1 operator carried six Prime execution edges, and it caught a Prime checkout lock mislabelled as a native compaction lock on its first run.
- **Parallel subagents on "disjoint files".** Not safe here: the gate reads the whole tree, so any in-flight edit invalidates a concurrent scan. One writer at a time.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **Phases 2-9 are entirely unstarted.** No application rebuilt. No native P1-P7 implementation exists for P1-P6, and P7's is present but unreachable without a Pi.
- **The fd-pinning (TOCTOU) property was reported preserved but not independently reproduced by me.** The implementing agent verified it adversarially (rewrote the extension path; the pinned fd still returned the original bytes); I did not re-run that check.
- **The Rust `executor.controlled` surface was never checked** for Prime references.
- **CI cache:** `.github/workflows/ci.yml` no longer names the prime-gateway lockfiles. The job exits 1 on a cache miss, so the npm cache needs repopulating — an operator action, not a code fix.
- **`docs/` is excluded from the gate's scan roots** by design; a checkout path written into a plan or guide would pass untouched.
- **`prime.launch` still requires a Pi-typed lease** (`asterion.runtime.pinned_extension.ExtensionLease` is generic, but the payload is validated with an exact-type check), so a non-Pi runtime still cannot satisfy it.

## 下一动作

1. **Phase 2** — convert the `asterion-prime-p7-solve` preset from a source-tree invocation (`PYTHONPATH=$(CURDIR)/src` + `../external-prime/arc-agi-3/venv/bin/python`) to an installed-wheel invocation, with an injected Pi command that does not reach Prime Agent's `pi/` tree.
2. Then Phase 3 (P7 revalidation), then Phases 4-9 (rebuild P1, P2, P4, P3, P5, P6).

## Ready-to-paste commands

```bash
project-state resume
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"   # expect 0
uv run python -m unittest tests.test_prime_source_detachment   # expect 23 OK
grep -rnE 'Pi[A-Z]|pi_extension|pi_rpc|runtimes\.pi' src/asterion/applications/prime/   # expect nothing
git log --oneline -8
```

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`. `../external-prime/` is a separate external resource and not covered by that prohibition.
- **`./pi/` is gitignored and untracked** — it is Prime Agent's modified Pi, not Asterion's. Do not add it to git, and do not reach into it from Asterion code.
- Do not restore Prime checkout dependencies, do not restore the Prime compaction lock, and do not weaken the gate to silence a red.
- **On the DeepSeek backend, pass no `model` to any subagent** (see AGENTS.md).
- **Research intensity:** review changed code plus boundary assertions, run small targeted regressions. Do not re-run full suites or harden tooling.
- Three stale sibling worktrees exist on `codex/*` branches (`asterion-p1-workload`, `asterion-p2-worker`, `asterion-p3-real-rlm`, 2026-09-03). Outside this work; untouched.
