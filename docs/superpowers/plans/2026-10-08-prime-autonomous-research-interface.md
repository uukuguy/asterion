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


## Task 18 — User-directed DeepSeek V4 Pro direct BP35 comparison

User interrupts Flash and changes .env to deepseek-v4-pro. Stop/seal/clean the exact Flash trial, then directly launch fresh cold BP35 L1–L6 with current Pro/high and the already verified frozen wheel, no repeat r11l. Verify actual Pi identity before model work. New finite5400second launch window plus180cleanup; standard6round/1000paid/1024model/4096tool controls. Retain per-level comparisons and user preference to stop if L2/L3 show a large gap. Trial owner owns evidence/launch/cleanup; root owns stop decisions and state.

Task18 user-stopped: Pro L1 unfinished30paid,30usage,1109.028seconds through cleanup; committed effects known and cleanup receipt clear. No L2/L3 transfer assessment achieved. User restored .env to openai-codex/gpt-6.1-sol; effort remains high, no further trial authorized.


## Task 19 — Latest Sol medium BP35 verification

User authorizes one latest-version cold BP35 L1–L6 comparison against best1023.280seconds/221paid. Production766d71e0 includes generic RPC fixes, score guidance and env effort control; current operator.env explicitly openai-codex/gpt-6.1-sol/medium. Rebuild/install matching wheel, verify actualPi identity, then run5400second finite ceiling/6round/1000paid/1024model/4096tool plus180cleanup. No new r11l prerequisite (tool registry unchanged), no inherited game knowledge or actor hints. Root interprets “相差不大” initially as roughly20% elapsed overhead (1227.936seconds) plus no material action regression, not an execution cutoff or statistical equivalence claim. Trial owner owns private installation/launch/monitor/replay/cleanup; root tracks per-level against21/71/34/23/30/42, RESET0/2/0/0/0/0. Preserve console52024/56659.

Task19 target6 achieved234paid/3RESET/2103.806813seconds; action+5.9percent/time+105.6percent versusbest, so the near17minute acceptance is NOT met. Perlevel24/51/47/25/44/43; noouterhints/edits. Cleanup/sourceidentityPASS; independentfull234replayPASS. No furthertrial orscorepromptrollback authorized.


## Task20 — User-authorized scoring-guidance A/B

User agrees to one fresh BP35 L1–L6 after reverting only new actor scoring guidance. Restore build_autonomous_prompt and Solver actor budget projection to best9b62d2c2 semantics; retain score accounting/report calculations, all latestgenericRPC/schema/effort fixes and operator.env Sol/medium. No research hints, prior notes or changed controls. One new5400s/6round/1000paid/1024model/4096tool +180cleanup from actuallaunch. Direct BP35, no repeat r11l. Rebuild matchingwheel after focusedtests/review, actualPi identity and actor budget confirmed beforelaunch. Compare to current234/2103.807 andbest221/1023.280; not a statisticalcausalityproof fromonesample. Trial owner uses .asterion-private/p7-scoring-ab-sol-medium-bp35-20261008/trial/, waitsrootsourcefreeze/GO. Root ownsstate, no midrun changes.

Task20 baseline visibility clarified: actual autonomous9b62 context has nolevel_baseline; legacyfacade field is not actor-delivered. Restoring exactprompt/solver removes score-providedbaselines too. Do not add newbaseline-onlyguidance inthiscomparison.


## Task21 — User-authorized objective scoring information only

User proposes a fresh test with only objective scoring rules. Task20 continues unchanged through terminal/cleanup (no explicit cancellation). Prepare new code in isolated /tmp/asterion-p7-objective-score-20261008, preserving main runtime freeze. Keep original pre-scoring actor objective and all behavioral instructions unchanged; restore budget.scoring and add factual definitions/formula/cost accounting only. No fullscoreaspiration, planninginstructions, hardactionlimits or newcognitivegates. Retain latestgenericrepairs andSolmedium. Integrate only after Task20sourceverification/cleanup, focusedtests/review; then one freshcoldBP35L1–L6 standard5400+180bounds. No simultaneousprovider runs or inheritednotes. Trial owner waitsrootGO. This yields separate observations for no scoring, objective facts only, and previous facts+behaviorgoal; few samples do not prove statistically stablecausality.

Task20 userSTOPat4levels151completedpaid+10unfinishedL5=161total;full161replay/cleanupPASS. Task21objective-onlysource1a22dc33integratedaftercleanup,49testsPASS/rootnarrowreview; trialownerGO rebuild/launch freshSolmedium standardcontrols. No priornotes/hints.


Task21 CLOSED/independent PASS: source1a22dc33, actualSolmedium, cold sixlevels221paid/3deathRESET/1296.819519s; perlevel19/43/41/38/31/49. All221paid/223SDK fullreplay, sourceidentity/seal/cleanup verified; no hints/edits. Quality115/115/115/100/113.319459/115, partial9game46.666667. Same221paid vsbest but+26.73percenttime; versusTask19 -13paid/-38.36percenttime. Death costs23vsold31, success198vs190. Userrequests posttrialdeathRESETanalysis: allthreeautomaticverticalmotion, L2newmechanism/L3lossypurpleopenclosedrepresentation+jointmodel/L4crossviewpath+standposition. Canonicalcomparison holds ARC actual note evidence and generic/P7 layered improvement proposals. No new codefix or trial authorized; objective-only source remains current.


## Task22 — Approved transition evidence and research capability implementation

Spec: [P7 transition research design](../specs/2026-10-08-p7-transition-research-design.md). User says同意继续 after the concrete layered design. Root integrates and owns prompt/docs; p7_transition_impl owns research_bridge/research_runtime and focused transition tests. Review owner checks architecture and correctness independently. No concurrent actor trial.

- [x] Add focused failing unittest for r.transition(sequence): actual committed action, before/after refs and recorded animation descriptor; invalid/future/unknown reads rejected, immutable, no effect.
- [x] Run `uv run python -m unittest -v tests.test_prime_p7_research_transition` and observe missing-interface failure before implementation.
- [x] Implement through the existing read-only P7 bridge; preserve existing history/frame/animation and registered tool contracts. No Prime framework changes or game semantics.
- [x] Root updates build_autonomous_prompt with transition/animation examples, actual helper signatures, optional executable models and freely organized decision-useful NOTES. Preserve objective scoring facts and all action/budget boundaries.
- [x] Run transition, research runtime/observation and autonomous suites; independent code review; `make lint`, `make docs-check`, `make promotion-check`. TS registration/resource unchanged; run existing extension tests for deployment consistency.
- [x] Commit integrated source before a fresh packaged bounded `make asterion-prime-p7-level-witness GAME=r11l LEVEL=1`; verify exact wheel/resources/allowlist/cleanup, preserve console. Do not silently start BP35.
- [x] Record implemented/provider-free/packaged evidence separately; no claim death rate improved until separately authorized cold comparison.

Task22 source ready: new read-only helper exact refs/action/state/SDK animation descriptor, committed-only transaction guard and shared evidence lock. Focused RED observed before implementation; GREEN7 includes real persistent worker and pagination; adjacent36 and root18 regressions PASS. Independent review READY, TS50PASS/6externalPi skips, lint/docs PASS. No Prime generic code, registered tool, TypeScript or bundled extension changed. Promotion running; packaged witness pending, BP35 death reduction unverified.

Task22 promotion fullPASS commands25/provider_operations0/full_datasetno. Frozen sourceecd20b2f; deployment owner GO issued for fresh actual Make r11lL1 witness and isolated installed worker probe. No BP35 or actor hints.

Task22 packaged actualMake witnessPASS: r11lL1 coldSolmedium7paid/0RESET/70.642472s toSDKgoal. Exactfreshwheel/source/resource/three-tools, all7paid/9SDKreplay, seal/cleanup verified; realinstalledworker syntheticAPIprobePASS and actualmodeltop-levelr.transition(1) calledsuccessfully. Cleanup177.418283wall, consolepreserved. No newBP35; effectondeathrateunverified. FinalindependentauditPASS; manifest127files SHA804c9c8a519e8b3973e356135541304229181679120e593429e39e7cf7be5e17. Task22complete within implementation/deployment boundary.


## Task23 — User-authorized latest P7 cold BP35 verification

User requests README/AGENTS guidance updates, then the prepared cold verification. Keep Prime positioning as overall guidance; develop and stabilize first on P7. Update bothREADME languages/AGENTS beforelaunch; sourceecd20b2f remains frozen. No repeatedr11l, TS orpromotion (Task22 verifiedtheexactsameproduction). Current operator.env Solmedium, fresh isolatedcoldBP35L1–L6 withno oldNOTES/routes/hints. Original5400seconds+180cleanup,6round/1000paid/1024model/4096tool, norewal. Stopat6of9; modelmay naturallycontinue underoriginalbudget.

Trialowner notes_bp35_trial owns .asterion-private/p7-transition-sol-medium-bp35-20261009/trial/, install/wheel/sourcebinding, actualconfigurationpreflight, launch/monitor/fullreplay/cleanup. Root owns documentation/comparison; independentreviewer auditsprocesswithoutactorfeedback. Compare Task21 objectivefacts221/1296.819519s/3RESET (19/43/41/38/31/49), best221/1023.279883s, Task19fullguidance234/2103.806813s. Track perlevel totalpaid/successfulsegment/deathRESET/score/time, evidenceuse and actor modelprograms. Newhelperissupport; no death-ratecausalityclaimfromonesample.

Task23 ACTIVE2026-10-09T03:27:12.949955Z, exactrunp7-live-20261009032713-41edfbb078eaa7de208c454f/unite4749fe01fa84944a462674521e1dc86, fixeddeadline04:57:12.949479Z+180cleanup. SourceECD/HEADabf3/wheelce5f8f/installed584/configSolmedium verified; nooldresearch. Rootstatecheckpoint updated, trialowner running and reviewer read-only.


Task23 CLOSED: six levels203paid/1deathRESET/1420.864428seconds; perlevel21/43/36/25/37/41. Full203paid/205SDK replay, frozen source/install/seal and cleanup independently PASS. L6 authored settle+BFS,29,954states/20-step output exactly matched final actual actions. Fewer failures but slower than Task21 and best17minute; L5 score79.547114 remains regression. Canonical comparison records all boundaries; no further trial or source fix authorized.


## Task24 — Authorized discovered-problem fixes and cold verification

User requests design, implementation and verification with three-layer positioning. [Design](../specs/2026-10-09-prime-state-view-p7-action-preconditions-design.md), [implementation plan](2026-10-09-prime-state-view-p7-preconditions.md). Generic trusted stale-state model projection, P7 board-only replacement adapter, optional literal before.cells. L2 unknown hazard remains a measured research gap. Task24 private preparation ready, no provider GO until implementation/review/checks/packaged witness complete.

Task24 USER-STOPPED PARTIAL: source687c6fac packaged r11l L1 witness verified5paid/57.440s; cold BP35 interrupted4levels/229paid after L1/L2 regression. Independent1778-file/fullreplay/seal/cleanup audit READY; no L6 achievement. Root cause evidence and minimal repair are in the existing spec and canonical comparison.

## Task25 — User-authorized repair and cold restart

Sourcebc8f3f23 adds only P7 budget.scope source labels and short research explanation; generic state-view/registered tools unchanged. Scope ambiguity is supported; broad clearing and mistaken restore accounting are actor behaviors, not proved projection failure. Python40PASS/AstraREADY/lint/docsPASS; fullpromotion25PASS/provider0 and fresh installed preflightREADY. Root Task25 GO issued; Task25 ACTIVE2026-10-09T05:36:11.576714Z, runp7-live-20261009053612-8b560a4a5b55cad6803b08fb, unit1014b770e3c844c7852f9bf770a78b32; supervisor8945/launcher8947/caffeinate8946/session55378. Fixeddeadline07:06:11.576148Z+180settlement. Sourcebc8f3f23/wheeld64d/extension4fecd frozen; base .asterion-private/p7-task25-scope-sol-medium-bp35-20261009/trial/. Outcome pending; notes_bp35_trial monitors and finalizes. No inherited prior research or external rules. Trialowner prepares a new empty BP35 root with Solmedium and original5400+180 controls. No inherited NOTES/routes, resource threshold, outside hints or renewed deadlines. Root GO follows deployment readiness; monitor L1–L6 paid/success/RESET/quality/time and compare without causal claim from one run.

Task25 target achieved within original controls: sixlevels206paid/2deathRESET/1764.232393seconds;20/43/41/25/33/44. Full208SDK/206action replay, source/install/seal/cleanup ownerPASS; independent1848-entry audit READY/fullframes/source/cleanup. Quality110.25/115/115/115/100/115. Early interrupted-run regression recovers, but slower thanTask23 andbest17minute; scope wording causality unproven. No further model run or source modification authorized by this result.


## Task26 — Approved cache-compatible context and passive research records

Status: CLOSED / implemented and packaged deployment verified after user explicit “继续完成实现”; no repeat approval gate. Design follows the canonical Task25 analysis and D-2026-10-09-02. No cold BP35 is launched by this task.

Architecture: Prime owns opaque latest-state placement, numerical context accounting and evidence relationships. P7 research passively interprets real notes/program/plan/feedback milestones; P7 data supplies actual observation and transition references. No forced cognition, invented thoughts, strategy hint or altered scoring rule.

- [x] TS owner: reproduce prefix instability with a failing fixture; append the unique admitted snapshot after native history. Preserve native identity/order, tool pairing, custom-to-user role, recovery and compaction. Run real installed Pi conversion where available; unavailable external coverage remains external-limited.
- [x] TS owner: count four categories of model-bearing message JSON UTF8 bytes after owned context projections, with latest/peak/cumulative and at most1024 chronological samples. Report this as extension-hook bytes, not provider wire or token counts. Inject `ASTERION_PRIME_IPYTHON_CONTEXT_METRICS_FD` through the existing exact extension binding; use a private regular file, never stdout/stderr or the closed compaction witness channel. Failure leaves model messages/actions unchanged.
- [x] Root: generic Python owned metrics file, numeric closed-shape validation and finite read; P7 operator explicitly creates/injects/closes it and includes safe validated private summary. Cover redaction, invalid body, bounds and descriptor lifecycle with unittest before implementation.
- [x] Python owner: minimal generic private evidence-link recorder and passive P7 research milestone adapter, referring to existing source/output/notes/plan/observation evidence. Mark model statements versus behavior; causal meaning unknown unless explicitly supported. Capacity/failure visible, no duplicated raw log or mandatory model reporting. Cover source binding, failure/unknown outcomes and side-effect isolation.
- [x] Independent Astra changed-code review; resolve findings before deployment. Root syncs bundled extension; execute TS tests, focused Python tests, lint/docs and full promotion. Keep unchanged Rust historical failures distinct if encountered.
- [x] Commit reviewed implementation then one actual packaged finite `make asterion-prime-p7-level-witness GAME=r11l LEVEL=1` using operator.env Sol/medium, fresh state and existing900+180 controls. Verify wheel/resource/allowlist identity, passive artifacts, replay/seal/cleanup and user-console preservation. This is deployment verification, not BP35 speed or death-rate proof.
- [x] Commit evidence/state; retain outstanding full BP35 comparison and causal speed benefit explicitly unverified.

Ownership: context_impl owns TS source/tests; chain_impl owns generic/P7 chain Python modules/tests; root owns metrics-file Python, operator integration, bundled resource and docs; review is read-only. Workers do not revert one another. No protocol/manifest/tool registration changes.

Task26 final: sourcea919b496, promotion25PASS/provider0, fresh packagedr11lL1 fivepaid/zero deathRESET/79.490224s. Context8samples/86309Bpeak, chain7records including1acceptedNOTES (postgoal). Fullreplay/source569/install587/seal/cleanup verified; independent final manifest audit recorded in canonical comparison. No BP35 performance claim or new BP35 launch.


## Task27 — Latest context layout and passive research BP35 cold evaluation

User explicitly authorizes “开始实测”. One fresh BP35 L1–L6 using unchanged productiona919b496 and operator-owned.env model/effort. Deployment owner installs exact matching wheel and confirms resource/allowlist/runtime identity before launch; prior Task26 fullpromotion and r11l verification stand, no redundant provider trial. Original finite5400seconds plus180cleanup, sixlevels/1000paid/1024model/4096tool; no deadline renewal, inherited NOTES/routes, external solve hints or midrun source edits. Preserve user console52024/56659.

Track each level paid/successful actions, official capped score, death RESET, launch→goal time, chronological normalized input and extension-hook byte composition. Compare Task25 206paid/2RESET/1764.232393s and best17minute 221paid/2RESET/1023.279883s; successful steps below115 cap are not extra benefit. Macrochain separates actual model statements/program/action evidence; death assessment uses information available beforehand. Single-run differences do not prove caching causality or stable death-rate improvement. Private root `.asterion-private/p7-task27-cold-bp35-20261009/trial/`; launch identifiers pending owner.

Task27 CLOSED:203paid/one deathRESET/1644.981503s, six-levelpaid19/49/36/23/35/41 andQ115/95.960017/115/115/88.897959/115. Independent1824-entry audit READY; fullreplay/source/install/trace/metrics/chain/cleanup verified. Improvement versusTask25 is6.7594%time, but L2/L5score regress and best17minute remains60.7558%faster. Context history continues accumulating; weighted cache41.8226→19.3755%, so overall cache benefit unverified. Canonical comparison records risk-cue refinement and exact remaining investigation; no further benchmark/source change launched.


## Task28 — Stable state prefix and exact regional visual research

User authorizes design, implementation, independent review then actual evaluation. Active spec: [context and visual research design](../specs/2026-10-09-prime-context-prefix-and-p7-visual-research-design.md); execution plan: [implementation plan](2026-10-09-prime-context-prefix-and-p7-visual-research.md). Prime fixes reproduced moving-state placement using a trusted complete-tool-group anchor and records numeric actual provider-input prefix through public Pi event; no original archive/roles/pairing/cognition ownership changes. P7 data adds optional exact bounded patches, research guidance supports visual-risk hypotheses and representation cross-checks without fixed hazards/routes/mandatory forms.

Status IMPLEMENTING: P7 patch/prompt lane100PythonPASS + independent codePASS; Python prefix/operator lane15PASS + independent codePASS. FinalTS78PASS/6external skips and actualPi1.0provider-freePASS; finalPython85PASS, independent overall code reviewAPPROVE. FullpromotionPASS25/provider0 and freshr11lL1 deployment independentlyREADY105files; sixpaid/75.605709s, actualprefix7/7and19/19items preserved, rawcache unavailable. RootGO for fresh BP35L1–L6 issued; actualcoldreceiptpending. Deployment prepares separate fresh r11lL1 then BP35L1–L6 with existing finite controls/operator.env, after root sourcefreeze and GO; no repeated userpermission necessary.

Task28 targetcomplete:236paid/two deathRESET/1069.976586s,18/62/36/23/31/66paid andQ115/59.937565/115/115/113.319459/115. Compute35/35fullprefix/cache98.9263% restorespriorlane; actioncache6.5523%/historygrowth and two avoidable-risk candidates remain. Full238SDKreplay/236trace/seal/source569/install587/cleanup verified; finalmanifest1909entries independentREADY/SHA7de0df3782979d893a3fe4b1bfb9fab168d49783ec989f73e2d55333ca96c762. No activeactor, no additionalfix/run initiated.

## Task29 — Dynamic settled-observation boundaries

User authorizes design+implementation and directlyrelatedthree-layerdefects. [Design](../specs/2026-10-09-p7-observation-boundary-design.md), [plan](2026-10-09-p7-observation-boundary.md): objectiveboundedpixeltranslationcandidate, defaultsoftyield/actoroptout/optionalcheckpoint, hardRESET/terminalpriorityrepair. ExistingPrime lifecycle reused; no newBP35. Implementation/review/deploymentpending.

Task29 CLOSED:reviewedimplementation9557ad63/defaultsoftyield+actorcheckpoint/RESETpriority/cappedfeedback fixes. TS79PASS/6external skip/Python142PASS/promotion25PASS/provider0; actualpackagedr11lL1sixpaid/104.040866s/zero paidRESET, fullreplay/identities/cleanup and110entryindependentauditREADY. Installedsyntheticnewboundaryverified; naturalwitnessno boundary; no newBP35effectclaim. Standalone [Task29 review](../../reviews/2026-10-09-p7-observation-boundary-review.md).

Task29 subsequent user-authorized cold BP35 evaluation CLOSED:211paid/zero deathsRESET/1548.246660s; paid25/42/36/24/30/54,Q70.56+five115. All213SDKreplay/211tx/312trace/source570/install588/cleanup independentlyREADY; manifest1836entries/SHAe5d936b2e62a47b7a97174998486c5dd936f3dc06466a7e06d65e923e23fc2df. Naturalsoftyield0:36candidates/26laststep/10suffixalloptout,9optoutplans. Stable safety/automaticyield efficacy unverified; time+44.70% versusTask28. See [standalone current evaluation](../../reviews/2026-10-09-p7-bp35-task29-evaluation.md). No further run or implementation initiated.

## Task30 — Resource-aware autonomous research

User authorizes design+implementation after dynamic active/conservative strategy clarification. [Design](../specs/2026-10-09-prime-resource-aware-research-design.md), [plan](2026-10-09-prime-resource-aware-research.md), freeze4e848873. Genericdateddeadlinefacts+guidance, P7conditionalscorefacts, trustedfirstJSONtoolcompletionresources withoutmovingfullmemoryprefix. No fixedstrategy/scoregate/origininference/newFD. CLOSED: source26250c0e,191Python/79TS/fullpromotion25PASS, fresh packagedr11lL1 4paid0RESET67.896532s, independentREADY. ActualPi receipt/adoption and BP35strategy effect unknown. Task31 direct115/100remaining/exceeded facts implementedba51c62e/48tests/fullpromotion/newr11l6paid0RESET94.471582s; final115manifest independentREADY, CLOSED; no newBP35authorized.

## Task32/33 — Interrupted comparison and contemporaneous decision records

Task32 cold BP35 stopped by user afterL1:22paid/Q91.1157/167.713005s, L2partial16paid/deathRESET1, total38paid; fullSDKreplay/seal/cleanup and395manifest independentREADY. [Analysis](../../reviews/2026-10-09-p7-bp35-task32-interrupted-analysis.md) separates concrete route changes, risk nonapplication, model timing and causality limits.

Task33 user requires initial and materially changed game strategy reports plus concise action/group reasons. Implemented P7prompt using existing NOTES and goal; changedcodeAPPROVE/root35tests/lint/docs, no hostgate/schema/generic or data additions. Source-only verified, not new live adherence/effect; no further run authorized. Sameresource-aware [spec](../specs/2026-10-09-prime-resource-aware-research-design.md) and [plan](2026-10-09-prime-resource-aware-research.md) amendments.

## Task35/36 — Scarcity and opening strategy, closed with negative quality result

Task35 b2d1a453 explicitlyprioritizes informedprogressunderscarce score/time: coldL120paid/Q110.25, resources referencedinactualgoal, authorizedearlystop/final304manifestREADY. Task36 latestproduction94dabe66 adds initialroute/exploration judgmentbefore paidprobe: 23tests/APPROVE thenfresh packagedcoldBP35L124paid/Q76.5625/247.167053s,L2none;26SDKreplay/280manifestindependentREADY/ownedcleanup. Initialdecisionreported butclearall14notlinkedtoobjective; wholeanimationprint65536B causednextinput30946→86730. [Evaluation](../../reviews/2026-10-09-p7-bp35-task32-interrupted-analysis.md) includesexactstop/usage/cache boundaries.

Task36CLOSED: recordcontractsimplemented/deployed, qualitynotimproved. Noactiveactor orautomaticnexttrial. Furthergoal-causality/outputorganization work remainsdesign-only; Primegeneric/P7research/P7data responsibilities mustremainseparate. FollowcurrentRESUME fornewuserintent, notolderTask33/35 runauthorization.

## Task37 — Unchanged-version L1 repeat

Userauthorized singleBP35L1 repeat, no productionchanges: same94dabe66/wheelbbf153/Solmedium/seed0/freshhistory/native6/5400+180 actorinputs. External private identity-checked watcher stops after knownL1goal, no19gate. Result21paid/Q100/0RESET/161.361755s, L2paid0; Task36sameversion24/Q76.5625/247.167053s. Earlier route-related mechanism update and bounded animation output differ; two trials demonstrate variability, not promptcausality orstability. 23SDK replay/21knowntransactions/40trace/14researchrecords verified; final258manifest fd2d6ae8 independentREADY/ownedcleanup. Task37CLOSED. Usernewquestion revealedactual autonomousinterface lacksstandardACTION1–7 priors (legacy mappingnotdelivered). Domaininterface/research improvementremainsnotimplemented; noadditionalrun authority.

## Task38 — Revisable action interface priors

**Goal:** Deliver known ARC interface conventions to the actual autonomous actor, keeping hidden game mechanics model-owned.

**Architecture:** Only P7 research prompt; Prime generic services and P7 data/contracts remain unchanged. No game route or forced probe. Design is the Task38 section in the existing resource-aware research spec.

- [x] Add focused prompt-delivery test for all7actions, revisable prior, ACTION7/RESET distinction and GAME_OVER boundary; observe missing-content failure.
- [x] Add short mapping paragraph to `build_autonomous_prompt()` in `src/asterion/applications/prime/p7/prompt.py`; run `uv run python -m unittest -v tests.test_prime_p7_autonomous_interface`, Ruff/diff and independent changed-code review.
- [x] Commit source and documentation; run `make promotion-check` and freshwheel installed prompt probe, checking source/prompt/resource/tools match.
- [x] Record implemented vs provider-free verified vs model-quality untested boundaries; close checkpoint. User subsequently authorized fresh BP35 L1–L6: exactSolmedium/seed0/native6/5400+180, preflightREADY/rootGO, no inheritedknowledge orL1stopper/19gate; prioritize L1 comparison and monitor each level.

Task38CLOSED: source8e2e8a29/packagingverified; freshBP35target6 naturalexit0/215paid/zeroRESET/1482.657593s, actualofficial9levelpartialscore46.666667. Final1908manifest3cebc44d independentlyREADY/217SDKreplay/ownedcleanup. Evaluation containsL1interfaceadoption, L2/L6undocorrection, L5time/cache and goalvsfinalusage. NewNOTES-primarydesigninvestigation followsuserexplicit cognition/history concern; no newmodel trial orcontextsourcechanges.

## Task39 — Normal NOTES primary cognition, selective evidence retrieval

User explicitlyauthorizes implementation/simple review/coldBP35. [Design](../specs/2026-10-10-prime-notes-primary-context-design.md) changes ordinaryacceptedNOTES toprimaryworkingbaseline, noadditionalmodelcheckpointswitch. Prime TSworker owns genericarchive-reader/selection/completegroupcursor/v3receipt/projection/compaction+cache; Pythonworker owns genericenvelope/domainbindings/P7cognitionprompt/workspacemetadata; root integration/docs, independent review beforepackage/GO. No productioncodeuntildesignAPPROVE.

- [x] Agree Python/TS v3 envelope and appworkspace native-read contract; addfocused RED tests foractualselectedbranch reads/unknown/group/sibling boundaries andordinarynotesepochs.
- [x] Implement read-by-ref first, thennotesautomaticepoch projection, preserveactualcurrentfacts/programgeneration/userconstraints/errors/refutations/unknowns; epochappend andcompaction/reload semantics. No blindbytewindow ornewtool.
- [x] Explain richerfreeNOTES andimportantcounterexamples inactualP7prompt; syncschema/registration/allowlist/buildresource/bridge, focusedtests+simplechanged-codeAPPROVE.
- [ ] Sourcecommit; TS→relevantPython→promotion→necessaryrealpackagedsmallwitness forapptoolchanges; independentlypreflightREADY freshBP35/Solmedium/seed0/native6/5400+180, rootactualGO.
- [ ] Trackeachlevelpoints/paid/deathRESET/time, acceptednoteepoch/inputpeak/rawcache/refretrieval/programcontinuity; fullSDKreplay/seal/cleanup/finalREADY. Don'tpromote optionalAPIorunittest toNOTES-primary ability.

### Task39 补齐：Prime 统一接入与默认专用摘要

用户继续授权，并明确覆盖 P7 全部 Pi 依赖。NOTES 核心提交2930fbd8；本补齐完成后统一打包验证，不先启动旧接入版本。

- [ ] deployment 列出 P7 live/operator/runtime_binding/official_operator/run_story 内全部底层启动、配置、profile/entry、RPC、extension、事件依赖；迁移到 agents/prime 的真实通用接口，领域完成判定和证据转换保留 P7。
- [ ] context_impl 与 deployment 对齐默认 session_before_compact 摘要、有限调用授权/结算、失败/取消、持久化范围及 P1 兼容合同；review 独立设计 gate。沿 Pi 阈值/preparation/persist，不修改外部 Pi，不新增 runner/provider。
- [ ] TS focused RED→GREEN 验证实际选定 registry 请求使用自有代码语义材料、最多 main/prefix 两调用、信号与真实 usage、未知/错误保护、NOTES 范围与压缩重载。Python focused RED→GREEN 验证 callback/deadline、实际usage不双记、P7只调用Prime接口、错误与清理。
- [ ] 简单独立 changed-code review，通过后同步打包扩展并提交；按 TS→Python→promotion 顺序验证，记录跳过及未实测边界。
- [ ] fresh wheel 与真实打包小关验证同一扩展及工具版本，再按已授权 Solmedium/seed0/native6/5400+180 冷测 BP35，持续跟踪分数、动作、RESET、时间、NOTES epoch及输入tokens。
