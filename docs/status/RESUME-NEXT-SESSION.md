# Next-Session Handoff

> Updated: 2026-09-15 05:40, end of session. 22 commits since `c6c425f9`.

## TL;DR

1. **Phases 2 and 3 are complete.** The P7 preset is an installed-wheel
   invocation, and **native P7 was revalidated by a passing live run** driven by
   an independently installed upstream Pi — no Prime Agent anywhere in the path.
2. **The detached-Pi question is closed in the affirmative**, and the whole Orb
   wiring is now known and written down (two traps that will otherwise cost an
   hour each).
3. **Active package is Phase 4: rebuild P1's *launch path*** — P1 is not missing
   an implementation, it is missing the wiring, because `_preflight` still
   raises the Phase 1 "unavailable" stub. Phase 4 is also where plan risk 1
   (compaction) finally gets tested.

## 已验证事实

Evidence: a passing live run, commits, measured counts.

- **Live run `p7-live-20260914141314` PASSED.** Level 1 of `ls20-9607627b` in
  **20 primitive actions** and **40 IPython cells**, `partial_game_score`
  3.571429, `terminal_reason` `level-completed`, `failure: null`,
  `promotion: unpromoted`, trace sealed, replay verified, cleanup complete.
  Receipt `c00e3263cb2842dbe854cd4950ea2d2ec75859c21189f2bb101e66efed05c554`.
  Solve window 22:13:17 → 22:17:46 (~4.5 min). Private artifact at
  `.asterion-private/prime-p7-live/p7-live-20260914141314/` (0700, gitignored).
  For comparison the Prime-Agent-era run `p7-live-20260909065351` used 23
  actions and 43 cells for the same level.
- **Detachment gate 0** throughout, before and after every change.
- **A detached Pi exists and is named:** `@earendil-works/pi-coding-agent`
  (MIT, upstream, no prime-agent dependency), a *different build* from the
  `./pi/` checkout. Plan risk 2 resolved in the affirmative.
- **`make asterion-prime-p7-solve` is the working live command** (see below).
- **Prime test set: 207 tests OK, 34 skipped.** Both pre-existing failures fixed
  this session; neither was caused by this session's work.
- **P1 is unpublished** (`create_provider()` no longer lists it), matching the
  packaging index, which Phase 1 had already cleaned.

## 当前判断

Direction chosen on current evidence; not yet proven end-to-end.

- **Both Prime operators filter the global provider rather than declaring their
  own application metadata** (`p1/operator.py:238`, and P7's equivalent). That
  is why publication state reaches so far into their tests. Worth revisiting
  when Phase 4 rewires P1, but not before — it is a shape question, not a bug.
- **P1's gap is a launch path, not an implementation.** `operator`,
  `ipython_host`, `coordination`, `oracle`, `receipt`, `runtime_binding`,
  `worker`, `worker_main` all exist, as does the native substrate
  (`agents/prime/backend` with `_compact`, `context` with
  `PrimeCompactionEvidence` / `validate_compaction_witness`, `compaction_budget`,
  `session`, `store`, `state`, `trace`).

## 历史归档

Rejected or superseded paths, recorded so they are not re-walked.

- **"No detached Pi exists."** Wrong. Inferred from one `ls` of `./pi/`.
  Search `PATH` first — `/opt/homebrew/bin/pi` symlinks into the npm global root.
- **"The P7/P1 coupling is a closure-semantics problem."** Wrong. The resolver
  is correct (a published application must be executable). The defect was
  publishing P1 without a witness.
- **"Phase 2 is a conversion."** It was a rebuild: Phase 1 had already deleted
  the target and its 1006-line driver.
- **Restoring the Prime-coupled context-witness test.** Its Node harness
  resolved the off-limits checkout, verified the Prime compaction lock and
  imported Prime's compaction internals. The spec forbids tests requiring a
  Prime checkout, so the test was removed, not repaired.
- **Estimating timestamps instead of running `date`.** Done twice; the second
  time the journal drifted ~35 minutes before it was caught.
- **Spelling a forbidden path literal in an explanatory comment.** The
  detachment gate scans comments; this took the gate from 0 to 1.
- **Gate hardening rounds 1-5**, and **parallel subagents on "disjoint files"**
  (the gate reads the whole tree — one writer at a time).

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **Phases 4-9 unstarted. P1-P6 have no native implementation reachable.**
  **P1-P7 native implementations: 1 of 7** — P7 only, at its proven boundary.
- **Phase 3's completion is bounded:** Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`. Not full-game, multi-seed or
  multi-game.
- **Plan risk 1 is NOT cleared.** A 4.5-minute run never reached compaction.
  P1's witness requires compaction, so **Phase 4 is where it is actually
  tested**. Do not record it as tested, and do not restore a Prime lock.
- **15 P1 route tests skip** in `test_asterion_prime_p1_operator.py` (guards at
  the fixture and at `test_stubborn_host_owners_...`), plus retargeted
  assertions in `test_asterion_prime_p1_installed.py` and
  `test_asterion_prime_p1_provider.py`. **Phase 4 reverts all of them** in the
  same change that publishes P1 with its witness.
- **The `ASTERION_PRIME_PI_ENTRY` injection names are not in `AGENTS.md`.**
  Undecided whether they belong there.
- **Diagnosability gap:** a capability failure is reported as a classified
  `failure_class` only; the cause is discarded (`composer` re-raises `from
  None`) and is not captured privately either. Locating one fixture defect
  needed a temporary probe. The redaction is correct; the private capture path
  is missing.
- **The fd-pinning (TOCTOU) property** was reported preserved but never
  independently reproduced.
- **MOCKS/`../external-prime/`**: the ARC wheels and `environment_files/ls20/`
  were used as-is; their provenance was not audited.

## 下一动作

1. **Implement Phase 4's launch path** — `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`, section "Phase 4". Build the
   worker command, Pi command and compaction backend from Asterion-owned values,
   reusing the P7 shape (D-2026-09-14-03).
2. Then the live P1 witness run (provider-backed, needs operator authorization).
3. Then republish P1 and revert every guard listed above, in one change.

## Ready-to-paste commands

```bash
project-state resume
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"   # expect 0
uv run python -m unittest tests.test_prime_make_presets        # expect 2 OK
uv run python -m unittest tests.test_prime_p7_native_installed # expect OK
git log --oneline -6
```

**The working live P7 run** (operator-authorized; provider-backed, ~5 min,
deadline cap 1 h). Both paths are load-bearing — see D-2026-09-14-03:

```bash
make asterion-prime-p7-solve \
  ASTERION_PRIME_ARC_ROOT=/Users/sujiangwen/sandbox/agentic-2026/external-prime/arc-agi-3 \
  ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js
```

**Two Orb traps, both verified the hard way:**

- OrbStack mounts the Mac at `/mnt/mac` (and `/Users` at the same path). The
  host path `/opt/homebrew/...` **does not exist inside the VM**. Pass the
  `/mnt/mac/...` form.
- Orb's system node is **v20.19.4** and the Pi imports `node:fs.globSync`
  (Node 22+), so the preset's own `npm exec --package=node@22` resolution
  (v22.23.2) is **load-bearing — do not simplify it to the system node**.

## Workspace boundary

- Do not inspect or invoke the `3th-party` Prime Agent repo. `../external-prime/`
  is a separate external resource and not covered by that prohibition.
- **`./pi/` is gitignored and untracked** — Prime Agent's modified Pi. Do not
  add it to git or reach into it from Asterion code.
- Do not restore Prime checkout dependencies or the Prime compaction lock, and
  do not weaken the gate to silence a red.
- **On the DeepSeek backend, pass no `model` to any subagent** (see AGENTS.md).
- **Run `date` — never estimate a timestamp.**
- **Search `PATH` and the real environment before concluding a resource is
  absent.**
- **Research intensity:** review changed code plus boundary assertions, run small
  targeted regressions. Do not re-run full suites or harden tooling.
- Three stale sibling worktrees exist on `codex/*` branches
  (`asterion-p1-workload`, `asterion-p2-worker`, `asterion-p3-real-rlm`,
  2026-09-03). Untouched.
