# Next-Session Handoff

> Updated: 2026-09-17 12:15, end of session. This session's commits are
> `git log 1d21ef05..HEAD` — 31 of them, from the loader change through the
> probe forensics. Stated as a range on purpose: state-only bookkeeping lands
> after this file, so a hard-coded count would go stale on commit.

## TL;DR

1. **Seven defects that blocked the P1 witness are fixed and committed.** Each
   was found by a live run and confirmed by value, not by reading code. Stage
   one now passes end to end and Pi performs a real compaction.
2. **An eighth was root-caused part of the way and deliberately left open.**
   The extension cancels compaction because Asterion's private channel socket
   closes under it. **Whether that close is the cause or the consequence of
   the witness's own 60 s timeout is NOT established** — the teardown path
   closes the witness too, so both readings fit the evidence. Treat the chain
   as unclosed.
3. **The next step is one timestamped measurement**, not more reading: record
   when the extension rejects and when the witness's 60 s expires, and see
   which came first. That decides which side to investigate.

## 已验证事实

Evidence: live probe runs, RPC event values, captured frame fields, passing
tests. Each carries its commit.

- **Cell naming (`afb2f3b1`, corrected at `b096e589`).** A cell may bind `_f`.
  The exemption is order- and scope-aware; a binding inside an `if`, a loop
  body or a comprehension does not count outside it.
- **`safe_open` signature (`0911d846`).** It took `encoding` but not `newline`,
  so `open(..., encoding="utf-8", newline="")` — the exact-bytes form the task
  asks for — raised `TypeError` inside the worker.
- **Poison granularity (`e4fbb1ea`, D-2026-09-16-03).** `_validate` runs before
  `run_code`, so a refused cell has run nothing; the frame now carries
  `executed` and only a cell that ran poisons the worker. This is what let a
  later run survive a refused cell and expose the next defect.
- **`with`-body bindings (`98937ac0`).** A `with` body always runs, so its
  bindings count afterwards.
- **Reserved names (`7c04f57b`).** `_`, `_i`, `_ii`, `_iii`, `_ih`, `_oh`,
  `_dh`, `_exit_code` and `_i1`..`_iN` are denied outright, bound or not —
  which is what makes the `with` rule sound rather than fail-open. Cost:
  `for _i in range(n)` is now refused.
- **Task statement (`acc5ad1f`, `2998ee78`).** It states the one-cell-per-turn
  rule the oracle already enforced, and that the allowed modules must each be
  imported.
- **Compact terminal (`f5a41964`).** `validate_pi_compact_result` required
  exactly three events; Pi sends four, because `PiSession.compact()` opens with
  `await this.abort()` and so settles the agent first. One leading
  `agent_settled` is now accepted; everything else is unchanged.
- **Two security-review findings were real and are fixed** (`b096e589`,
  `7c04f57b`). The first underscore exemption was tree-wide, admitting four
  shapes whose binding never runs; the first `with` rule was fail-open because
  `__exit__` can suppress an exception.
- **The extension's failure is visible now.** Temporarily giving
  `context-witness.ts`'s bare `catch {` a binding shows
  `ASTERION-WITNESS-FAIL Error: Asterion context witness is unavailable`, with
  no frame of the extension's own in the stack — only
  `processTicksAndRejections → ExtensionRunner.emit → AgentSession.compact`.
- **Everything else in the chain is measured:** Pi emits
  `["agent_settled","compaction_start","compaction_end","response"]`;
  `compaction_end` carries `aborted: True`; the native witness receives no
  frame at all (`TimeoutError`, `wait_seconds: 60`).
- **Pi resolves the settings path correctly** (verified in Orb by importing
  Pi's own `config.js`): `PI_CODING_AGENT_DIR` → `getAgentDir()` →
  `getSettingsPath()`, file present. So the "Pi never read the settings"
  theory is **disproved**, and the extension's hard `SETTINGS` check against
  `{enabled: false, reserveTokens: 4096, keepRecentTokens: 256}` — which
  `_AGENT_SETTINGS` already matches exactly — is **not** the failure.

## 当前判断

Chosen on current evidence; not proven.

- **The socket close is the pivot and its direction is unknown.** `close()` →
  `_close_transport()` → `socket.close()` is the only path that rejects the
  extension. Its only caller is teardown (`operator.py:679-680`, and
  `backend.close()` closes the witness by design). If teardown runs *after*
  the 60 s witness timeout, the close is a consequence and the real question
  returns to "why the extension never sends a proposal". Both readings fit
  everything measured so far.
- **Do not build on the "session too small" reading** — withdrawn, see below.
- **The overall shape is now clear**: the failures were mostly a model writing
  ordinary, correct Python that a narrower environment refused, plus one
  contract mismatch about Pi's event stream. That class looks exhausted; what
  remains is the channel/timing question.

## 历史归档

Rejected or superseded paths, recorded so they are not re-walked.

- **"The witness session is too small, so `prepareCompaction` returns
  undefined."** WITHDRAWN. Pi compacts; there is no "Nothing to compact". It
  was static-only reasoning reported as root-caused before any value was
  captured, and a decision (`keepRecentTokens`) was taken on it. It must not
  be implemented for that reason.
- **"Pi never read the Asterion settings, so the extension's SETTINGS check
  fails."** Disproved by measurement (see above).
- **"The extension fails a check inside `before()`."** Not established — the
  stack has no extension frame, which points at a rejected promise (the
  channel), not a check.
- **"Asterion's `session.compact` RPC does not fire the hook."** Wrong:
  `compact()` is the shared entry and emits it.
- **"Something outside kills the worker."** Wrong: a failed cell poisons it and
  the close path SIGTERMs its own group.
- **"Capture worker stderr."** Both runs returned `b''`; read the frame.
- Carried over: rebuilding the Prime compaction dependency against another
  source; letting the extension import Pi's compaction internals; treating
  `customInstructions` as sufficient; asking upstream for
  `replaceInstructions`; two Pi instances for independence.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **The P1 witness has NOT passed. P1 stays unpublished.** Seven defects fixed
  is not a passing witness, and the witness has still never run with all seven
  in place and reached its own validation.
- **The channel chain is NOT closed.** One link is a hypothesis in both
  directions.
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7.**
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

1. **Measure the order, do not read for it.** Timestamp the extension's
   rejection and the witness's 60 s expiry in one run. If the extension
   rejects first, the channel close is a cause and belongs to Asterion's
   teardown or transport; if it rejects after, the cause is upstream and the
   question is why no proposal frame is ever written.
2. **To see the extension's reason again**, temporarily bind the `catch` in
   `context-witness.ts` and print the stack with `data:text/javascript` frames
   filtered — unfiltered output exceeds Pi's stderr cap and truncates the
   event stream instead (observed). Restore the bare catch afterwards; it is
   currently restored.
3. Then re-run the witness with all seven fixes and this one.

## Ready-to-paste commands

```bash
# Probe run (Orb, real path, probe entry instead of the operator module):
sh .asterion-private/p1-probe.sh

# Zero-cost boundary check (both sides of the underscore rule):
uv run python .asterion-private/p1-validate-check.py

# Prime P1 tests, including the underscore, open and oracle boundaries:
uv run python -m unittest -v tests.test_asterion_prime_p1_worker

# The compact terminal contract:
uv run python -m unittest tests.test_asterion_prime_backend

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

**Rebuilding the extension** (needed if `context-witness.ts` changes): `uv
build --wheel` recompiles it through `hatch_build.py`, so the probe picks the
change up; a bare `npm --prefix packages/typescript/asterion-prime-extension
run build` only refreshes `dist/`.

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
