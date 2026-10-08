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
