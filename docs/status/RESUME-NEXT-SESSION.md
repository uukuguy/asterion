# Live Session Checkpoint

> Updated: 2026-09-17 18:58. **Session remains active — not a final handoff.**
> Supersedes the 18:32 checkpoint in this same session: the guard decision was
> taken and the compaction path now completes end to end.
> Commits this session: `git log d1535168..HEAD` (stated as a range on purpose).

## TL;DR

1. **The compaction path completes end to end for the first time.** The witness
   accepts the persisted frame, the RPC terminal validates, and the receipt is
   `status=succeeded` with `before_context_tokens=7608 / after_context_tokens=8657`.
   The whole resume chain then runs: `journal.reopen → host2.recover →
   authority.sync → resume.admit → resume.persist → host2.close`.
2. **Six defects were fixed** (`206d1d50`, `0a97e9cd`, `a578183b`, `97c309e4`,
   `67978fe4`). Three were the same shape: a contract or fixture narrower than
   what Pi actually sends. The shrink-guard decision was taken by the user.
3. **The chain now stops after the resume.** The continuation cell never runs
   (`cells_recorded: 2`), and the reason is discarded by a bare `except
   Exception` in the ipython bridge. **P1 still does not pass and stays
   unpublished.**

## 已验证事实

Each item is supported by a commit, a captured value, or a passing command.

- **The persisted frame was never written (`206d1d50`).** The extension sent
  Pi's raw entry, which carries `usage.cost` with float values
  (`input: 0.00023002000000000002`, `cacheRead: 7.168e-07`). `canonicalJson` is
  `canonical(value, false)` (`context-projection.ts:147`) and rejects any
  non-safe-integer, so `digest(entry)` and `#channel.write` both threw. The same
  field was independently refusable: the host's accepted entry keys exclude
  `usage`. The wire now carries the contract fields; the digest covers what was
  sent.
- **Stack frames carry no line number.** esbuild emits the bundle as a single
  line (44618 chars on line 1), so every frame reports line 1; only the column
  distinguishes one `fail()` site from another. The columns resolved to
  `invalid()` ← `canonical`'s number branch.
- **`customInstructions` is not a compaction-entry field (`0a97e9cd`).** Both of
  Pi's construction sites omit it, and `createCompactionSummaryMessage` emits
  only `role`, `summary`, `tokensBefore`, `timestamp`; Pi carries custom
  instructions on the `before_compaction` hook event. Measured:
  `pd-check tokens=2723 declared=2723 cust=undefined`. The host compared an
  absent field against a declared value, so it could only pass while that value
  was null — the fixture's only case.
- **The compact response contract was unreachable (`a578183b`).**
  `_compact_rpc_event` projects a response to `{type,id,success}` before the
  validator sees it. Authority:
  `docs/superpowers/specs/2026-09-10-asterion-prime-native-p1-shared-kernel-design.md:206`
  — "`PiRpcConfig.compact_events` is transport event redaction". The reducer
  `063b6cc9` (09-09) predates the validator `8f8c6709` (09-10), so the
  requirement was unreachable from the moment it was written.
- **The compact result is exactly six keys (`67978fe4`).** Verified in the
  installed bundle at both of Pi's terminals:
  `{summary, firstKeptEntryId, tokensBefore, estimatedTokensAfter, usage,
  details}`. The validator allowed four, so a real successful compaction was
  refused. `usage` is absent when undefined, so the set stays an allowance.
- **The byte shrink guard is gone (`97c309e4`), by user decision.** The
  projection equality already binds the rebuild to Pi's retained tail plus the
  summary; the only free quantity is the summary's size. Five measured points
  sat on both sides, the closest by 23 bytes (`post=9952 pre=9929`), with `eq=1`
  in every one. `pre_units` stays validated (`context.py:387` holds
  `pre_units == count_rebuilt_context(pre)`) and `after_context_tokens` is still
  reported; only the bound was removed.
- **A live run now completes the compaction.** `WITNESS FRAME RECEIVED` twice
  (proposal and persisted), `RPC COMPACT RESULT {"events": [agent_settled,
  compaction_start, compaction_end, response], "outcome": "completed"}`, then
  `COMPACT RECEIPT status=succeeded` with `before_context_tokens=7608`,
  `after_context_tokens=8657`. The resume chain then runs to `host2.close` with
  no exception trace anywhere in the log.
- **Verification commands run at their boundaries:** `test_asterion_prime_context`
  25, `test_asterion_prime_backend` 43, `test_asterion_prime_p1_operator` 26 — 94
  pass; TS extension 16 with 15 pass.
- **Two pre-existing failures were confirmed by reverting to HEAD source, not by
  inference.** `test/ipython-extension.test.mjs`'s "the arm frame's native
  material drives the request the witness proposes" fails identically on
  unmodified HEAD. `tests.test_pi_session` is red at HEAD with **1 failure + 6
  errors** (`Pi RPC process exited unexpectedly`), verified twice; it is **not**
  in the previous carry-over list.

## 当前判断

Chosen on current evidence; not proven end to end.

- **The stop after the resume is a discarded exception, not a decision.**
  `operator.py:887-890` catches `Exception` in the ipython bridge and calls
  `request_stop("recovery-required")` without recording the cause, which is why
  the log holds no traceback. Nothing about the run looks like a refusal: every
  stage reports success and the shutdown is clean. Recover the value before
  changing anything — this is the recorded "a classification is not a cause"
  pattern, and guessing at it has never once been right on this path.
- **Three of this session's defects were one shape: a contract narrower than
  reality.** The extension's wire entry, the witness's entry key set, and the
  RPC compact result all modelled fewer fields than Pi sends, and in each case
  the fixture modelled the same narrow shape, so tests passed. When adding a
  contract here, take the key set from Pi's own construction site.
- **The overall shape is unchanged:** mostly a narrower environment refusing
  ordinary correct work, plus contract mismatches with Pi. Each instance has
  been cheap to fix once measured; guessing at them has never once been right.

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
- **"The failure behind the guard is unmeasurable."** Superseded — measured on
  the first instrumented run that passed the guard.
- **"Removing the diagnostics caused the Run C regression."** Withdrawn by
  measurement: the next instrumented run showed the guard refusing at
  `post=9952 pre=9929`.
- **"The validator's `command`/`data` requirement is the live contract"** and
  **"the compact result is four keys."** Both rejected: the fixtures modelled
  shapes production never sends.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **The P1 witness has NOT passed. P1 stays unpublished.** The compaction and
  resume stages complete; the continuation turn never runs.
- **The stop after `resume.persist` is unexplained.** One occurrence; the cause
  is discarded by the bridge's bare `except Exception`.
- **`compaction_budget` still under-reserves.** `reserveTokens` is 16384, so Pi
  may generate up to 13107 output tokens per branch, while the reservation
  assumes 3276 and `_RESERVED_TOKENS_MAX` is 16000. Left deliberately
  under-reserved rather than silently widened.
- **The extension test fake still lies.** `test/ipython-extension.test.mjs`'s
  `buildSessionContext` returns `{role, retainedMessageCount}` — the exact shape
  Pi never produces. Not done.
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7.**
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

1. **Recover the discarded exception in the ipython bridge.** Instrument
   `operator.py:887-890` (temporary, not for commit) to print the exception type
   and traceback to stderr, then re-run and read it. Do **not** change the
   handler before the value is in hand — it is one of several places that
   classify without recording.
2. **Then read whatever the continuation turn needs.** `cells_recorded: 2` says
   the third cell was never requested, so the question is whether the operator
   stopped before asking for it or the request failed on the way.
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
(cd packages/typescript/asterion-prime-extension && npm run build && \
  node --test test/ipython-extension.test.mjs)

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

**Reading a failed run.** The probe log's stage markers name the position. Useful
greps: `RPC COMPACT EVENTS` (names the stage a compact died at),
`witness-receive-FAILED` (the host's 60 s bound expired with no frame),
`COMPACT RECEIPT` (its `status` and token counts), and the `{"stage": ...}`
trail, which shows how far the resume chain got.

**Marks that worked for the extension.** A `stamp(tag)` helper writing
`AST-W <epoch-ms> <tag>` to stderr, called at `pd-enter`, `pd-event`,
`pd-entry`, `pd-check`, `pd-summary`, `pd-branch`, `pd-units` (carrying the
actual `post`/`pre`/`eq` values), `pd-writing`, `pd-written`, `pd-ack`, and
`pd-failed` in the catch. All reverted; re-add them the same way.

**Keep extension stderr small.** Unfiltered stacks exceed Pi's stderr cap and
truncate the event stream (observed). One short line per mark.

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
is the authority; two of this session's defects came from trusting a fixture
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
