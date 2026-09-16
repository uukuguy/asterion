# Next-Session Handoff

> Updated: 2026-09-16 19:04, end of session. This session's commits are
> `git log 1d21ef05..HEAD` — nine commits from `fd962a66` through the docs
> closeout. They are stated as a range on purpose: state-only bookkeeping lands
> after this file, so a hard-coded count would go stale on commit.

## TL;DR

1. **Phase 4's P1 launch path is rebuilt, committed and green.** P1 no longer
   resolves itself out of the published provider, so it composes while
   unpublished; the 34 tests that skipped because of that coupling now run.
2. **The live witness now completes stage one end to end** — setup, verify,
   oracle and `stage1.complete` — and reaches `compact.admit`. It does not pass.
3. **The remaining failures track the model's output, not one broken link.**
   Failure points differ run to run, and one run reached compaction. The next
   step is to capture worker-side stderr and cell logs, not to keep patching.

## 已验证事实

Evidence: commits, passing commands, live-run stage traces, measured values.

- **Commits this session** (`git log --oneline fd962a66^..HEAD`):
  - `fd962a66` delete the pinned Pi dependency channel (−686 lines) — this was a
    runtime import of Prime Agent's modified Pi wearing the name "dependency
    injection"
  - `c21d0dae` Asterion's own compaction summarization module
  - `f1b08c1f` rebuild the native P1 launch path; decouple P1 from the published
    provider; carry the summarization instruction into Pi's compaction
  - `774ae137`, `540283b8`, `2ae1c652`, `74a092b5` docs and the `agent_settled` fix
- **Detachment gate 0** throughout; targeted set **162 passed**; lint unchanged
  at its 4 pre-existing findings; working tree clean.
- **P1's provider coupling is gone.** `provider.py` exposes
  `prime_ipython_coding_application()` and `create_prime_ipython_coding_provider()`;
  the operator composes from those. The public list is unchanged (P7 only). The
  P1 set went from 38 passed / 34 skipped to **83 passed / 0 skipped**.
- **Two real defects were found and fixed:**
  - The Pi child refused the extension because the context witness needed
    compaction internals that exist only in Prime Agent's Pi build. Upstream
    never published that version (`npm view` shows no 0.7.x; earliest is 0.74.0),
    so the locked tree was Prime's own build.
  - `26519254` swapped the round terminal from `agent_settled` to `agent_end`
    and dropped `agent_settled` from the accepted vocabulary entirely. Pi emits
    `agent_end` then `agent_settled`; the round driver stops at its terminal, so
    the trailing event lands on the *next* round. Single-round P7 never sees it.
- **Live-run progression** (model-driven, so the stopping point varies):
  - `p1-debe34e5…` died at the first turn (extension refused to load)
  - `p1-bb85dc5e…` first turn passed, died on the second (`agent_settled`)
  - `p1-f6f4d6e4…` **stage one complete**, died at `compact.admit`
  - `p1-e1101d8f…` died at `stage1.oracle.start`
- **Worker-lifecycle readings** from one run:
  `{"closed": true, "poisoned": true, "stdout_gone": true, "returncode": -15,
  "root_fd_is_none": true, "seconds_to_deadline": 590.3}` — the worker was
  SIGTERMed with 590 s of deadline left, and `_close()` had already run.

## 当前判断

Direction chosen on current evidence; not yet proven end-to-end.

- **The remaining failures are the application not yet working reliably, not an
  unfixed link.** Failure points differ per run and one run reached compaction,
  which is what a model-driven system looks like when the machinery is intact
  but the model does not always produce what the oracle requires.
- **The worker is being closed or terminated mid-run**, but **who triggers it is
  not known.** `P1WorkerProcess._signal_owned_process(process, signal.SIGTERM)`
  (`ipython_host.py:650`) is the only place that sends SIGTERM. The unverified
  hypothesis is that a first-turn cell ends the worker, closing its stdout and
  making the host poison and reap it — this needs worker stderr and cell logs to
  settle, which the current probe does not collect.
- **D-2026-09-16-01 is decided but not implemented.** Asterion should own
  compaction summarization through Pi's `session_before_compact` takeover using
  `ctx.modelRegistry.runtime.complete()`. What is in the tree now is the interim
  `customInstructions` append, which reaches the model only on compaction
  Asterion drives itself. This is a prerequisite for P1's kernel-persistence
  property actually holding.
- **Plan risk 1 is being exercised for the first time** and nothing about it is
  proven.

## 历史归档

Rejected or superseded paths, recorded so they are not re-walked.

- **"Rebuild the Prime compaction dependency against a different source."** Wrong.
  The mechanism was itself the illegitimate import. Deleting it was correct.
- **"Let the extension import Pi's compaction internals."** Dead: upstream Pi
  does not export three of the seven names the witness required.
- **"Append the kernel note via `customInstructions` and be done."** Only covers
  compaction Asterion drives; automatic threshold and overflow compaction pass no
  instructions, and upstream's wrapper is a one-line `Additional focus: X`.
- **"Ask upstream for `replaceInstructions` on the compaction path."** No
  published version has it (latest 0.85.1); it exists only on the tree/branch
  summarization path. Prime had it only because it owned a forked Pi.
- **"Two Pi instances restore independence."** No: both are Pi, and verifying one
  summary with another is not verification — summaries have no unique answer.
- **Estimating timestamps instead of running `date`.** Avoided this session.
- **Reading a failure classification as the cause.** Every real cause this
  session came from values: `__context__` behind `from None`, or instrumenting
  the check that swallowed its own reason.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **The P1 witness has NOT passed. P1 stays unpublished.** Do not publish it
  without a passing witness — that was the 2026-09-15 defect.
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7** — P7
  only, at its proven boundary.
- **`validate_compaction_witness` still requires `entry.get("fromHook") is not
  False`.** It must be relaxed only as part of D-2026-09-16-01, not before.
- **Unverified from the subagent's work:** `test/context-witness.test.mjs` cannot
  run (its harness was deleted with the Prime Gateway surface in `019e2c48`, and
  the tests imported Prime's Pi internals directly); `tests/test_core_only_install.py`
  was already red at HEAD for two pre-existing module-allowlist entries.
- **`.asterion-private/p1-diagnose.py`** is a temporary diagnostic probe
  (gitignored). It is working and worth keeping for the next session; delete it
  when the diagnosis is done.
- **Phase 3's completion stays bounded** to Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`.
- **The `climb/` verification loop is dormant and its state is stale.**
  `climb/research-tree.md` ends at "Next: Phase 3.2" and
  `climb/session-state.json` still says
  `next_action: phase-3.2-native-small-verification-sidecar`, both last written
  2026-09-01. The project has since moved to the Phase 4 native-detachment
  program. This is a paused parallel loop, not a contradiction — do not read its
  `next_action` as the project's next action.

## 下一动作

1. **Capture worker-side evidence before changing anything.** Extend
   `.asterion-private/p1-diagnose.py` to collect the worker's stderr and the
   per-cell log so the SIGTERM question is answered with values, not inference.
   Start from `P1WorkerProcess._signal_owned_process` (`ipython_host.py:626-660`)
   and its callers.
2. Then decide whether the remaining failures are the task statement / prompt not
   eliciting the cells the oracle requires, or the oracle being stricter than the
   task. Those are different fixes.
3. Implement D-2026-09-16-01 once the witness is stable — it is what makes P1's
   kernel-persistence property real.

## Ready-to-paste commands

```bash
# The live witness (operator-authorized; provider-backed; ~2 min per run):
make asterion-prime-p1-run \
  ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"

# The targeted set used this session (expect all passed):
uv run python -m unittest tests.test_asterion_prime_summarization \
  tests.test_asterion_prime_context tests.test_asterion_prime_backend \
  tests.test_asterion_prime_backend_rpc tests.test_asterion_prime_p1_operator \
  tests.test_pi_runtime_extensions tests.test_asterion_prime_session \
  tests.test_pi_rpc_reusable
```

**Two Orb traps, both verified the hard way:** OrbStack mounts the Mac at
`/mnt/mac` (the host path `/opt/homebrew/...` does not exist inside the VM), and
Orb's system node is v20 while the Pi needs Node 22 — the preset's own
`npm exec --package=node@22` is load-bearing and must not be simplified.

## Workspace boundary

- **Asterion prime must never import or depend on Prime Agent.** Reading
  `3th-party/prime-agent.git` read-only to extract a design principle is the
  authorised exception (given 2026-09-16); every shipped line must be Asterion's
  own. The detachment gate must stay 0, and it scans comments.
- Do not restore Prime launch, Prime locks, or Prime compaction imports.
- **On the DeepSeek backend, pass no `model` to any subagent** (see AGENTS.md).
- **Run `date` — never estimate a timestamp.**
- **Search `PATH` and the real environment before concluding a resource is absent.**
- **Research intensity:** review changed code plus boundary assertions, run small
  targeted regressions. Do not re-run full suites or harden tooling.
