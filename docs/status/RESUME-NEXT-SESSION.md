# Next-Session Handoff

> Updated: 2026-09-17 16:15, end of session. This session's commits are
> `git log 1d21ef05..HEAD` — 20 of them. Stated as a range on purpose, so a
> hard-coded count cannot go stale on commit.
> Supersedes the 12:15 handoff, whose central open question is now answered.

## TL;DR

1. **The direction question is closed by measurement.** Asterion's socket close
   is teardown, 60.06 s *after* the extension had already cancelled — a
   consequence, not the cause. The extension's own 5 s channel timeout never
   fired. RESUME's binary framing was incomplete; the answer is neither side.
2. **Four defects were fixed and committed** (`c03eecad`, `2f744bf5`,
   `0f1a7d98`). The witness now runs arm → proposal → approve → Pi compacts →
   rebuild check. Before this session it died inside the extension's first
   check.
3. **Two things are open and must not be read as done.** The rebuild guard is
   *marginal* — three measured runs land on both sides of it — and a further
   failure, seen once behind a passing guard, **has never been measured**.
   **P1 does not pass and stays unpublished.**

## 已验证事实

Each item is supported by a commit, a captured value, or a passing command.

- **The close follows the timeout (`c03eecad` path, measured).** One clock:
  `host-arm-sent` T+0.000 → extension `data-ok`/`read-buffered`/`before-arm`
  T+0.001 → extension `before-failed` **T+0.003** → host
  `witness-receive-FAILED wait=60 TimeoutError` and `host-socket-closed`
  **T+60.063**, caller `backend.py:1241` (teardown). No `bounded-timeout` mark
  ever fired, so the extension's 5 s channel bound is not the cause either.
- **Pi has no retained count.** `retainedMessageCount` appears **0 times** in
  the installed Pi bundle; `createCompactionSummaryMessage(summary,
  tokensBefore, timestamp)` emits exactly the four keys observed
  (`q1-summaryKeys=role,summary,tokensBefore,timestamp`,
  `q4-rawRetained=undefined`). Pi states retention by `firstKeptEntryId`.
- **That field is Asterion's own.** It appears in **no spec or plan**, entered
  with the witness feature (`59e14138`), was pinned by a test (`28a573eb`)
  first, and `countRebuiltContext` does not use it. Fixed at `c03eecad`: the
  field is now nullable end to end, sharing one helper with
  `projectPrimeContext` — two copies of the same rule were what diverged.
- **The reservation was denominated in tokens and fed bytes.** Its constants
  are `_..._TOKENS_MAX` and its cost is priced per million tokens, but the
  caller passed `len(request.encode())`. The tell: the operator's
  `_COMPACTION_INPUT_CAPS = (4096, 4096)` is the same number as the old
  `_INPUT_CAP_MAX`. Cost was overstated fourfold and every cap silently
  tightened fourfold. Fixed at `2f744bf5`; the host then approved a proposal
  for the first time (`host-quote caps=(1740, 261) approved=True`).
- **Pi truncates the summary at `min(floor(0.8 * reserveTokens),
  model.maxTokens)`.** Asterion set `reserveTokens: 4096` against Pi's own
  default of `16384`, so the cap was 3276 and Pi reported
  `Summarization failed: generation hit the token cap and the summary is
  incomplete` (`stopReason === "length"`). Measured both ways, twice each:
  4096 fails, 16384 completes. Fixed at `0f1a7d98` on both sides, because the
  extension asserts Pi's `preparation.settings` equals its own `SETTINGS`
  exactly — one value in two files.
- **The rebuild comparison is marginal, not wrong.** Three runs:
  `pre_bytes → post_bytes` = 8776→9259 (refused), 8804→8701 (passed),
  7672→7884 (refused). A markdown-heavy summary costs more JSON bytes per token
  than the conversation it replaces, so the byte metric loses discriminating
  power at the boundary. `post_msgs=4` vs `pre_msgs=8`.
- **Pi's compaction entry carries `tokensBefore` but not
  `estimatedTokensAfter`.** `entryKeys=type,id,parentId,timestamp,summary,
  firstKeptEntryId,tokensBefore,details,usage,fromHook`. The after-count lives
  in the compaction *result*, not the entry.
- **Everything else in the persisted path passes:** `pd-entry fromHook=false`,
  `pd-branch tail==true prefix==true`, `pd-post equal=true`.
- Verification commands are below and were run at the stated boundaries: TS
  extension 16, `test_asterion_prime_context` 23, `test_asterion_prime_p1_operator`
  26, `test_asterion_prime_backend` 41; detachment gate 0; ruff clean.

## 当前判断

Chosen on current evidence; not proven end to end.

- **The extension's diagnostics must be re-added before deciding the guard.**
  In the single run where the guard passed, Pi still emitted `extension_error`
  — so at least one more failure sits behind it. Changing the guard first would
  fix a checkpoint the chain may not even be stopping at.
- **A uniform divisor will not fix the guard.** Bytes/4 is a scalar multiple of
  bytes, so the comparison is unchanged; the divergence is real (markdown is
  byte-fat per token), not an encoding artifact.
- **The `reserveTokens` change is measured, not witness-confirmed.** It is
  justified by two runs each way. It is *not* justified by the witness passing,
  which it does not. 16384 is upstream's own default, so it restores Pi's value
  rather than inventing one — but the rule about not promoting unvalidated
  values to defaults applies and is recorded rather than waved away.
- **The overall shape is unchanged:** mostly a narrower environment refusing
  ordinary correct work, plus contract mismatches with Pi. Each instance has
  been cheap to fix once measured; guessing at them has never once been right.

## 历史归档

Rejected or superseded, recorded so they are not re-walked.

- **"Asterion's channel socket close causes the cancel."** Half right: the close
  is real but is teardown, 60 s *after* the extension cancelled.
- **"The extension's 5 s channel timeout fired."** Disproved — no
  `bounded-timeout` mark in any run.
- **"Fabricate a retained count so the host bound stays strict."** Rejected: it
  would make a bound that can never fail.
- **"The 4096 request bound is the whole story."** It was one site of three; the
  units mismatch underneath it was the real one.
- **"`_INPUT_CAP_MAX` alone is the ninth defect."** Superseded by the units
  finding; the derived cap is retained but was not the blocker.
- Carried over, still rejected: the "session too small" reading (Pi compacts);
  "Pi never read the settings" (disproved); "capture worker stderr"; rebuilding
  the Prime compaction dependency; letting the extension import Pi's compaction
  internals; `customInstructions` as sufficient; asking upstream for
  `replaceInstructions`; two Pi instances for independence.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **The P1 witness has NOT passed. P1 stays unpublished.** It reaches the
  rebuild comparison and stops.
- **The failure behind the guard is known to exist and has never been
  measured.** One occurrence, not reproduced.
- **The rebuild guard is unfixed**, and its unit question is undecided.
- **`compaction_budget` now under-reserves.** `reserveTokens` is 16384, so Pi
  may generate up to 13107 output tokens per branch, while the reservation
  still assumes 3276 and `_RESERVED_TOKENS_MAX` is 16000. Left deliberately
  under-reserved rather than silently widened.
- **The extension test fake still lies.** `test/ipython-extension.test.mjs`'s
  `buildSessionContext` returns `{role, retainedMessageCount}` — the exact
  shape Pi never produces. Fixing it is the regression guard for the eighth
  defect and has **not** been done.
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7.**
- `validate_compaction_witness` still requires `entry.get("fromHook") is not
  False`; relax only as part of D-2026-09-16-01.
- Known-unverified carry-overs: `test/context-witness.test.mjs` cannot run;
  `tests/test_core_only_install.py` was already red at HEAD;
  `tests.test_asterion_prime_pi_contract` does not exist (a stale `.pyc`
  suggested it did).
- `.asterion-private/p1-diagnose.py`, `p1-probe.sh` and `p1-validate-check.py`
  are temporary diagnostics. Delete them when the diagnosis is done. The probe
  script carries host-side decide/quote instrumentation.
- Phase 3's completion stays bounded to Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`.
- The `climb/` loop is dormant and its `next_action` is stale.

## 下一动作

1. **Re-add the extension marks and reproduce the failure behind the guard.**
   The marks are recorded in `docs/status/JOURNAL.md` (2026-09-17): a
   `stamp(tag)` helper writing `AST-W <epoch-ms> <tag>` to stderr, inside
   `persisted()` — `pd-enter`, `pd-event`, `pd-entry`, `pd-summary`,
   `pd-branch`, `pd-post`, `pd-writing`, `pd-ack`, and `pd-failed` in the catch.
   Run until one passes the guard; read what fails after it.
2. **Then decide the shrink guard's unit**, with that value in hand. Note the
   entry has no `estimatedTokensAfter`, so a token-denominated replacement
   needs another source. The host's `context.py` uses the same metric and must
   move with it.
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
uv run python -m unittest tests.test_asterion_prime_p1_operator
uv run python -m unittest tests.test_asterion_prime_backend
(cd packages/typescript/asterion-prime-extension && npm run build && \
  node --test test/ipython-extension.test.mjs)

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

**Rebuilding the extension** (needed if `context-witness.ts` changes): `uv
build --wheel` recompiles it through `hatch_build.py`, so the probe picks the
change up; a bare `npm --prefix packages/typescript/asterion-prime-extension
run build` only refreshes `dist/`. `npm run build` runs `tsc` first and will
fail the wheel build if the TS does not typecheck.

**Keep extension stderr small.** Unfiltered stacks exceed Pi's stderr cap and
truncate the event stream (observed). One short line per mark.

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
