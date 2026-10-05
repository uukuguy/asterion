# P7 WorldMap implementation review and verification

Date: 2026-10-05. Scope: approved Prime workspace / P7 solver / console redesign.

## Architecture

Prime owns persistent computation, explicit source/JSON exports and recovery. P7 supplies read-only observation access, versioned WorldMap and host-checked reports; the actor alone submits predictions to the existing Broker. Default runs expose exactly three tools and do not inject historical routes or shared cognition. The existing Prime session owns model continuation; no second runner was added.

## Independent review and corrections

Astra reviewed generic kernel/admission, console, and solver/application wiring. Corrections:

- Python errors remain settled tool results; a repairable cell cannot poison the shared bridge. Kernel loss retains its own status.
- The bridge keeps one event loop for worker startup, all cells and cleanup; no persistent subprocess transport crosses per-cell loops.
- Actor responses retain bounded settled frames, references, budgets and action settlement. Large research and prediction projections explicitly signal omitted detail; authoritative history stays complete.
- Terminal WIN events use the final valid level so the console keeps the final feedback.
- Cleanup executes even when writing control state fails. Actual research-host closure and cell lifecycle drive diagnostics.

Read-only RPC isolation is an application capability boundary, not an OS sandbox for arbitrary Python. Host report checks establish prediction agreement with observations, not a proof of complete model correctness.

## Provider-free evidence

- Generic real-worker workspace: 16 tests. Prime admission/session: 40 tests.
- Console/control: 105 Python tests; shipped-asset DOM suite: 74 tests, zero skips. Actual exported HTML exercised without external requests.
- Runtime integration: real kernel computes predictions, actor publishes, second real Broker action contradicts prediction, suffix stops, WorldMap is revised. Actual socket bridge preserves namespace across a Python error. Explicit checkpoint survives computation loss and requires calibration before action.
- Installed wheel tests: legacy regression explicitly isolated; new default registers three tools and runs real kernel exports, publication and predicted actions through Solver/Broker.
- Per user correction, UI acceptance remains the established background DOM/HTTP/export workflow. An unnecessary Chrome connection attempt timed out; it is not a gate and supplies no verification claim.

Final independent implementation re-review accepted the corrected primary path. A low-probability constructor-failure cleanup tail remains outside the verified normal lifecycle; no broad hardening was added.

Final related Python suite: **365 tests PASS**. `make lint docs-check`: PASS (274 Markdown files, 63 local links).

## Deployment and ability boundary

- Extension final test: 39 total, 33 PASS, 6 external-Pi skips. Generated resource synchronized after source freeze.
- `make promotion-check`: 3957 tests, 15 failures / 5 errors / 4 skips; **not PASS**. The wrapper retained only its tail (existing source-detachment failures). One full Python 3.12 rerun recorded 3957 tests / 12 failures / 4 errors / 4 skips. Two new failures were obsolete core-module inventory and tool allowlist assertions, fixed in `b45977e6` with three targeted checks passing. The other 14 failing cases match historical names and causes. Promotion used Python 3.14; its additional 3 failures / 1 error were not fully reproduced, so the full gate remains non-PASS. No second complete rerun was done.
- Real packaged `make asterion-prime-p7-level-witness GAME=sp80 LEVEL=1`: **PASS**. Run `p7-live-20261005212851-4b7287c4dc5d498db14c16a6`, seed 0, model gpt-6.1-sol, commit `a1aef743`. Fixed existing 900-second cgroup preset; human-baseline action cap 39. Completed Level 1 with **9 actions**, remaining 30; target stop `level-completed`, replay verified, trace sealed, cleanup complete. Exact guest unit is inactive/dead with MainPID 0.
- First live attempt used six actor plans and four workspace focus calls, **zero IPython cells**, no WorldMap publication. `playbook_loaded=false`, `replayed_prefix_actions=0`. This proves a fresh default-path Level 1 completion; it does **not** prove program-model-driven reasoning or cross-level transfer. No old route or human save was injected.
- A second bounded fresh run targets Level 2 by naturally replaying neither route nor prefix: `p7-live-20261005213404-18a2a34f77bf46a4b282e66b`, same fixed 900-second preset, target-level human-baseline cap. It completed **Level 2 in 20 total actions**, replay verified, trace sealed, cleanup complete; guest unit inactive/dead/MainPID 0. Ten actor plans, four focus calls, zero cells/publications, no prefix or playbook loaded. This establishes fresh natural two-level completion, but not persistent WorldMap use or program-model transfer.

Full 25-game evaluation is outside this authorization. No benchmark percentage is inferred from these partial witnesses.

## Evidence-driven completion of the main reasoning path

The real attempts exposed a structural bypass: the initial empty revision admitted plans indefinitely, and focus only changed the current task. This allowed successful direct planning with no external WorldMap. Requiring Python/export boilerplate for a semantic update plausibly discouraged publication; that causal explanation is a current judgment, while the bypass and zero publication are verified facts.

The existing workspace tool now supports direct, bounded semantic `revise`, preserving optional program publication. Plans will use a meaningful current semantic revision; mismatches, actual RESET and level changes will require one update grounded in current evidence before the next plan. Matched predictions may retain their revision. This does not require complete rules, report certification, one experiment per hypothesis, or compulsory computation. Independent supplement review passed. Extension tests: 33 PASS / 6 external-Pi skips; related integration Python suite: 317 PASS; final task-declaration event patch: 18 Solver tests PASS. Packaged extension synchronized. Direct semantic updates emit actor task declarations plus model revisions, without inventing calculation starts/completions. Final promotion: **3965 tests / 13 failures / 5 errors / 4 skips, non-PASS**. The two new assertions no longer fail. The revised installed witness completed with the same finite preset; prior successes remain evidence for their own commit.


## Semantic deployment and provider ID compatibility

Commit `123249a1`, run `p7-live-20261005220059-e0dee5c6d0794ad0a9db563d`: fresh SP80 Level 1→2 **PASS, 16 actions, five semantic revisions**, sealed/replayed/cleaned. The actual trace contains initial hypotheses, action counterexamples and revised rules, including a retained/reconsidered model at level changes. This proves the semantic revision/action path. It still records zero actual IPython cells.

A revision reported unavailable computation. Local Pi Responses source constructs `call_id|item_id` and passes it unchanged to tool execution; the packaged IPython bridge rejected `|` before wire dispatch. An isolated real socket bridge reproduced that rejection, while a method call with a composite ID and an IPython call with a simple ID succeeded. The live run did not preserve raw native tool IDs, so its exact failed-call count is unknown. Zero live cells cannot establish a voluntary decision to avoid computation.

The narrow correction permits `|` without truncating or replacing IDs, retains the 256-character bound and rejects controls/whitespace, including a trailing newline. A real FD regression executes two consecutive composite IDs and tests malformed IDs with zero dispatch. Extension: **34 PASS / six external-Pi skips**. Resource synchronization completed; related Python checks completed: 19 PASS and one pre-existing empty-profile fixture error. That fixture now explicitly declares its provider and a fake environment credential; its four-test module passes. Both actual installed suites passed. Independent narrow ID review, lint and docs checks pass. Mandatory promotion after the ID fix:3965 tests/13 failures/4 errors/4 skips, still non-PASS. The old empty-profile error is removed. Fixed-ID deployed witness started from an empty state with the same preset.


Semantic run background console acceptance: actual export `/tmp/p7-semantic-real-console.html`, SHA256 `9d8f1d7106376ae1f4d3af32d6b0d2053f1ecfaaa980cafcaac9f6bd8c90a832`. Shipped JavaScript checked 41 exact historical event positions (five revisions, five task declarations, 15 plan events, 16 feedback), with zero JS errors/network requests; no future event leakage or invented computation. Selected-run HTTP replay, page and state returned 200; replay equals the exported complete event list. Two existing DOM and three HTTP tests passed. No Chrome was used; server/thread cleanup confirmed. Actual-root history listing `/api/runs` exceeded a five-second client timeout and is **not** a verified performance result. Full command record: `/tmp/p7-semantic-real-console-acceptance.md`.


## Final fixed-ID installed witness — 721c8ae5

`make asterion-prime-p7-level-witness GAME=sp80 LEVEL=2`, fixed 900-second console/guest preset and human-baseline action cap97. Run `p7-live-20261005221958-e3d73e5ff66547bc9a6ff731`, seed0, gpt-6.1-sol/openai-codex: **PASS, two completed levels, 16 primitive actions, zero RESET**. Five plans, four semantic revisions, three real successful IPython cells; zero bridge method failures. No Playbook, prior/replayed prefix or offline optimization. Terminal reason `level-completed`; this is two of six levels, not a whole-game WIN or ARC benchmark score. Sealing/replay/cleanup all true; guest unit `asterion-p7-97d27598e0054d489856b4febeef6744.service` is inactive/dead/MainPID0.

Actual console event chain:

- Revision4 starts with uncertain control/flow rules. Probe actions1–2 and real successful cells11→12,19→20 precede revision22, which records the 4-pixel motion step and a computed candidate alignment. Plan23→40 uses that exact revision. ACTION5 advances Level1, contradicting the predicted single-frame flow; the host stops the remaining plan on `prediction-mismatch`.
- Revision42 updates ACTION5 to whole-layout submission and reasons about the inverted three-cup Level2. Selection probe43→48 matches. Real calculation49→50 precedes plan51→77; actual actions9–16 match the proposed edits and complete Level2. Revision79 records confirmed selection/step/submit rules and the new Level3 layout without executing beyond the target.

This establishes actual computation, semantic WorldMap revision, prediction-bound planning, counterexample correction and natural two-level solving in one installed run. The actor described program search/branching geometry; this run exported no source/model artifacts, so the algorithm's exact source and reusable checkpoint were not separately audited. Persistent-kernel recovery remains provider-free verified only; cross-run program reuse, cold/warm improvement and broader games remain unverified.

Final extension test34 PASS/six external-Pi skips; related installed checks passed, historical fixture repaired with four PASS. Full promotion3965tests/13fail4error4skip remains non-PASS and stopped before its downstream wheel checks. Separate actual installed tests and this rebuilt guest witness establish their own narrower wheel/runtime boundaries. `make check` was not redundantly rerun after the failing full promotion; lint/docs separately pass.


Final-run background UI: `/tmp/p7-final-real-console.html`, SHA256 `817a7e7be75d2f854c4239d5e3ba67befa14ede7c89af3e271380b8ebe38cfa5`. One focused actual-export DOM test passed all45 historical positions: four revisions, four task declarations, three started/completed calculation pairs,15 plans,16 feedback. Started cards remain unfinished; completed cards show actual elapsed time and remove the unfinished marker. Zero JS errors/network requests. Actual selected-run HTTP replay/page/state200; complete replay event list equals export,zero provider/actions,server cleaned. Commands: `/tmp/p7-final-real-console-acceptance.md`. No repeated full DOM suite or historical-directory listing.


## Persistent console and authorized continuation

User requested saving the solved baseline and continuing levels; exported HTML must not depend on a temporary directory. The sealed/replayed two-level run remains unchanged. Console export uses its existing default persistent output `.asterion-private/prime-p7-live/p7-live-20261005221958-e3d73e5ff66547bc9a6ff731/p7-console.html`; acceptance report/manifest are archived in that run’s `console-acceptance/`. A regenerated projection differs from the previous temporary export, so it is under fresh background verification rather than inheriting the earlier byte hash.

Next bounded scope is this same SP80 game through Level6 in one fresh verified run:900 seconds, baseline action cap518. The completed prior process cannot be resumed; the existing verified route starts a new environment and naturally carries its own computation/WorldMap through levels. No successful action prefix is injected. Full25 scope remains unapproved.


Persistent baseline HTML SHA435a67f77f297c0772f067e872778a3bdbb63f61af1b66353f04bfde54336969 passed a focused real DOM check (45 cursors,0JS/network). Comparison with the earlier accepted HTML finds only generated_at changed; run,levels,process events and revisions are identical. Both HTML variants and scripts/results are now in run/console-acceptance/. HTTP was not rerun for the persisted variant.

User then directed starting at Level3. The freshly launched LEVEL6 run `p7-live-20261005230820-7a8e491bcab640e8a11de01b` was stopped after two actions; cleanup true,guestinactive,summarycancelled/unsealed/unreplayed. That attempt is not solving evidence. Application continuation will explicitly select the sealed two-level source run, verify and restore its real pose into a new Broker, retain the verified research path and provide prior public rules as advisory. Restoration actions will be counted separately; this is warm continuation, not fresh solving.


Explicit saved-run continuation implemented: process-only `ASTERION_PRIME_P7_RESUME_RUN_ID`, strict exact source/model loader and validated historical WorldMap prose prior. `run_live` keeps verified research tools, restores via the existing real Broker before composing the first model request, and starts a new workspace requiring current-evidence revision. Budget16+421=437; restoration/new solver counts are retained in private summary.diagnostics, without expanding the closed public receipt. Source tampering, wrong model, missing prior or restore divergence refuse execution before model composition. No implicit fallback to best/fresh/legacy. Astra narrow implementation review passed.

Related command `uv run python -m unittest tests.test_prime_p7_resume tests.test_prime_p7_solutions tests.test_prime_p7_live_command tests.test_prime_p7_research_runtime`:117 tests PASS. Root separately validated the actual sealed source with the two external ARC wheels:exact source2levels/16actions,validated priorrevision3b41c983...,newtotalcap437. `make lint docs-check` passes. Installed regressions2testsPASS; mandatory promotion3971tests/13fail4error4skip remains non-PASS. Explicit warm Level3→6 model witness launched with fixed900s/cap437; outcome pending.


## Sealed warm four-level progress and persistent replay

Commit `aa5b6c84`, run `p7-live-20261005232533-2e9f20d6a7294d23bddf876a`: the fixed 900-second Level3→6 continuation reached four of six levels, then stopped without completing Level5. Actual restoration16 + new solving82 =98 primitive actions, zero RESET. The completed prefix stops at67 actions (16 restored +51 new:14 on Level3,37 on Level4); the other31 actions are the failed Level5 attempt and remain in the actual run history. Fifteen successful IPython cells, nine semantic revisions and eleven actor plans. Full target outcome unsuccessful; this is not a whole-game WIN. Partial trace sealed, completed prefix replay verified, cleanup complete; exact guest unit inactive/dead/MainPID0.

Persistent export is `.asterion-private/prime-p7-live/<run>/p7-console.html`, SHA256 `f1192d471d3590a67e91270728b7812125275657fc89e930e37b6513429f0b18`. Background DOM acceptance passes164 exact cursors, all15 actual calculation pairs, zero JS/network errors; selected replay/page/state HTTP200 matches the persistent projection with zero provider/action callbacks. Reports and scripts are in `<run>/console-acceptance/`. Summary partial replay verification is distinct from the export's full-target completion flag (false); neither the UI nor this review promotes the latter.

User requests background continuation with a two-unsuccessful-attempt limit per blocked level, then switching games. Level5 currently has one unsuccessful new-WorldMap attempt. The next finite attempt explicitly restores this four-level source and starts Level5; same900-second preset, cap67+96+152=315. No simultaneous guests or all25 sweep.

## 2026-10-06 console and local-solving update

Console implementation is recorded as targeted verified: fixed 25-game/183-level overview, exact WorldMap P7 filter for `gpt-6.1-sol`/seed 0, legacy dc22/vc33 history exclusion, per-game selection by progress/RHAE/fewer actions, whole-game denominator and unplayed zero. Explicit target/exact-source start, latest selected-game replay, pinned history cursor and read-only external-run following are implemented. Focused checks: Python overview 59 PASS, export 14 PASS, CLI 3 PASS, UI 85 PASS / 1 skip. The final actual static/export DOM acceptance passed 86/86 with 0 skips on persistent `replays/sp80.html`; command and log path are recorded in `docs/status/RESUME-NEXT-SESSION.md`. Root HTTP review and commit coordination remain pending.

The persistent controller’s canonical URL is `http://127.0.0.1:57515/`; do not promote idle legacy port 56659. The active process metadata is under `launches/`. SP80 run `p7-live-20261006001222-3a7662493aa44f01b109e5f9` completed 6/6 with 143 actions (95 restored + 48 new), RESET=2, receipt 100, seal/replay/cleanup true. Correct the earlier stale claim of RESET=0. Its local standing is 1/25 games, 6/183 levels, 4%.

User explicitly authorized sequential local solving over all 25 games: DC22 → VC33 → remaining catalog, skipping SP80, with one finite guest at a time. Switch after two failures on one blocked level; success resets the counter. This supersedes older statements that the 25-game work was unauthorized. Official submission and formal benchmark remain unauthorized. Exact-resume limitations remain: successful action prefix and advisory WorldMap text only, without failed-tail action/cell/kernel recovery; no high-probability claim for a retry.

Latest promotion is 3990 tests, 14 failures / 4 errors / 4 skips, non-PASS; one additional failure remains unclassified. See private `launches/p7-overview-promotion.log`. Do not characterize all failures as historical or repeat the full suite.


### DC22 interruption and one-time official submission authorization

DC22 run `p7-live-20261006002338-7fc5ecf2b7ca4c5e8a827607` stopped on `_CallbackRejected` (`prime-event-type`, `pi.prompt`): 14 actions, 0 levels, 5 cells; cleanup true, unsealed/unreplayed. This is a runtime interruption, not a solving failure. Do not relaunch before root repairs the run path. A zero-level failed-run experience reuse contract is not yet connected.

The user authorized one complete 25-task official submission after finite DC22/VC33 attempts, regardless of whether they fully solve. Pause remaining local games during submission; root records official score and channel, then resumes the rest. No repeated or open-ended livebench is authorized.
