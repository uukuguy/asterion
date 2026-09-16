# Live Session Checkpoint

> Updated: 2026-09-16 20:41. **Session remains active — not a final handoff.**
> Supersedes the 19:46 checkpoint. This session captured the worker evidence
> the last handoff asked for, root-caused both failures it found, and fixed
> one of them.

## TL;DR

1. **The underscore defect is fixed, committed and verified.** A P1 cell may
   now name its own locals `_f`; that was killing whole runs on otherwise
   correct cells. `afb2f3b1`, then corrected at `b096e589` after an automated
   security review found the first exemption was tree-wide rather than
   order- and scope-aware.
2. **The compact failure is located to one exact link.** `_compact` waits for
   a proposal frame from the Pi extension and times out, because the extension
   only sends one when Pi fires `session_before_compact` — and it never fired.
3. **Why Pi never fired it is the next question**, and it is the substance of
   D-2026-09-16-01. Nothing else in the compact path needs investigation
   first.

## 已验证事实

- **Commit `afb2f3b1`** narrows the cell validator. `_bound_names` collects
  what the cell binds (assignment and loop targets, `with ... as`, parameters,
  comprehension targets, `except ... as`). The `ast.Name` rule is now three
  parts: `forbidden_names` unchanged; `__`-prefixed denied in every position,
  bound or not; single-underscore denied only when the cell never binds it.
  The `.attr` underscore rule and the underscore function-name rule are
  untouched.
- **Commit `b096e589` corrects that exemption.** The first version collected
  binding targets tree-wide, so a name was admitted whenever it appeared as a
  target *somewhere*, even when the read came first or the binding sat in an
  `if False`, an empty loop or a comprehension — each leaving the read to fall
  through to the IPython namespace, which is what the rule exists to stop. An
  automated security review of `afb2f3b1` flagged it; all four shapes were
  reproduced before anything changed. Admission now requires the binding to
  provably precede the read in the read's own scope, and no binding escapes an
  `if`, a `try`, a loop body or a comprehension. The walk is conservative in
  the fail-closed direction.
- **Verified:** 25 P1 worker tests pass, including every fail-closed security
  test (`test_forbidden_cells_fail_closed_and_poison`,
  `test_format_string_cannot_traverse_private_attributes`,
  `test_pattern_matching_cannot_extract_worker_closures`); a 19-case boundary
  check passes (6 admitted, 13 denied); detachment gate 0; 30
  operator/installed/provider tests pass; ruff clean.
- **Why the defect survived every test:** the existing test cells name their
  locals `stream`, `accumulator`, `verified_bytes` — none with a leading
  underscore. The new tests add a positive case and a six-entry security
  regression matrix.
- **Live probe run `p1-cc5967b5103764bfbab82322`:** both cells complete,
  `audit_denials: 0`, `WORKER CLOSE {poisoned: false, closed: false,
  cells_recorded: 2}`. The fix works on the real path.
- **The compact cause, read out for the first time** by the `_receipt` hook
  reading `sys.exc_info()` inside the swallowing `except` block:
  `_compact` (`backend.py:990`) → `witness.receive_proposal_and_decide`
  (`context.py:734`) → `_receive()` waits for a proposal frame on the private
  socket → `asyncio.wait_for` times out (its `__context__` is `TimeoutError`,
  the socket recv having been cancelled) → `_fail()` (`context.py:93`) raises
  `PrimeContextError: invalid Prime context witness` → swallowed into the
  bottom-out receipt.
- **The extension does send proposals.** `context-witness.ts:361` writes one,
  but only from `before()`, which is registered on Pi's
  `session_before_compact` (`:423`) and returns early unless
  `event.type === "session_before_compact"` (`:336`). The timeout therefore
  means that hook did not fire.
- **The SIGTERM question from the previous handoff is closed.** Nothing kills
  the worker from outside: a cell that is not `completed` poisons it, and the
  close path SIGTERMs its own process group.

## 当前判断

- **Two independent defects were blocking the witness; one is now cleared.**
  A green run still requires the compact path to work, so the witness stays
  unproven either way.
- **The compact failure is a wiring question, not a summarization-quality
  question.** The frame never arrives, so nothing about summary content has
  been exercised yet.
- **The two candidate explanations are distinguishable and cheap to test:**
  either Asterion's own `session.compact` RPC does not make Pi fire
  `session_before_compact`, or the extension's witness was never selected in
  this run. Extension-side evidence decides it.
- **This is the substance of D-2026-09-16-01**, which is decided but not
  implemented.

## 历史归档

- **"Rejecting underscore identifiers is fine, the model will comply."** No —
  nothing constrains how the model names locals, and one such name killed a
  whole run.
- **"Capture worker stderr to explain a failure."** Both runs returned `b''`;
  cell output is redirected into an in-process buffer and discarded on
  failure. Read the frame instead.
- **"Something external is killing the worker."** Superseded: the worker
  closes itself.
- Carried over: rebuilding the Prime compaction dependency against another
  source; letting the extension import Pi's compaction internals; treating
  `customInstructions` as sufficient; asking upstream for
  `replaceInstructions`; two Pi instances for independence.

## 未完成边界

- **The P1 witness has NOT passed. P1 stays unpublished.**
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7.**
- **Run-to-run variation is real.** Earlier runs died at `stage1.oracle.start`
  or on the second turn; a single green run would not prove those gone.
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

1. **Find out why Pi did not fire `session_before_compact`.** Get
   extension-side evidence: the extension's own stderr/stdout is not
   currently collected by the probe, and that is where the answer is.
   Distinguish "Asterion's `session.compact` RPC does not trigger the hook"
   from "the witness was never selected in this run".
2. Then implement D-2026-09-16-01 on whatever that shows.
3. Re-run the witness only after both are addressed — it is model-driven and
   costs a provider call per run.

## Ready-to-paste commands

```bash
# Probe run (Orb, real path, probe entry instead of the operator module):
sh .asterion-private/p1-probe.sh

# Zero-cost validator boundary check (both sides):
uv run python .asterion-private/p1-validate-check.py

# The worker contract, including the new underscore tests:
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
