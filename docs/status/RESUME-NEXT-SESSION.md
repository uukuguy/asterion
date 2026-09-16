# Live Session Checkpoint

> Updated: 2026-09-16 21:34. **Session remains active — not a final handoff.**
> Supersedes the 20:41 checkpoint. Three live runs plus upstream Pi sources
> separated "the witness fails" into three independent defects; two are fixed,
> and the third is root-caused and waiting on a decision.

## TL;DR

1. **Two of three defects are fixed.** The underscore rule (`afb2f3b1`,
   corrected at `b096e589` after a security review) and the missing
   one-cell-per-turn rule (`acc5ad1f`). Both verified by tests; the first also
   by a live run.
2. **The compact failure is root-caused, and it is not a bug in Asterion's
   compaction code.** Pi refuses to compact *before* it emits
   `session_before_compact`: the witness session is far below
   `keepRecentTokens` (20000), so `prepareCompaction` finds nothing to
   summarize and throws "Nothing to compact (session too small)". The
   extension therefore never sends the proposal frame, and the witness times
   out.
3. **The compact one needs a decision, not another patch.** P1 exists to prove
   an object survives a real compaction. A session this small never triggers
   one, so the witness cannot prove its own point as currently sized.

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
- **Root-caused — compaction, statically.** `agent-session.js:1474` documents
  `compact()` as the shared entry for `/compact`, RPC and extensions, and it
  does emit `session_before_compact` at `:1496`. So "RPC does not fire the
  hook" is **ruled out**. But `prepareCompaction` returning falsy throws at
  `:1488-1493`, before the hook. `compaction.js:537-565` returns undefined
  when there is nothing to summarize, and `findCutPoint` (`:308-333`) only
  moves the cut once the accumulated tail reaches `keepRecentTokens`
  (default 20000, `compaction.js:77`). The P1 witness session is orders of
  magnitude below that, so the kept region covers the whole session.
- **Consequence of that reading:** the extension is not at fault and is not
  unregistered. `context-witness.ts:361` sends a proposal correctly from
  `before()`, which Pi simply never calls for this session.
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

1. **Decide how the witness should reach a compactable size** — accumulate
   context, lower `keepRecentTokens` for this application, or both.
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
