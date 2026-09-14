# Live Session Checkpoint

> Updated: 2026-09-14 22:27. **Session remains active — not a final handoff.**

## TL;DR

- **Phases 1, 2 and 3 are complete.** The detachment gate is 0, the P7 preset is
  an installed-wheel invocation, and **native P7 was revalidated by a passing
  live run** driven by an independently installed upstream Pi.
- **Active work package is now Phase 4** — rebuild P1 (`prime.ipython-coding`).
- The P7 anchor is proven, not inferred: Level 1 of `ls20-9607627b` solved in 20
  primitive actions and 40 cells with the trace sealed and replay verified.

## 已验证事实

Evidence: commits, a passing run, measured counts.

- **Live run `p7-live-20260914141314` PASSED.** `completed_level_count` 1,
  `primitive_action_count` 20, 40 worker cells, `partial_game_score` 3.571429,
  `terminal_reason` `level-completed`, `replay_verified` / `sealed_trace` /
  `cleanup_complete` all true, `promotion: unpromoted`, `failure: null`.
  Receipt `c00e3263cb2842dbe854cd4950ea2d2ec75859c21189f2bb101e66efed05c554`;
  replay `sha256:5b469c2ab7acfcb61d643d885453f744ef201d2a7765bcac1e04b0ac7afaea1b`.
  Private artifact `.asterion-private/prime-p7-live/p7-live-20260914141314/`
  (0700, gitignored). Solve window 22:13:17 → 22:17:46, ~4.5 minutes.
- **The detached Pi exists and is named:** `@earendil-works/pi-coding-agent`
  (npm upstream, MIT, no prime-agent dependency), a different build from the
  `./pi/` checkout. Plan risk 2 is resolved **in the affirmative**.
- **Phase 3's red test is fixed.** `26519254` made `agent_end` the native round
  terminal and stopped recognizing `agent_settled`, updating five test files but
  not the shared fixture. One-line fixture fix; the P7 set is 47 tests green.
- **Gate 0** before and after every change in this session.

## 当前判断

- **P7's application logic was not rewritten** — the phase was revalidation, and
  it passed on the route Phase 2 built.
- **Phase 3's completion is bounded.** It proves the installed route and
  Level-1 solving on `ls20-9607627b` at seed 0 with `deepseek-v4-flash`. Full
  game, multiple seeds, other games, and promotion remain separately authorized.

## 历史归档

Rejected or superseded paths, recorded so they are not re-walked.

- **"No detached Pi exists."** My first pass concluded this from a single `ls`
  of `./pi/` and it was **wrong**. Search `PATH` first: `/opt/homebrew/bin/pi`
  symlinks into the npm global root.
- **Reaching into `./pi/`.** Prime Agent's modified Pi, gitignored, off-limits.
- **A cross-process ARC host service.** Reachable but rewrites P7 application
  logic, which the spec forbids.
- **Sibling-relative engine/checkout paths.** The coupling the gate exists to catch.
- **Gate hardening rounds 1-5**, and **parallel subagents on "disjoint files"**
  (the gate reads the whole tree — one writer at a time).
- **Estimating timestamps instead of running `date`.** Done twice this session;
  the second time the journal drifted ~35 minutes before I measured it.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **Phases 4-9 unstarted.** P1-P6 have no native implementation. **P1-P7
  native implementations: 1 of 7** — P7 only, and only at its proven boundary.
- **Plan risk 1 is NOT cleared.** Whether P7 resolves compaction through the
  removed Prime checkout lock is a long-session property; a 4.5-minute run never
  reached compaction. Do not record it as tested, and do not restore the lock.
- **The P7/P1 coupling is resolved (2026-09-15).** The resolver was never at
  fault; the defect was `create_provider()` publishing P1 without a witness. P1
  is now unpublished and P7 supplies only its own package. 15 P1 route tests
  skip explicitly until Phase 4. See CURRENT-STATE for the measured baseline.
- **A pre-existing red test sits in the compaction family.**
  `test_python_admits_and_privately_persists_real_locked_pi_compaction`
  (`tests/test_asterion_prime_context.py`) fails on the pristine tree. Not
  investigated; it may be plan risk 1 surfacing.
- **Diagnosability gap.** A capability failure is reported as a classified
  `failure_class` only; the cause is discarded (`composed.py` re-raises
  `from None`) and not captured privately either. Locating the fixture defect
  needed a temporary probe. The redaction is correct; the private capture path is
  missing.
- **The fd-pinning (TOCTOU) property** was reported preserved but never
  independently reproduced.
- **`ASTERION_PRIME_PI_ENTRY` was not in `AGENTS.md`.** Whether the injection
  names belong in the repo instructions is undecided.

## 下一动作

1. **Settle the P7/P1 selector question** before rebuilding P1.
2. **Phase 4** — rebuild P1 (`prime.ipython-coding`) to its spec witness.

## Ready-to-paste commands

```bash
project-state resume
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"   # expect 0
uv run python -m unittest -v tests.test_prime_make_presets        # expect 2 OK
uv run python -m unittest tests.test_prime_p7_native_installed    # expect OK (was red; fixed)
git log --oneline -6
```

**The working live P7 run** (operator-authorized; provider-backed, ~5 min,
deadline cap 1 h). Both paths are load-bearing — see D-2026-09-14-03:

```bash
make asterion-prime-p7-solve \
  ASTERION_PRIME_ARC_ROOT=/Users/sujiangwen/sandbox/agentic-2026/external-prime/arc-agi-3 \
  ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js
```

Orb reaches the Mac **only** at `/mnt/mac`; the host path `/opt/homebrew/...`
does not exist inside the VM. Orb's system node is v20 and the Pi needs
`node:fs.globSync` (Node 22+), so the preset's own `node@22` resolution is
required — do not simplify it to the system node.

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`. `../external-prime/` is a
  separate external resource and not covered by that prohibition.
- **`./pi/` is gitignored and untracked** — Prime Agent's modified Pi. Do not
  add it to git or reach into it from Asterion code.
- Do not restore Prime checkout dependencies or the Prime compaction lock, and
  do not weaken the gate to silence a red.
- **On the DeepSeek backend, pass no `model` to any subagent** (see AGENTS.md).
- **Run `date` — never estimate a timestamp.** Twice violated this session.
- **Research intensity:** review changed code plus boundary assertions, run small
  targeted regressions. Do not re-run full suites or harden tooling.
- Three stale sibling worktrees exist on `codex/*` branches (`asterion-p1-workload`,
  `asterion-p2-worker`, `asterion-p3-real-rlm`, 2026-09-03). Untouched.
