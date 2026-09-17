# Next-Session Handoff

> Updated: 2026-09-17 20:49, end of session. Commits are
> `git log d1535168..HEAD` (stated as a range on purpose — a count goes stale
> the moment this file is committed).

## TL;DR

1. **Phase 4 is complete: P1 is rebuilt, witnessed and republished.**
   `make asterion-prime-p1-run` completed six times with sealed receipts; the
   run now covers setup, verification, and the post-compaction continuation,
   through `stage2.release`, `stage2.complete`, `oracle.pass`, `runner.terminal`.
   `prime.ipython-coding__1.0.0` is back in `create_provider()` and the index.
2. **Fifteen defects were fixed this session, and six were one shape:** a
   contract or fixture narrower than what Pi actually sends, or a claim the
   metric cannot support. The byte-shrink clause alone sat at **six**
   enforcement points.
3. **The next package is Phase 5, and it has no plan.** The program plan stops
   at Phase 4, so Phase 5 needs its own plan before implementation — do not
   start P2 coding against an unwritten plan.

## 已验证事实

Each item is supported by a commit, a captured value, or a passing command.

- **P1's witness passes at its named boundary.** `make asterion-prime-p1-run`
  completed six times with sealed receipts (`d97808e2`, `f4a4c19a`, `ac3fbb1c`,
  `d15c9b45`, `400c45dc`, `838f2db6`), three cells each, `exit 0`. The probe
  path passed three more (`7e5421ad`, `348a1898`, `a4cdc321`). The target needs
  `ASTERION_PRIME_PI_ENTRY`; unset, it fails closed at preflight with status 2.
- **The byte-shrink clause sat at six enforcement points, all removed under
  D-2026-09-17-04** (commits `97c309e4`, `0672e420`, `4f891d66`): the witness
  (`context-witness.ts` and `context.py`), `P1WorkerCheckpoint.__post_init__`,
  `P1StageTwoRelease.__post_init__` (the gate that authorizes stage two), the
  oracle's `verify_stage_two`, `P1OracleReceipt`, and the native receipt. All
  compare canonical-JSON byte counts; a markdown-heavy summary legitimately
  costs more bytes than the conversation it replaces. Measured refusals:
  `7608 → 8657`, `8260 → 8596`, and the witness's five points (closest
  `9952 → 9929`, 23 bytes). Both counts stay required everywhere and are still
  carried as evidence.
- **Enumerating every site at once is what found the last three.** Earlier fixes
  found them one live run at a time because the search was truncated by
  `head -20`; the full scan then showed six. When a wrong constant is found on a
  path, grep the whole path before fixing.
- **The residual failures are model behaviour, not contract defects.** Measured
  twice with values: one continuation returned `final_result=98`, equal to
  `expected_result=98`, but with `file_reads=0` where one read is required (it
  used in-kernel state instead of re-reading the file); another stopped at
  `stage2.release` with no `stage2.complete`, so the continuation turn never
  finished. The oracle correctly rejected both.
- **Three contract corrections were one shape — narrower than Pi.** `usage.cost`
  floats cannot be encoded by the integer-only wire (`206d1d50`);
  `customInstructions` is not a compaction-entry field (`0a97e9cd`); the compact
  result is exactly `{summary, firstKeptEntryId, tokensBefore,
  estimatedTokensAfter, usage, details}` at both of Pi's terminals
  (`67978fe4`). `_compact_rpc_event` projects responses to `{type,id,success}`
  first, so the validator's `command`/`data` requirement was unreachable
  (`a578183b`); authority is
  `docs/superpowers/specs/2026-09-10-asterion-prime-native-p1-shared-kernel-design.md:206`
  — "transport event redaction". Each fixture modelled the narrow shape, which
  is why tests passed; take key sets from Pi's installed bundle.
- **Localization technique that worked four times:** instrument the handler that
  *classifies and discards*, not the code under suspicion. A mark on the ipython
  bridge handler was a **true negative** that refuted the first attribution; a
  mark on `operator.py:768` gave `AST-O run-exc P1WorkerError: P1 worker
  checkpoint rejected` with the exact stack; a mark in `verify_stage_two` gave
  the `final-rejected` values above.
- **Verification commands run at their boundaries:** 183 tests across the
  P1 + core set, 67 across the provider/installed set, all pass; TS extension 16
  with 15 pass; detachment gate **0**.

## 当前判断

Chosen on current evidence; not proven end to end.

- **P1's intermittency is the model, not the harness.** Roughly a third of runs
  the model skips a required step or fails to finish the continuation; the
  oracle catches each one. That is the witness working, not a defect to fix —
  do not "fix" `file_reads != 1` or loosen the oracle.
- **Phase 4's acceptance is met at the named boundary, not promoted.** Six
  passing runs of one task, one game, seed 0, `deepseek-v4-flash`, Level 1,
  `promotion: unpromoted`. Full benchmarking and production promotion remain
  separately authorized.
- **Phase 5 needs a plan first.** Phases 5-9 (P2, P4, P3, P5, P6) were never
  detailed; the manager rule is to repair the roadmap before implementing.
- **Do not read the passing runs as P2-P6 evidence.** Only P1's route was
  exercised.

## 历史归档

Rejected or superseded, recorded so they are not re-walked.

- **"The ipython bridge's bare `except Exception` caused the stop."** Refuted by
  a mark that never fired; the stop came from `operator.py:768` classifying a
  `P1WorkerError`.
- **"Removing the diagnostics caused the Run C regression."** Withdrawn by
  measurement: the next instrumented run showed the guard refusing.
- **"The failure behind the guard is unmeasurable."** Superseded — measured on
  the first instrumented run that passed the guard.
- **"Publishing P1 broke the P7 installed route."** Refuted: the same test fails
  at HEAD with the same underlying cause (`Prime solver runtime did not
  complete`), verified by running HEAD with the diagnostic in place.
- **"The validator's `command`/`data` requirement is the live contract"** and
  **"the compact result is four keys."** Rejected: the fixtures modelled shapes
  production never sends.
- Carried over, still rejected: the "session too small" reading (Pi compacts);
  "Pi never read the settings" (disproved); "the channel socket close causes the
  cancel" (it is teardown); "the extension's 5 s channel timeout fired"; the
  "4096 request bound is the whole story"; "capture worker stderr"; rebuilding
  the Prime compaction dependency; letting the extension import Pi's compaction
  internals; `customInstructions` as sufficient; asking upstream for
  `replaceInstructions`; two Pi instances for independence.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **Phase 5 has no plan.** Writing it is the first task of the next package.
- **`compaction_budget` still under-reserves.** `reserveTokens` is 16384, so Pi
  may generate up to 13107 output tokens per branch, while the reservation
  assumes 3276 and `_RESERVED_TOKENS_MAX` is 16000. Left deliberately
  under-reserved rather than silently widened.
- **The extension test fake still lies.** `test/ipython-extension.test.mjs`'s
  `buildSessionContext` returns `{role, retainedMessageCount}` — the exact shape
  Pi never produces. Not done.
- **P1-P7 native implementations: 2 of 7** — P7 and P1. P2-P6 remain unbuilt.
- Three pre-existing red tests, each confirmed at HEAD by running it, not by
  inference: `tests/test_pi_session` (1F+6E, `Pi RPC process exited
  unexpectedly`), `tests/test_prime_p7_native_installed`
  (`CapabilityExecutionError: Prime solver runtime did not complete`),
  `tests/test_core_only_install.py`. `test/context-witness.test.mjs` cannot run.
  `tests.test_asterion_prime_pi_contract` does not exist (a stale `.pyc`
  suggested it did).
- `validate_compaction_witness` still requires `entry.get("fromHook") is not
  False`; relax only as part of D-2026-09-16-01.
- `.asterion-private/p1-diagnose.py`, `p1-probe.sh`, `p1-resolve-probe.py` and
  `p1-validate-check.py` are temporary diagnostics. Delete them when done. The
  probe carries host-side decide/quote instrumentation.
- Phase 3's completion stays bounded to Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`.
- The `climb/` loop is dormant and its `next_action` is stale.
- The P1 run's private receipt artifact lands in the operator's own per-run temp
  root inside Orb; `/tmp/piagent-probe` holds only `settings.json`. Do not
  assume it is on the host.

## 下一动作

1. **Write the Phase 5 plan** (P2 rebuild) before any implementation, following
   the shape of the Phase 4 section in
   `docs/superpowers/plans/2026-09-12-asterion-prime-p1-p7-native-detachment.md`
   — acceptance verbatim from the spec, tasks, a "do not" list, carried risks.
   Carry forward this session's lesson: take every contract key set from Pi's
   own construction sites, and grep the whole path when a constant is wrong.
2. **Reconcile `compaction_budget` with the output ceiling** (see 未完成边界).
3. **Make the extension test fake match Pi** — drop `retainedMessageCount`.

## Ready-to-paste commands

```bash
# P1 acceptance at its named boundary (needs the operator-owned Pi entry):
ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js \
  make asterion-prime-p1-run

# Probe variant with tracing hooks and a teed log:
sh .asterion-private/p1-probe.sh

# Targeted regressions for the changed surfaces:
uv run python -m unittest tests.test_asterion_prime_p1_operator tests.test_asterion_prime_p1_oracle \
  tests.test_asterion_prime_p1_worker tests.test_asterion_prime_p1_runtime
uv run python -m unittest tests.test_asterion_prime_backend tests.test_asterion_prime_context
uv run python -m unittest tests.test_asterion_prime_p1_provider tests.test_asterion_prime_p1_installed \
  tests.test_prime_p7_native_provider tests.test_installed_application_provider
(cd packages/typescript/asterion-prime-extension && npm run build && \
  node --test test/ipython-extension.test.mjs)

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

**Reading a run.** The operator prints `{"stage":"..."}` with no space after the
colon, so grep `{"stage":"` — a spaced pattern matches nothing and looks like an
empty run. The stage trail localizes the failure: `stage2.complete` without
`oracle.pass` means the stage-two oracle rejected; `stage2.release` without
`stage2.complete` means the continuation turn never finished.

**Recovering a discarded cause.** `run_composed_application` raises
`ApplicationRunError(...) from None`, and several P1 handlers classify without
recording. Either instrument the *classifying handler* with a temporary stderr
mark, or walk `error.__context__` in a wrapper and print the chain. Both worked
this session; guessing did not, six times running.

**Stack frames carry no line number.** esbuild emits the extension bundle as one
line, so read the **column**, and skip the first two frames (`unavailable`,
`fail`), which are constant for every call site.

**Keep extension stderr small.** Unfiltered stacks exceed Pi's stderr cap and
truncate the event stream (observed). One short line per mark. Note that
`tests/test_asterion_prime_p1_operator.py` asserts the operator's stderr is
empty, so any temporary mark makes that test fail loudly — revert marks before
running it.

**Rebuilding the extension:** `uv build --wheel` recompiles it through
`hatch_build.py`, so both the probe and `make asterion-prime-p1-run` pick the
change up; a bare `npm --prefix packages/typescript/asterion-prime-extension run
build` only refreshes `dist/`.

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
