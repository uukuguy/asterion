# Live Session Checkpoint

> Updated: 2026-09-16 21:34. **Session remains active — not a final handoff.**
> Supersedes the 20:41 checkpoint. Three live runs plus upstream Pi sources
> separated "the witness fails" into three independent defects; two are fixed,
> and the third is root-caused and waiting on a decision.

## TL;DR

1. **All seven defects are now fixed, and the last one was found by value.**
   The compaction failure was `validate_pi_compact_result` requiring exactly
   three events while Pi sends four: `PiSession.compact()` opens with
   `await this.abort()`, so `agent_settled` leads the stream. `f5a41964`
   accepts one leading settled event and validates everything else unchanged.
2. **The witness has still never passed, and it has never been run with all
   seven fixes in place.** The last run died at the terminal check, which is
   now fixed. The next run is the first real test of the whole path.
3. **Run `p1-a4c9d893d2d7998a878abf87` reached the furthest point so far** —
   setup, verify, oracle and `stage1.complete`, then a real Pi compaction.

## 已验证事实

- **Three defects, three different links.** They explain the run-to-run
  variation the previous handoff recorded: a model that writes exactly two
  cells passes the oracle and stalls at compaction; one that writes an
  exploratory cell is rejected at the oracle instead.
- **Fixed — cell naming (`afb2f3b1`, `b096e589`).** A cell may bind `_f`; the
  exemption is order- and scope-aware, so a binding that never runs (`if
  False`, an empty loop, a comprehension, a read before the binding) is still
  denied. 19 boundary probes, 25 worker tests.
- **Fixed — task statement (`acc5ad1f`).** `oracle.py:119-143` requires exactly
  two cells with two distinct request ids and turn ids. The statement said
  only "there are three independent turns". It now says "use exactly one cell
  per turn, with no exploratory cells". The oracle and the worker's four-cell
  ceiling are both unchanged; 65 tests pass.
- **Fixed — `safe_open` signature (`0911d846`).** It took `encoding` but not
  `newline`, so `open("stage-one.json", "w", encoding="utf-8", newline="")` —
  exact bytes the way the task asks for — raised `TypeError` inside the
  worker, which the bare `except BaseException` turned into `uncertain` and a
  dead run. The frame reads as an argument-binding failure, not a rejected
  cell: `audit_denials` 0, `class_name` and `callable_probe` populated,
  `file_write_calls` 0. `newline` is now accepted and validated against the
  builtin's values, and rejected in binary mode as the builtin does. Path,
  permission and encoding checks unchanged. 27 worker tests.
- **Fixed — poison granularity (`e4fbb1ea`, D-2026-09-16-03).** `_validate`
  runs before `run_code`, so a cell it refuses has executed nothing, yet a
  bare `except BaseException` merged that with a failure inside `run_code` and
  poisoned the worker either way. The frame now carries `executed`; the host
  poisons only when a cell that ran failed or was cancelled, and still for a
  frame it rejected outright. A refused cell is still denied, still
  `uncertain`, still counts its audit denial. This was the reason five
  consecutive witness runs never reached compaction.
- **Fixed — `with`-body bindings (`98937ac0`).** The scope-aware walk of
  `b096e589` made a `with` behave like an `if` and let none of its bindings
  escape, so a cell binding `_stage_one_bytes` inside the body and reading it
  after was refused before running. But a `with` body always runs — had it
  raised, the cell would have stopped there — so the risk does not exist
  there, though it does for `if`, a loop body and `try`. This cost a live run
  its verify cell. `if`/loop/`try` unchanged.
- **The poison fix is confirmed on the real path.** That same run is the first
  where a refused cell left the worker usable (`poisoned: false`), which is
  what let it continue far enough to expose the `with` defect.
- **Compaction runs; Asterion rejects its terminal.** Run `p1-a4c9d893…`
  reached `compact.admit` and Pi emitted
  `["agent_settled","compaction_start","compaction_end","response"]`. Asterion
  then raised `ValueError('Pi RPC compact terminal is invalid')`, which
  `_compact`'s `except` turned into the bottom-out receipt. **The terminal
  check is the thing to read next** — `PiRpcSession.compact` decides which
  event sequence counts as a terminal, and Pi's sequence clearly is not what
  it expects. The witness hook fired and the summarization instruction reached
  Pi, so the witness side of the protocol is working.
- **WITHDRAWN — the earlier "session too small" reading.** It said
  `prepareCompaction` would return undefined because the session sits below
  `keepRecentTokens`, so the extension hook would never fire. Pi compacted,
  so that is disproven, and the decision to lower `keepRecentTokens` must not
  be implemented. The reasoning was static only; no value was ever captured
  for it, and it was reported as "root-caused" too early.
- **Every live run this session had cells complete cleanly once the naming fix
  landed** — three `ok`, unpoisoned, `audit_denials: 0` in the last one. The
  worker is not the problem in any current failure.
- **The SIGTERM question stays closed:** nothing kills the worker from
  outside; a cell that is not `completed` poisons it and the close path
  SIGTERMs its own process group.

## 当前判断

- **The compact defect is a witness-sizing problem, not a wiring problem.**
  The extension, the hook, the RPC path and the witness protocol all behave as
  designed; the session is simply too small for Pi to consider compaction.
- **Candidate directions, none chosen:** make the witness accumulate enough
  context to cross `keepRecentTokens` before asking to compact; configure a
  smaller `keepRecentTokens` for this application; or have `_compact` await
  the RPC result and the witness concurrently so Pi's own failure surfaces
  instead of a timeout. The third is worth doing regardless — right now Pi's
  reason is discarded and only a timeout is visible.
- **D-2026-09-16-01 remains the right shape for summarization ownership**, but
  it cannot be exercised until compaction actually happens.

## 历史归档

- **"The extension never sends a proposal."** Wrong: it does, from Pi's hook.
- **"Asterion's `session.compact` RPC does not fire the hook."** Wrong:
  `compact()` is the shared entry point and emits it.
- **"Something external kills the worker."** Wrong: the worker closes itself.
- **"Capture worker stderr."** Both runs returned `b''`; read the frame.
- **"Rejecting underscore identifiers is fine, the model will comply."** No —
  nothing constrains how the model names locals.
- **"The oracle is stricter than the task."** No: its shape carries stage
  one's meaning. The statement was incomplete.
- Carried over: rebuilding the Prime compaction dependency against another
  source; letting the extension import Pi's compaction internals; treating
  `customInstructions` as sufficient; asking upstream for
  `replaceInstructions`; two Pi instances for independence.

## 未完成边界

- **The P1 witness has NOT passed. P1 stays unpublished.**
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7.**
- **The one-cell-per-turn fix has not been re-run against the live witness**,
  and neither fix has been exercised together with a session that reaches
  compaction.
- **Pi's own error text has not been observed at run time.** The
  `PiRpcSession.compact` hook is installed but has not yet fired. The reading
  above is from upstream source, which is strong but is not a captured value.
- `validate_compaction_witness` still requires `entry.get("fromHook") is not
  False`; relax only as part of D-2026-09-16-01.
- Known-unverified carry-overs: `test/context-witness.test.mjs` cannot run;
  `tests/test_core_only_install.py` was already red at HEAD.
- `.asterion-private/p1-diagnose.py`, `p1-probe.sh` and `p1-validate-check.py`
  are temporary diagnostics. Delete them when the diagnosis is done.
- Phase 3's completion stays bounded to Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`.
- The `climb/` loop is dormant and its `next_action` is stale.

## 下一动作

1. **Re-run the live witness.** All seven fixes are in the tree, and it has
   never been run with all of them present. That run is the first one that can
   exercise the whole path: cells, oracle, Pi's compaction, Asterion's
   terminal check, and then the witness's own compaction validation.
2. **Independently, make `_compact` await the RPC result and the witness
   proposal concurrently**, so Pi's own failure surfaces instead of a bare
   timeout. This is a diagnosability fix worth having either way.
3. Then implement D-2026-09-16-01 on a compaction that actually happens.
4. Re-run the witness only after that — it is model-driven and costs a
   provider call per run.

## Ready-to-paste commands

```bash
# Probe run (Orb, real path, probe entry instead of the operator module):
sh .asterion-private/p1-probe.sh

# Zero-cost boundary check (both sides of the underscore rule):
uv run python .asterion-private/p1-validate-check.py

# Prime P1 tests, including the underscore and oracle boundaries:
uv run python -m unittest -v tests.test_asterion_prime_p1_worker

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
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
