# Task29 Observation Boundary Implementation Plan

> **For agentic workers:** Use subagent-driven-development for separate ownership and independent spec/code review.

**Goal:** Return settled observations at informative batch boundaries without automatic suffix execution.

**Architecture:** Existing Prime tool/continuation/admission are reused. P7 puredata reports bounded pixeltranslation candidates; autonomous Solver chooses softyield or actorcheckpoint, preserving all hardstops and committed evidence.

**Tech Stack:** Python unittest/standardlibrary, existing TypeScript Pi extension, exact bundledresources.

## Global Constraints

User approves design+implementation plus related execution defects. No new BP35. No oracle/hardcoded gamecolors/route, mandatory cognitive loop, action refund/retry, deadline renewal or generic duplicate runner. Workers not alone; root commits. Specification: [Task29 design](../specs/2026-10-09-p7-observation-boundary-design.md).

## Task1 — Data measurement and history reader (deployment)

Files: new `src/asterion/applications/prime/p7/view_change.py`; `research_bridge.py`; new `tests/test_prime_p7_view_change.py`; existing `tests/test_prime_p7_research.py`.

Interface `view_change(before,after)->dict` is exact boundedcandidate/unsupported/ambiguous/no-candidate output, <=2KiB; no colorsymbolsemantics. `r.view_change(before_sequence,after_sequence=None)` resolves once and reads immutableframes/refs through existingbridge, noactions. Use `grid()` for accepted raw shape but check <=4096 before costlycomparison. Search0 andaxes±32; threshold/cap rules exactspec.

- [x] Write and run failing truevertical/horizontal shifts, flat/repeating/static/player-only/bounds/history/read-only/immutability tests (unittest).
- [x] Implement boundedliteral detector; include numericmeasurement uncertainty and <=2newwindows, ensure no externaldependency.
- [x] Bridge dispatch and module API accept exactlytwo refs and return actual sequences.
- [x] Run `uv run python -m unittest -v tests.test_prime_p7_view_change tests.test_prime_p7_research`; record RED/GREEN. Offline existingTask28 pairs are optional diagnostic, notnewengine experiment.

## Task2 — Sequential boundary and hardstops (context_impl)

Files: `solver.py`, `prompt.py`; new `tests/test_prime_p7_observation_boundary.py`; relevant `test_prime_p7_solver.py`, `test_prime_p7_research_runtime.py`.

Consume datafunction above; no otherworker files. Publicautonomous fields `stop_on_view_change: bool=True`, step`observe_after:bool=False`; pureoptional defaults preserve single-step plans. `stop_reason='observation-boundary'` holds count/ref/result+unexecuted_steps, explanatorytop-levelsummary andperstepfacts. Insert policyoutsideactiontry/finally and onlyknownsettledsteps, hardstopswin; no blockingkernel/newSDKcalls/LLMcall. Sameidread-only, noauto resumption. Immutablebeforeframe/refcaptured beforedispatch.

- [x] RED criticalRESET wrongexpect+stop_on_mismatchfalse suffix and terminalpriority; record currentunsafeextra dispatch.
- [x] RED shiftprefix/suffix boundary, optout, checkpoint, malformedwholeplan, duplicate/newplan, unknown/cancel/budget and detectorerrorisolation; use realBrokerfixture.
- [x] Implement strictdefaults/validation, per-step boundedfacts and postcommitsoftyield; handle detectorfault outside actiontransaction handling, retainknownfacts.
- [x] Correct hardstoppriority usingactualstate/progress/RESET independentlyofnative mismatch. Preserve mismatches asfeedback.
- [x] Prompt explains objectivecandidate/no cameratruth/no safetyproof, modelchoices andresubmission; noBP35physicsguidance.
- [x] Verify runtimeprojection/stateview preserve addedfacts andcertainty; run focusedboundary+solver+runtime suites.

## Task3 — Typed tools/resources and integration (root)

Files: `packages/typescript/asterion-prime-extension/src/ipython-extension.ts`, correspondingextension tests, bundled`resources/ipython-extension.mjs`; docs/status plus worklist.

- [x] RED TypeBoxvalidation boolonly/unknownkeys and descriptions; add onlytwooptionalfields toexistingclosedparameters; toolsremainipython,p7_execute_plan,p7_workspace.
- [x] Explainyield doesnotmeanterminal/unsafe, pending suffixneedsnewid/currentref, softpolicyfalsecannotbypasshardstops.
- [ ] Syncresource, run `npm --prefix packages/typescript/asterion-prime-extension test`, relatedPython, lint/docs and `RUST_TEST_THREADS=1 make promotion-check`.
- [x] Astra independentdesign/spec/code review; fiximportantfindings. Rootfreeze reviewedimplementationcommit.

## Task4 — Packaged deployment and truthful close (deployment/review/root)

- [ ] One actual `make asterion-prime-p7-level-witness GAME=r11l LEVEL=1` underexisting900+180preset; exactwheel/resource/tools/operator.env, nonewBP35.
- [ ] Installedprovider-freeboundaryfixture verifiescopy/evidence/typedfield/unexecuted suffix where naturalwitness lacks suchchanges.
- [ ] Fullwitnessreplay/trace/source/install/cleanup andindependentfinalaudit, preserveconsole.
- [ ] Recordimplemented/providerfree/deployed separately, no death-rate or efficiencyclaim; commitdesign/source/state promptly andjournalhashes.
