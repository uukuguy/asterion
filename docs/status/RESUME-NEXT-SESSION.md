# Live Session Checkpoint

> Updated: 2026-09-17 18:32. **Session remains active — not a final handoff.**
> Supersedes the 16:15 handoff: its next action (reproduce the failure behind
> the guard) is done, and three further defects were found and fixed.
> Commits this session: `git log d1535168..HEAD` (stated as a range on purpose).

## TL;DR

1. **The failure behind the guard was measured, and three defects are fixed.**
   Pi's compaction entry carries float `usage.cost`, which the integer-only wire
   canonical form cannot encode, so the persisted frame was never written at
   all. Fixing that exposed two more: the host required a `customInstructions`
   entry field Pi does not persist, and the RPC terminal validator required
   response fields that `compact_events` redaction removes by design.
2. **The witness now completes.** `pd-written` → `pd-ack` on a live run, the
   host accepts the persisted frame, and the RPC terminal validates. The chain
   stops at the rebuild guard instead.
3. **The guard is confirmed marginal, now by 23 bytes.** `post=9952 pre=9929`.
   Its unit is a public-contract decision and is the one thing this session did
   not decide. **P1 still does not pass and stays unpublished.**

## 已验证事实

Each item is supported by a commit, a captured value, or a passing command.

- **The persisted frame was never written (`206d1d50`).** The extension sent
  Pi's raw entry, which carries `usage.cost` with float values
  (`input: 0.00023002000000000002`, `cacheRead: 7.168e-07`). `canonicalJson` is
  `canonical(value, false)` (`context-projection.ts:147`) and rejects any
  non-safe-integer at line 132, so `digest(entry)` and `#channel.write` both
  threw. The marks showed `pd-units` then **no `pd-written`**. The same field was
  independently refusable: the host's accepted entry keys are
  `{type,id,parentId,timestamp,firstKeptEntryId,summary,tokensBefore}` plus
  optional `{details,fromHook}`, so `usage` would have been rejected on arrival.
  The wire now carries the contract fields and the digest covers what was sent.
- **The failing check was localized by stack column, not by line.** esbuild emits
  the bundle as a single line (44618 chars on line 1), so every frame reports
  line 1. Only the column distinguishes one `fail()` site from another; the
  columns resolved to `invalid()` ← `canonical`'s number branch.
- **`customInstructions` is not a compaction-entry field (`0a97e9cd`).** Both of
  Pi's construction sites omit it — `appendCompaction(summary, firstKeptEntryId,
  tokensBefore, details, fromHook, usage)` and the `publishStructuralOutcome`
  entry — and `createCompactionSummaryMessage` emits only `role`, `summary`,
  `tokensBefore`, `timestamp`. Pi carries custom instructions on the
  `before_compaction` **hook event**. Measured directly:
  `pd-check tokens=2723 declared=2723 cust=undefined`. The host compared an
  absent field against the proposal's declared value, so it could only pass
  while that value was null — the fixture's only case
  (`test_asterion_prime_context.py:59`). Same family as the eighth defect: the
  test modelled a scenario production never produces.
- **The compact response contract was unreachable (`a578183b`).**
  `_compact_rpc_event` (`pi_rpc.py:76-79`) projects a response to
  `{type,id,success}` before the validator sees it. The validator required
  `command == "compact"` and key set `{id,command,success,data}`, which the
  running path never delivers. Authority:
  `docs/superpowers/specs/2026-09-10-asterion-prime-native-p1-shared-kernel-design.md:206`
  — "`PiRpcConfig.compact_events` is transport event redaction". Dates settle the
  direction: the reducer `063b6cc9` (09-09) predates the validator `8f8c6709`
  (09-10), so the requirement was unreachable from the moment it was written.
  The fixtures modelled the **unredacted** stream, which is why it survived.
- **The rebuild guard is marginal, now at five measured points** (`eq=1` in every
  one, so the projections agree and only the byte metric decides):
  8776→9259 (refuse, +5.5%), 8804→8701 (pass, −1.2%), 7672→7884 (refuse, +2.8%),
  9572→10758 (pass, −11%), 9952→9929 (**refuse, +0.23% — 23 bytes**).
- **Verification commands run at their boundaries:** `test_asterion_prime_context`
  24, `test_asterion_prime_backend` 42, `test_asterion_prime_p1_operator` 26 — all
  pass; TS extension 16 with 15 pass.
- **Two pre-existing failures were confirmed by reverting to HEAD source, not by
  inference.** `test/ipython-extension.test.mjs`'s "the arm frame's native
  material drives the request the witness proposes" (`witness peer timed out`)
  fails identically on unmodified HEAD. `tests.test_pi_session` is red at HEAD
  with **1 failure + 6 errors** (`Pi RPC process exited unexpectedly`), verified
  twice by reverting; it is **not** in the previous carry-over list.

## 当前判断

Chosen on current evidence; not proven end to end.

- **The shrink guard's unit is a contract decision, not a bug fix.** The entry
  carries `tokensBefore` but no `estimatedTokensAfter` (that lives in the
  compaction *result*, not the entry), so the extension cannot price the after
  side in tokens from what it has. A byte-based guard cannot express Pi's own
  claim and loses discriminating power at the boundary; a token-based one needs
  a source that does not currently exist on the persisted path. The host's
  `context.py` uses the same metric and must move with whatever is chosen.
- **Do not widen the guard by a fitted factor.** Five points is not enough to
  justify a constant, and a tolerance fitted to them would be the "constant that
  echoes elsewhere" failure this project has already recorded.
- **The three fixes are contract corrections, not loosenings.** Each replaced a
  requirement on a field the running path never produces with the field it does;
  none removed a check that could ever have passed.
- **The overall shape is unchanged:** mostly a narrower environment refusing
  ordinary correct work, plus contract mismatches with Pi. Each instance has
  been cheap to fix once measured; guessing at them has never once been right.

## 历史归档

Rejected or superseded, recorded so they are not re-walked.

- Carried over, still rejected: the "session too small" reading (Pi compacts);
  "Pi never read the settings" (disproved); "Asterion's channel socket close
  causes the cancel" (it is teardown); "the extension's 5 s channel timeout
  fired" (no `bounded-timeout` mark ever); "fabricate a retained count to keep
  the host bound strict"; "the 4096 request bound is the whole story"; "capture
  worker stderr"; rebuilding the Prime compaction dependency; letting the
  extension import Pi's compaction internals; `customInstructions` as sufficient;
  asking upstream for `replaceInstructions`; two Pi instances for independence.
- **"The failure behind the guard is unmeasurable."** Superseded — it was
  measured on the first instrumented run that passed the guard.
- **"Removing the diagnostics caused the Run C regression."** Withdrawn by
  measurement: the next instrumented run showed the guard refusing at
  `post=9952 pre=9929`, so the same code fails whenever the guard refuses.
- **"The validator's `command`/`data` requirement is the live contract."**
  Rejected: the fixture modelled the raw stream, not the redacted one.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **The P1 witness has NOT passed. P1 stays unpublished.** It reaches the
  rebuild comparison and stops when the guard refuses.
- **The rebuild guard is unfixed**, and its unit question is undecided.
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

1. **Decide the rebuild guard's unit** — the one open contract choice. The entry
   has no `estimatedTokensAfter`; the host's `context.py` uses the same metric
   and must move with it. Options seen so far: drop the shrink comparison and
   keep only the projection-equality invariant; denominate in tokens with a new
   source on the persisted path; or compare something Pi actually claims.
   **Ask before implementing** — this is a public-contract change.
2. **Then re-run until the guard passes** and read whatever fails next. Every
   stage behind it has now been reached at least once except a clean terminal.
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

**Reading a failed run.** The probe log's `RPC COMPACT EVENTS` list names the
stage. `extension_error` on `session_compact` with `witness-receive-FAILED
wait=60` means `persisted()` threw; re-add the marks to learn which check.
Marks that worked: a `stamp(tag)` helper writing `AST-W <epoch-ms> <tag>` to
stderr, calls at `pd-enter`, `pd-event`, `pd-entry`, `pd-check`, `pd-summary`,
`pd-branch`, `pd-units` (with the actual `post`/`pre`/`eq` values),
`pd-writing`, `pd-written`, `pd-ack`, and `pd-failed` in the catch.

**Keep extension stderr small.** Unfiltered stacks exceed Pi's stderr cap and
truncate the event stream (observed). One short line per mark.

**Stack frames carry no line number.** esbuild emits the bundle as one line, so
read the **column**; skip the first two frames (`unavailable`, `fail`), which are
constant for every call site.

**Rebuilding the extension:** `uv build --wheel` recompiles it through
`hatch_build.py`, so the probe picks the change up; a bare `npm --prefix
packages/typescript/asterion-prime-extension run build` only refreshes `dist/`.
`npm run build` runs `tsc` first and will fail the wheel build if the TS does
not typecheck.

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
