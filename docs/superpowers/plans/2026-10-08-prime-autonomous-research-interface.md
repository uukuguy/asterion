# Autonomous research interface implementation

Design: [contract](../specs/2026-10-08-prime-autonomous-research-interface-design.md). Previous [NOTES package](2026-10-08-prime-research-notes.md) is closed with failed BP35 comparison evidence.

1. **Historical implementation — generic context projection (superseded by Task7).** TypeScript owner implements capacity-triggered complete-message retention, trusted state without notes, optional plan metadata, tests and bundled resource.
2. **Implemented — P7 research autonomy.** Solver/Broker owner removes cognitive admission gates only for the modern autonomous profile, preserves true authority checks and adds pure observation helpers. Root integrates read-only research discovery, concise prompt and trusted state refresh.
3. **Implemented — execution settlement.** Deadline owner implements generic dual-clock deadline, SolverControl/SDK adapter integration and small durable action journal. Root and Broker owner wire the same budget, journal, guest origins and minimal finalization receipt.
4. **Verified — review and bounded deployment.** Review changed implementation, run TS then relevant Python tests and promotion; deploy one finite packaged r11l L1 witness. Record actual evidence and limits; do not claim BP35 improvement without a later comparison.

Ownership: root owns research_runtime.py, research_bridge.py, actor_projection.py, operator.py, prompt.py, launcher/packaging and state docs. Parallel workers own disjoint files listed above; no worker reverts another's changes. All implementation remains subject to integration review.

Changed-code review READY; TS48pass/6existing skips, real installed-Pi probe provider-free PASS, focused Python343tests/1existing skip, targeted Ruff PASS. Final-source full promotion PASS25commands/provider0; replacement packaged r11l L1 PASS3actions/0NOTES/64.865s, replay/seal/cleanup verified; prior private observer failure preserved separately; see [review](../../reviews/2026-10-08-prime-autonomous-research-interface.md).

## Task 5 — User-authorized BP35 comparison

**Status:** measurement closed, target NOT achieved. Frozen6ca run ended after about34minutes with2levels/166committed; L3unfinished. Projection diagnostics exceeded64KiB Pi RPC stderr quota, before5400sdeadline. L2 independently regressed to126paid versus47/74/48 baselines; its final route remained40steps. Completed150action prefix replay and sealed166action trace, identity and cleanup verified. No production edit or retry; see the comparison below. Implementation/deployment above remains verified only in its stated boundary.

Use frozen production6ca76ca4/gpt-6.1-sol high/seed0, empty isolated state, the prior5400s/6round/1000action/1024model/4096tool controls and180s fixed settlement. No old solution knowledge, outside game hints or midrun code repair. Stop at six levels or the existing termination/budget boundary. Audit outcome, per-level research/action cost, context behavior and cleanup against the fixed ARC/old-P7/NOTES baselines. [Trial evidence](../../reviews/2026-10-08-p7-autonomous-bp35-comparison.md).

## Task 6 — Bounded diagnostics and medium effort (intermediate; superseded by Task7)

User requests concrete repairs and asks whether P7 should use medium/low effort. Implement the directly proven telemetry defect with one shared4KiB UTF8 diagnostic budget including suppression, keeping the RPC64KiB guard. Change only P7's fixed thinking setting high→medium, not the generic runtime/defaults. ARC actually usedhigh; medium is a new intervention, not a proven root-cause fix. Keep context retention/NOTES/source APIs unchanged in this small package so effort is not confounded with a new memory design.

Acceptance: regression reproduces changing-outcome and exception log overflow, projections remain intact, TS/resource + related Python + promotion pass, one finite packaged mediumr11lL1 deployment witness. No BP35 rerun. Current-source retrieval and knowledge continuity remain a distinct unimplemented follow-up, described in the comparison.

### Layer ownership reaffirmed by user

| Concern | Owner and boundary |
| --- | --- |
| Diagnostic budget | Generic Prime extension diagnostic facility; P7 memory hook uses it. Keep runtime stderr guard separate. |
| Current computation source/results/errors and dynamic definition retrieval | Generic computation/kernel facilities; narrow bounded read APIs. P7 consumes them without importing game knowledge into Prime. |
| Complete interaction retention and compaction/recovery coordination | Generic context/session lifecycle. No game ids, board rules or level semantics. |
| Stable mechanics, counterexamples, current-level plan, old-level detail retirement | P7 adaptation/prompt and model-authored notes. Generic memory stores opaque content; host does not decide game truth. |
| Thinking level, target level and experiment budget selection | P7 operator policy. Generic runtime accepts the exact injected configuration and execution budget. |

This user constraint governs the separate source-retrieval/context follow-up. Current Task6 changes only diagnostic budget and P7thinking; it does not imply the broader follow-up is implemented.

## Task 7 — Implement usable computation history and context continuity now

User explicitly rejected stopping after Task6 packaging. Task7 must be implemented before the next packaged verification. Task6 promotion on cbeddf3f passed but does not verify this expanded package. No small witness has launched.

### 7A Generic computation (kernel owner)

Files: `agents/prime/ipython.py`, `ipython_worker.py`, a focused `cell_history.py`, and generic kernel tests. Automatic private current-workspace cell archive, full admitted source and real bounded worker output/status; no automatic replay/export. Public-safe failures remain codes; private read returns actual content. Source remains available after ordinary Python errors and kernel replacement in the same workspace. Unique virtual filenames and linecache make inspect.getsource work for current and older function references.

Interface: `PersistentIpythonHost.cell_history(start=0,limit=16)` returns items/start/next_start/total with stable `cell:<sha256(generation,call_id)>` identity, ordinal, generation, status, source_bytes, output_bytes, output_available/output_truncated and export ids. `cell_read(cell_id,field='source'|'output',start=0,limit=4096)` returns metadata plus text/character offsets; page maxima64items/16384characters. Storage under injected workspace/cells, atomic/thread-safe, no cross-root paths. Existing16KiB source/64KiB worker output apply. Host limits bound records/serialized storage (16384/2GiB defaults); capacity refusal occurs before execution, never silent eviction. Archival failure after execution must preserve real execution outcome and mark readback unavailable. Tests cover real function introspection, failed result/source retrieval, pagination, kernel recovery, independent scope and pending/limit semantics.

### 7B Generic context (TypeScript owner)

Files: `context-memory.ts`, hook compatibility in `ipython-extension.ts`, tests/installed-Pi probe and packagedresource. Remove96/48KiB rolling deletion. Replace only owned synthetic snapshot; all real native messages, tool sibling groups, instructions and native compaction/branch summaries remain in original order. Native Pi manages compaction. Preserve trusted v1/v2 admission and4KiB diagnostic budget. Output truthful private metrics; remove unsupported window-count metrics. Tests use >96KiB history with0NOTES, committedNOTES, pending tools and native summaries; raw evidence and all real model-visible messages must remain intact.

### 7C P7 adaptation (root)

Files: `research_bridge.py`, `research_runtime.py`, `prompt.py`, P7 read/runtime integration tests. Add only read-server routes `cell_history` and `cell_read`; callbacks delegate to current generic kernelhost. Expose `r.cell_history(start=0,limit=16)` and `r.cell_read(cell_id,field='source',start=0,limit=4096)` in the existing injected module, no new registered action tool. Reject invalid ids/field/bounds before callback. Source/result content stays private and readonly; querying never dispatches an environment action.

Prompt explains automatic code/result history and direct function source inspection; encourages concise verifiedmechanics/counterexamples/uncertainties/currentplan notes, revise after informative surprises and retain reusable knowledge across levels. No mandatory schema or note-before-action gate. Explain native compaction and independent notes retention accurately; do not promise arbitrary kernel objects survive restart.

### 7D Integration/acceptance

- [x] Kernel and TS focused regressions pass; P7 real subprocess test defines helper, reads source/result through injected API, recovers explicit state and re-reads prior archive without an action.
- [x] Independent changed-code review across generic/application boundary, lifetime, read scope, truncation and post-execution failure semantics.
- [x] Final TS, related Python, promotion, then one actual packaged mediumr11lL1 witness, with exact resource/source identity and cleanup. No new BP35 trial in this package.
- [x] Commit implementation and evidence, update state; report implemented continuity separately from unmeasured BP35 improvement.


Task7 result: production9b62d2c2, core-install allowlist fixa4003544. TS49PASS/6existing skips; relatedPython119PASS; core-install4PASS; independent reviewREADY; finalpromotion25PASS/provider0. One packaged mediumr11lL1 PASS5paid/0RESET/2successfulcells/0NOTES, SDKpass85.099s afterhostMake, cleanup91.089s. Automaticarchive2records observed; readback/recovery and >96KiB continuity covered by provider-free real-kernel/Pi tests, not claimed as live actor use. Replay/seal/identity/cleanupPASS. See [updated evidence](../../reviews/2026-10-08-p7-autonomous-bp35-comparison.md). BP35 improvement remains unmeasured.


## Task 8 — User-authorized review and frozen BP35 comparison

User requests rechecking Task7 design/implementation against requirements, then running BP35. Review concrete generic computation/context/P7 boundaries and deployment identity; fix only evidence-backed blockers before freeze. Once READY, run one coldsol/medium BP35 L1-L6 with existing5400s/6round/1000action/1024model/4096tool and180s settlement bounds. No old knowledge, external solve hints, production hotfix or retry. Track per-level paidactions/RESET, cells/errors/readback, NOTES, usage and naturalcontinuation with explicit evidence completeness. [Current comparison](../../reviews/2026-10-08-p7-continuity-bp35-comparison.md).


Task8 completed: re-reviewREADY,32/33overlapping targetedtestsPASS, no newproductionchanges. Frozen medium BP35 L1-L6 PASS221paid/2RESET,21successfulcells,3acceptedNOTESwrites660–1074B;1023.280s toL6SDKpass. Full221replay/seal/identity/cleanupPASS. One completednaturalroundrecorded, fullcompactioncountunavailable. See comparison for perlevel costs and multi-intervention limitations.


## Task 9 — User-authorized low-effort comparison

Change only P7 application thinking medium→low; generic defaults/prompt/context/tools remain frozen. Run one fresh BP35 L1-L6 with exactly Task8 seed0/modelsol/budgets/cleanup and no inherited game knowledge, external solve feedback, hotfix or extra retry. Compare against Task8 medium221paid/2RESET/1023.280s/21successfulcells/3NOTES. First verify command selection with a failing-low regression then focused checks; inspect rebuilt wheel/installed low setting and unchanged extension identity. This is an effort selection change, not a resources/protocol change; prior full promotion remains historical, focused114tests and exact newwheel identity verify this narrow delta. Report individual-run evidence, not statistical proof; default choice remains subject to outcome.


Task9 complete: low231paid/2RESET/1968.197s target reached,15successfulcells,3NOTES; all231replay/cleanup/sourcefreezePASS. Actionefficiency modestly worse thanmedium221, elapsed~1.92x; no single-run statistical/latency attribution.

## Task 10 — User-authorized same-version high comparison

Afterlowclosed, change only P7 effortlow→high, retain Task7 code/prompt/bundle and identical coldBP35L1-L6 finitecontrols. Newsource/wheel/installedidentity +focused114tests; thenonefrozenrun, no outsidegamehelp/hotfix/retry. Compare medium/low/high on sameimplementation, unlikeoldhighfailures. Preserveconsole52024/56659 and ordinarycleanup/evidenceboundaries.


Task10 attempted/external-runtime-limited: highL1PASS24paid/0RESET/235.379s, thenmodel_rpc_error after nativeautoretry, target6NOTachieved.24actioncompletedprefix replay/seal/sourceidentity/cleanupPASS. Errorbody/statusnotpersisted, no causalclassification beyondnative transientprovider/transport retrycategory. No additionalprovidertrial. Restoremediumdefault afterhighcleanup;114focusedtestsPASS, production`src`exactlymatchesverified9b62d2c2. This doesnot close highabilitycomparison asPASS.


## Task 11 — Explicitly authorized second high trial

User explicitly requests high again after the request-interrupted firsthigh. Use exactlya7cf5826 production (onlyefforthigh), retained verified highwheel, newcoldroot/unit/run, same5400s/6round/1000action/1024model/4096tool+180cleanup. Priorhigh evidence stayssealed; no oldnotes/routes injected, no productionfix/newinstrumentation, no unrequestedthirdattempt. Current114focusedtests and exactsrc equality topriorhigh plus newinstalledidentity cover unchangeddeployment. Finish goalL6 orfiniteboundary thenaudit/cleanup/report.


## Task 12 — Authorized score-aware autonomous planning (isolated preparation; integrate after Task11)

User approves supplying the actor with target levels, baselines, scoring rules and full-score conditions so it can plan for task value itself. Do not add per-level action cutoffs or mandatory reasoning, notes, prediction or search steps. Task11 production and actor inputs remain unchanged until its terminal evidence and cleanup are confirmed. Prepare implementation and provider-free tests in an isolated worktree while it runs; integrate only after cleanup.

Use the existing generic application-context delivery and trusted total-budget enforcement. ARC-specific objectives, baseline metadata, level accounting and scoring belong in P7; do not introduce game fields into generic runtime contracts or a second tool-registration path. The minimal implementation is P7 autonomous instructions plus compact trusted current-state feedback through Solver and the existing research snapshot.

The user clarified that the stable actor objective is always the full game and its maximum score. Tell the actor all game levels, all available baseline values, the scoring formula and completion cap. Treat the selected target_level as the operator execution stop boundary, not a replacement task objective. Per-level q_i=min(115,100*(b_i/a_i)^2); full-game contribution uses weights i and denominator N*(N+1)/2, capped by completed weight / total weight *100. Baseline is a100-point reference, not an optimal route or hard limit. Full-game100 requires alllevels. BP35 has N9; a stop after K6 currently caps recorded contribution at46.666667, but this is not the actor objective. Plan for complete-game100 and obey the operator stop atL6; later authorized continuation retains knowledge, progression and paid costs. Do not automatically extend budgets, reset accounting, continue beyond an active stop boundary or restart the fullrun for score.

Feedback should provide completed-level paidcounts/scores, current-level paidcount including failedattempts and RESET, currentbaseline and remaining global controls. Successful-episode counts must never replace total paidcounts. Alreadyspent actions remain charged after RESET. Unknown/uncertain effects must retain existing failclosed execution semantics rather than invent a score. Supply concise objective facts; leave exploration, calculation, route choice and knowledge maintenance to the actor.

In the isolated worktree, verify exact authoritative accounting source and score consistency; implement focused boundary tests for leveltransition, RESET accumulation, initialreset exclusion, targetvsfullgame and baseline100/levelcap115. Review code and context delivery; run relevant tests and applicable packaged verification. New BP35 scored-policy comparison is not silently included in the existing high2 authorization.


Task11 completed: high2 L1–L6 PASS262paid/2RESET/4409.249s, full replay/source/cleanup verified; no trial active. Task12 isolated61951178 integrated as851ee071 aftercleanup; related94tests/finalprojection22tests/independentreviewREADY, provider-free wheel install and scoreprobePASS. Newpolicy gameplay not yet measured; arbitrary crosssession continuation not added.


## Task 13 — Authorized score-aware medium BP35 comparison

User explicitly authorizes one fresh BP35 L1–L6 trial of the integrated score-awareness change and requests per-level process comparisons. Freeze production e869a3dd (scoring851ee071 plus medium default); build a new medium wheel, do not use isolated Task12 high wheel. Same seed0/sol/5400seconds/6rounds/1000paid/1024model/4096tool+180cleanup. No prior notes/routes, outside solve hints, midrun source/prompt edits or extra attempt. Full-game/100 objective and all scoring facts remain stable; operator stops afterL6. Preserve console52024/56659.

Trialowner notes_bp35_trial owns fresh privatebase .asterion-private/p7-scoring-medium-bp35-20261008/trial/, coldroot, installedidentity, exactrun supervisor and finalreplay/cleanup. notes_bp35_review observes only, reporting eachlevel vs oldmedium (21/71/34/23/30/42,221paid/2RESET/1023.280s): totalpaid, failed/RESET/successful episode decomposition, exploration/model/route differences, NOTES revisions, scorefact usage evidence and timed compute versus unclassified waiting. No feedback toactor. Root owns docs and finalintegration. One sample cannot establish causal or general improvement.


Task13 closed external/runtime-limited: fivelevels168paid, L6unfinished16paid, modelRPCfailure. Full184sealed, replay168completedprefix, identity/cleanupverified; no furtherretry.

## Task 14 — Authorized DeepSeek Flash / high comparison

User requests one deepseek-flash/high BP35 trial. Keep integrated score-aware P7 logic/prompt/tools unchanged, switch application thinking tohigh and use operator-owned provider/model binding after verifying exact Flash API identity and high mapping. Existing .env has credential; do not expose secret or persist experiment overrides. Fresh coldL1-L6 seed0,5400s/6rounds/1000actions/1024model/4096tool+180cleanup from actuallaunch. No oldknowledge/hints/hotfix/extraattempt; preserve console52024/56659. Trialowner notes_bp35_trial owns .asterion-private/p7-deepseek-high-bp35-20261008/trial/ and newinstallation; verify SDKimports/full dependency set, wheel/source/installed identity, actual Flash notPro, thinking mapping before launch. Root owns onlyhigh config anddocs; prior scoringmedium failureevidence remains separate. Perlevel compare against oldmedium and scoringmedium prefixes, do not attribute model+effort change tosinglefactor.

Task14 CLOSED external/runtime-limited: exactdeepseek-flash/high confirmed offline andactualmodelidrecorded; firstpromptRPCfailure,0paid/1zerousage,cleanup/sourcePASS. NoHTTP/body/stopReason retained; noabilityresult oradditionaltrial.


## Task 15 — Explicitly authorized DeepSeek continuation with private failure capture

After current.env→actualPi get_state and a bounded API request both pass, user explicitly says continue. Run one fresh DeepSeek Flash/high BP35 L1–L6 under unchangedscorepolicy/sourcec33, samefinitecontrols5400s/6round/1000actions/1024model/4096tool+180cleanup. Newbase .asterion-private/p7-deepseek-high2-bp35-20261008/trial/. No inheritedknowledge/actorhints/hotfix. Beforelaunch add only run-private transparent failureevent observation so another failure yields evidence: byteidentical stdout forwarding, bounded600privatefailurefields, no normalprompt/content/headers/credentials, no changedcompact_events/context. Trialowner implements/preflights; reviewowner verifies synthetic forwarding/failure/limits/cleanup. No productiondiagnosticframework refactor inthistrial. OnceREADY launch directly; if failure diagnose exactcapturedcause, no blindextraattempt. If running continue perlevelcomparison. Preserveconsole.


## Task16 — User-authorized generic RPC diagnosis and safe recovery

See ../specs/2026-10-08-prime-rpc-failure-recovery-design.md. Isolated worktree /tmp/asterion-rpc-diagnostics: rpc_failure_diagnostics owns typed/private failure infrastructure; rpc_recovery_contract owns recovery contract/session execution and P7 admission after interface coordination. Main production remains frozen for Task15. Focused redaction/effects/deadline tests and independent review; integrate only after live source seal/cleanup. No automatic extra full trial.


Task16 implemented: generic schema normalization, private typed failure capture and bounded same-session recovery integrated through c5f8e71a. Independent review READY; TS50/Python165/lint/docs/promotion25 PASS. First packaged witness installed identity and IPython observation PASS, but confirmed host sleep caused deadline cancellation before game actions. Full witness NOT PASS.

## Task 17 — Continue repaired DeepSeek packaged verification and BP35

User explicitly says “改完了就继续” after the sleep-interrupted run. One fresh 5400-second task window covers Make r11l L1 (at most900seconds) then independent cold BP35 L1–L6 using the remaining task time, plus180seconds cleanup. No automatic deadline renewal. Frozen production c5f8e71a, documentation HEAD46e087ed; DeepSeek Flash/high from operator .env. Existing6round/1000paid/1024model/4096tool limits remain. Trial owner notes_bp35_trial owns fresh private evidence, installation identity, launch, monitoring and cleanup; review owner observes per-level comparisons without actor feedback. No production changes or prior game knowledge transfer. Preserve console52024/56659. Host power assertions are checked without changing system power settings.
