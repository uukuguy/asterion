# Live Session Checkpoint

> Updated: 2026-09-17 19:40. **Session remains active — not a final handoff.**
> Supersedes the 18:58 checkpoint in this same session: the stage-two gates were
> the remaining blocker, they are fixed, and P1 now reaches its end.
> Commits this session: `git log d1535168..HEAD` (stated as a range on purpose).

## TL;DR

1. **P1 now runs to the end of the task.** Both post-fix runs recorded three
   cells (the continuation cell never ran before), stage two was released, and
   the third cell passed its own checks. One of the two runs returned
   `status=completed` with a sealed receipt.
2. **Seven defects were fixed** (`206d1d50`, `0a97e9cd`, `a578183b`, `97c309e4`,
   `67978fe4`, `0672e420`). Four were one shape: a contract or fixture narrower
   than what Pi actually sends, or a byte-shrink claim the metric cannot
   support. The byte-shrink clause sat at **three** enforcement points.
3. **P1 is not yet a pass.** The second run completed every stage, including
   `stage2.complete`, and still returned `recovery-required` with no receipt.
   The residual failure is in finalization, it is intermittent (1 of 2), and its
   cause is discarded by a bare `except BaseException`.

## 已验证事实

Each item is supported by a commit, a captured value, or a passing command.

- **The persisted frame was never written (`206d1d50`).** Pi's compaction entry
  carries `usage.cost` as floats; `canonicalJson` is `canonical(value, false)`
  and rejects any non-safe-integer, so `digest(entry)` and `#channel.write` both
  threw. The host's accepted entry keys independently exclude `usage`. The wire
  now carries the contract fields; the digest covers what was sent.
- **Stack frames carry no line number.** esbuild emits the bundle as one line
  (44618 chars), so every frame reports line 1; only the column distinguishes a
  `fail()` site. The columns resolved to `invalid()` ← `canonical`'s number
  branch.
- **`customInstructions` is not a compaction-entry field (`0a97e9cd`).** Both of
  Pi's construction sites omit it; Pi carries custom instructions on the
  `before_compaction` hook event. Measured: `pd-check tokens=2723 declared=2723
  cust=undefined`. The host compared an absent field against a declared value,
  so it could only pass while that value was null — the fixture's only case.
- **The compact response contract was unreachable (`a578183b`).**
  `_compact_rpc_event` projects a response to `{type,id,success}` first.
  Authority: `docs/superpowers/specs/2026-09-10-asterion-prime-native-p1-shared-kernel-design.md:206`
  — "`PiRpcConfig.compact_events` is transport event redaction". The reducer
  `063b6cc9` (09-09) predates the validator `8f8c6709` (09-10).
- **The compact result is exactly six keys (`67978fe4`).** Verified in Pi's
  installed bundle at both terminals: `{summary, firstKeptEntryId, tokensBefore,
  estimatedTokensAfter, usage, details}`. The validator allowed four.
- **The byte shrink clause sat at three enforcement points (`97c309e4`,
  `0672e420`), and D-2026-09-17-04 removed it from all three.** The witness, then
  `P1WorkerCheckpoint.__post_init__` and `P1StageTwoRelease` — the gate that
  authorizes stage two. All compare canonical-JSON byte counts, so all refused
  legitimate compactions. Measured refusals: `7608 → 8657` at the checkpoint
  (stopped the run; the stage-two milestone never arrived), and the witness's
  five points (closest `9952 → 9929`, 23 bytes). Counts stay required and are
  still carried as evidence; only the comparison is gone.
- **P1 reaches the end of the task in both post-fix runs.** Run 1:
  `status=completed`, `receipt_sha256=928fb8d3b37172bde24b5f1c49836952cd39c08f374cb15aad4eb9ec3f8445dd`,
  three cells, compaction `9848 → 9235`. Run 2: stages
  `stage2.release → stage2.complete → host2.close → worker.close → backend.close
  → runner.terminal`, three cells, third cell output `setup_value_loaded: 40 /
  final_result: 98 / bytes_unchanged: True`, compaction `8260 → 8596` (grew —
  direct evidence the old gates had to go) — but `status=recovery-required`,
  `receipt_sha256=None`.
- **The localization technique that worked, twice:** instrument the handler that
  classifies and discards, never the code under suspicion. A mark on the ipython
  bridge handler produced a **true negative** (that handler was not involved),
  which refuted the first attribution; a mark on `operator.py:768` produced
  `AST-O run-exc P1WorkerError: P1 worker checkpoint rejected` with the exact
  stack `resume → P1WorkerCheckpoint → worker.py:176`.
- **Verification commands run at their boundaries:** `test_asterion_prime_context`
  25, `test_asterion_prime_backend` 43, `test_asterion_prime_p1_operator` 26,
  plus `p1_worker`/`p1_runtime`/`p1_oracle` — 124 pass across the affected set;
  TS extension 16 with 15 pass; detachment gate **0**.
- **Two pre-existing failures were confirmed by reverting to HEAD source, not by
  inference.** `test/ipython-extension.test.mjs`'s "the arm frame's native
  material drives the request the witness proposes" fails identically on
  unmodified HEAD. `tests.test_pi_session` is red at HEAD with **1 failure + 6
  errors**; it is **not** in the previous carry-over list.

## 当前判断

Chosen on current evidence; not proven end to end.

- **The residual failure is in finalization, not in the task.** Run 2 completed
  every stage marker through `runner.terminal`, and the third cell's own
  receipt shows its checks passed, yet no receipt was sealed. Compare run 1,
  which sealed one. So the operator's receipt path is the intermittent part.
- **Do not call P1 passed.** One run returned `completed`; the next ran the same
  distance and returned `recovery-required` with no receipt. `promotion` stays
  `unpromoted`, and this is one game, seed 0, `deepseek-v4-flash`, Level 1.
- **Two of this session's defects were refuted attributions**, both caught by
  measuring before changing: the bridge handler (true negative) and "removing
  the diagnostics caused the regression" (the guard was refusing). On this path,
  the first plausible cause has been wrong every single time.
- **The overall shape is unchanged:** mostly a narrower environment refusing
  ordinary correct work, plus contract mismatches with Pi. Each instance has
  been cheap to fix once measured.

## 历史归档

Rejected or superseded, recorded so they are not re-walked.

- Carried over, still rejected: the "session too small" reading (Pi compacts);
  "Pi never read the settings" (disproved); "the channel socket close causes the
  cancel" (it is teardown); "the extension's 5 s channel timeout fired" (no
  `bounded-timeout` mark ever); "fabricate a retained count to keep the host
  bound strict"; "the 4096 request bound is the whole story"; "capture worker
  stderr"; rebuilding the Prime compaction dependency; letting the extension
  import Pi's compaction internals; `customInstructions` as sufficient; asking
  upstream for `replaceInstructions`; two Pi instances for independence.
- **"The ipython bridge's bare `except Exception` caused the stop."** Refuted by
  a mark that never fired; the stop came from `operator.py:768` classifying a
  `P1WorkerError`.
- **"The failure behind the guard is unmeasurable"** and **"removing the
  diagnostics caused the regression."** Both withdrawn by measurement.
- **"The validator's `command`/`data` requirement is the live contract"** and
  **"the compact result is four keys."** Both rejected: the fixtures modelled
  shapes production never sends.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **P1 is NOT passed.** One `completed` run of two; the second completed every
  stage and returned no receipt.
- **The finalization failure is unexplained and intermittent.** One occurrence
  beyond run 1's success; the cause is discarded by `operator.py:768`'s
  `except BaseException`.
- **The run's private receipt artifact location is not pinned down.** It lands
  in the operator's own per-run temp root inside Orb; `/tmp/piagent-probe` holds
  only `settings.json`. Do not assume it is on the host.
- **`compaction_budget` still under-reserves.** `reserveTokens` is 16384, so Pi
  may generate up to 13107 output tokens per branch, while the reservation
  assumes 3276 and `_RESERVED_TOKENS_MAX` is 16000. Left deliberately
  under-reserved rather than silently widened.
- **The extension test fake still lies.** `test/ipython-extension.test.mjs`'s
  `buildSessionContext` returns `{role, retainedMessageCount}` — the exact shape
  Pi never produces. Not done.
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7** — P7 at
  its proven boundary, P1 short of a repeatable pass.
- `validate_compaction_witness` still requires `entry.get("fromHook") is not
  False`; relax only as part of D-2026-09-16-01.
- Known-unverified carry-overs: `test/context-witness.test.mjs` cannot run;
  `tests/test_core_only_install.py` was already red at HEAD;
  `tests.test_asterion_prime_pi_contract` does not exist (a stale `.pyc`
  suggested it did); `tests.test_pi_session` is red at HEAD (1F+6E).
- `.asterion-private/p1-diagnose.py`, `p1-probe.sh` and `p1-validate-check.py`
  are temporary diagnostics. Delete them when the diagnosis is done. The probe
  script carries host-side decide/quote instrumentation.
- Phase 3's completion stays bounded to Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`.
- The `climb/` loop is dormant and its `next_action` is stale.

## 下一动作

1. **Recover the finalization failure.** Instrument the receipt path the same
   way `operator.py:768` was instrumented — mark the handler that classifies,
   run again, read the value. Do **not** change the receipt code first.
2. **Repeat the probe until the outcome is stable** across at least three runs
   before treating the P1 witness as passed. Two runs have already disagreed.
3. **Reconcile `compaction_budget` with the new output ceiling** (see 未完成边界).
4. **Make the extension test fake match Pi** — drop `retainedMessageCount`.

## Ready-to-paste commands

```bash
# Probe run (Orb, real path, probe entry instead of the operator module):
sh .asterion-private/p1-probe.sh

# Zero-cost boundary check (both sides of the underscore rule):
uv run python .asterion-private/p1-validate-check.py

# Targeted regressions for the changed surfaces:
uv run python -m unittest tests.test_asterion_prime_context
uv run python -m unittest tests.test_asterion_prime_backend
uv run python -m unittest tests.test_asterion_prime_p1_operator
uv run python -m unittest tests.test_asterion_prime_p1_worker tests.test_asterion_prime_p1_runtime
(cd packages/typescript/asterion-prime-extension && npm run build && \
  node --test test/ipython-extension.test.mjs)

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

**Reading a run.** The operator prints `{"stage":"..."}` with no space after the
colon (compact separators), so grep for `{"stage":"` — a spaced pattern matches
nothing and looks like an empty run. `STAGES:` in order plus `WORKER CLOSE`'s
`cells_recorded` tells you how far it got: 2 cells means the continuation never
ran, 3 means stage two was released.

**Instrument the classifying handler, not the suspect.** `operator.py:768`'s
`except BaseException` turns anything into a classification, so it is where the
cause is lost — the same for the extension's `catch`. A mark on the wrong
handler yields a true negative that looks like progress; expect and use those.

**Keep extension stderr small.** Unfiltered stacks exceed Pi's stderr cap and
truncate the event stream (observed). One short line per mark.

**Stack frames carry no line number.** esbuild emits the extension bundle as one
line; read the **column**, and skip the first two frames (`unavailable`, `fail`),
which are constant for every call site.

**Rebuilding the extension:** `uv build --wheel` recompiles it through
`hatch_build.py`, so the probe picks the change up; a bare `npm --prefix
packages/typescript/asterion-prime-extension run build` only refreshes `dist/`.
`npm run build` runs `tsc` first and will fail the wheel build if the TS does
not typecheck.

**Two Orb traps, both verified the hard way:** OrbStack mounts the Mac at
`/mnt/mac` (the host path `/opt/homebrew/...` does not exist inside the VM), and
Orb's system node is v20 while the Pi needs Node 22 — the preset's own
`npm exec --package=node@22` is load-bearing and must not be simplified.

**Take contract key sets from Pi's own source.** The installed bundle at
`/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/chunks/`
is the authority; three of this session's defects came from trusting a fixture
over it.

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
