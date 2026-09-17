# Live Session Checkpoint

> Updated: 2026-09-17 14:16. **Session remains active — not a final handoff.**
> Supersedes the 12:15 handoff, whose central open question is now answered.

## TL;DR

1. **The eighth defect is found, fixed and committed** (`c03eecad`), by value,
   not by classification. The extension required `summary.retainedMessageCount`,
   which **Pi never emits** — the only producer was the extension test's own
   fake, which is why the suite stayed green while every live run died.
2. **The direction question is closed by measurement.** The socket close is a
   **consequence** of the witness's own 60 s timeout, not its cause; the
   extension rejected 3 ms after receiving the arm frame, 60.057 s earlier.
   The extension's own 5 s channel timeout never fired.
3. **Two more defects sat behind it and are now fixed** (`2f744bf5`), and the
   host **approved the proposal for the first time**. The second was a units
   mismatch: the reservation arithmetic is denominated in tokens, but the
   caller fed it byte counts — cost overstated fourfold, and every cap
   silently four times tighter than its own name.
4. **An eleventh defect is located and deliberately not fixed.** With approval
   working, Pi performs its *own* summarization and **Pi's generation hits its
   token cap**, so `session_compact` never fires, the extension's `persisted()`
   never runs, and the host waits out its 60 s. **P1 still does not pass.**

## 已验证事实

Evidence: live probe runs with epoch-ms marks on both ends, captured values,
passing targeted tests. Each carries its commit.

- **The close follows the timeout (`c03eecad`, measured).** One clock:
  `host-arm-sent` T+0.000 → extension `data-ok`/`read-buffered`/`before-arm`
  T+0.001 → extension `before-failed` **T+0.003** → host
  `witness-receive-FAILED wait=60 TimeoutError` and `host-socket-closed`
  **T+60.063**, caller `backend.py:1241` (teardown). The extension did not time
  out: no `bounded-timeout` mark ever fired.
- **The extension failed inside `before()`, between the arm read and the
  proposal write.** Step marks put it after `s6-tokens` and, one layer down,
  after `p5-role`; the last value read was
  `q1-summaryKeys=role,summary,tokensBefore,timestamp` and
  `q4-rawRetained=undefined`.
- **Pi has no retained count.** `retainedMessageCount` appears **0 times** in
  the installed Pi bundle; Pi's `createCompactionSummaryMessage(summary,
  tokensBefore, timestamp)` emits exactly the four keys observed. Pi expresses
  retention by `firstKeptEntryId`, not by a count.
- **The field is Asterion's own.** It appears in **no spec or plan**, entered
  with the witness feature (`59e14138`), and was pinned by a test (`28a573eb`)
  first. `countRebuiltContext` — the size accounting — does not use it.
- **The 4 KB assumption has three sites**, all from `59e14138`: the extension's
  request bound (`context-witness.ts`, 4096), the host's request bound
  (`context.py:421`, 4096), and `compaction_budget.py:19 _INPUT_CAP_MAX`. The
  summaries request **embeds the serialized conversation**, so all three cap
  the conversation itself (observed `main` = 7114 and 7721 bytes).
- **Fixed and verified (`c03eecad`).** The field is nullable end-to-end,
  sharing one helper with `projectPrimeContext` (two copies of the rule were
  what diverged); both request bounds now use the transport frame cap. TS 16
  tests, `test_asterion_prime_context` 20, `test_asterion_prime_backend` 41,
  detachment gate 0, ruff clean.
- **The proposal now flows.** Post-fix run: `write-start phase=proposal` →
  `write-ok` → `read-ok` → `before-decision status=reject`, with
  `host-decide approved=False remaining_callbacks=4 deadline_in=592.18`.
- Carry-over, still true: `validate_pi_compact_result` accepts one leading
  `agent_settled`; Pi resolves its settings path correctly; the cell-validator,
  `safe_open`, poison-granularity, `with`-body and reserved-name fixes from the
  previous session are all in.

## 当前判断

Chosen on current evidence; not proven.

- **The ninth defect is a budget-policy decision, not a constant to bump.**
  `_INPUT_CAP_MAX` is coupled to `_RESERVED_TOKENS_MAX = 16000` and
  `_COST_MICRO_UNITS_MAX = 125000`: two branches plus two 3276-token outputs
  leave only 4724 per branch, so a **symmetric** per-branch cap cannot hold a
  7114-byte main request while the total holds. The real shape is asymmetric
  (one large main branch, one small turn-prefix branch). Changing it redefines
  what a compaction may cost.
- **Whether the 4 KB family has a fourth site is unchecked.** The three found
  were located by following the failure, not by auditing for the constant.
- **The overall shape is unchanged:** the failures are mostly a narrower
  environment refusing ordinary correct work, plus contract mismatches with Pi.
  The class looks large but each instance has been cheap to fix once measured.

## 历史归档

Rejected or superseded paths, so they are not re-walked.

- **"Asterion's private channel socket closes under the extension, causing the
  cancel."** Half right: the close is real but is teardown, 60 s *after* the
  extension had already cancelled. Do not treat the channel as the suspect.
- **"The extension's 5 s channel timeout fired."** Disproved — no
  `bounded-timeout` mark in any run.
- **"Fabricate a retained count so the host bound stays strict."** Rejected: it
  would make a bound that can never fail, the "always-true predicate"
  anti-pattern this project already recorded.
- Carried over, still rejected: the "session too small" reading (Pi compacts);
  "Pi never read the settings" (disproved); "a check inside `before()` fails"
  (it was a value, not a check, that killed it — but the checks are still
  un-named as a group); "capture worker stderr"; rebuilding the Prime
  compaction dependency; letting the extension import Pi's compaction
  internals; `customInstructions` as sufficient; asking upstream for
  `replaceInstructions`; two Pi instances for independence.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **The P1 witness has NOT passed. P1 stays unpublished.** It now reaches a
  proposal and a host decision, and that decision is `reject`.
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7.**
- **The extension test fake still lies.** `test/ipython-extension.test.mjs`'s
  `buildSessionContext` returns `{role, retainedMessageCount}` — the exact
  shape Pi never produces. Fixing it is the regression guard for the eighth
  defect and has **not** been done.
- **The eleventh defect is located and NOT fixed.** Pi's summarization hits its
  token cap; the witness reaches `state=approved` and times out waiting for a
  persisted frame that is never produced. Nothing has been changed for it.
- The witness has still never completed a compaction end to end. It now goes
  arm → proposal → approve, and stops there.
- `validate_compaction_witness` still requires `entry.get("fromHook") is not
  False`; relax only as part of D-2026-09-16-01.
- Known-unverified carry-overs: `test/context-witness.test.mjs` cannot run;
  `tests/test_core_only_install.py` was already red at HEAD.
- `.asterion-private/p1-diagnose.py`, `p1-probe.sh` and `p1-validate-check.py`
  are temporary diagnostics. Delete them when the diagnosis is done. The probe
  script now also carries host-side decide instrumentation.
- Phase 3's completion stays bounded to Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`.
- The `climb/` loop is dormant and its `next_action` is stale.

## 下一动作

1. **Investigate `reserveTokens: 4096`** (`context-witness.ts`'s `SETTINGS`,
   which both sides pin by exact equality, and whichever Asterion settings file
   feeds Pi the same values). Pi reports `generation hit the token cap and the
   summary is incomplete`. Establish whether the cap is Pi's summary reserve,
   the model's output limit, or Asterion's own bound before changing it — and
   note that 4096 is now the **fourth** appearance of that number on this path,
   so check whether it is another copy of the same wrong assumption.
2. **Then re-run** `sh .asterion-private/p1-probe.sh` and see whether the
   witness completes or reveals a twelfth defect.
3. **Make the extension test fake match Pi** — drop `retainedMessageCount` from
   `test/ipython-extension.test.mjs` so the suite would have caught the eighth.

## Ready-to-paste commands

```bash
# Probe run (Orb, real path, probe entry instead of the operator module):
sh .asterion-private/p1-probe.sh

# Zero-cost boundary check (both sides of the underscore rule):
uv run python .asterion-private/p1-validate-check.py

# Targeted regressions for the compaction path:
uv run python -m unittest tests.test_asterion_prime_context
uv run python -m unittest tests.test_asterion_prime_backend
(cd packages/typescript/asterion-prime-extension && npm run build && \
  node --test test/ipython-extension.test.mjs)

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

**Re-adding the diagnostics.** The extension-side marks were removed from
production source (`git checkout` then the two real fixes re-applied), so
`context-witness.ts` is clean. The technique is recorded in
`docs/status/JOURNAL.md` (2026-09-17): a `stamp(tag)` helper writing
`AST-W <epoch-ms> <tag>` to stderr, plus a `close(reason)` tag to name the
caller; the host side uses the same shape with an `AST-P` prefix. Keep the
volume low — unfiltered stacks exceed Pi's stderr cap and truncate the event
stream (observed). The host-side `_stamp`/`_caller` helpers and the decide
hooks are still present in `.asterion-private/p1-diagnose.py`.

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
