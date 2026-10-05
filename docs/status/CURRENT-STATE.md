# Current State

## Project Snapshot

- Project: Asterion composable multi-runtime agent framework; native Prime / P7 research application.
- Current branch: `main`.
- Theme-level focus: WorldMap-driven P7 reasoning through the generic Prime persistent workspace, with cross-attempt research reuse.
- Project route: managed.
- Canonical worklist: `docs/superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md`.
- Active work package: P7 WorldMap solver and local 25-game console. Console integration and acceptance are complete at their stated boundaries (commit `2fec6fd3`). Failure-experience reuse (`12542476`) and complete-25 official preparation (`c261633c`) are integrated into local `main` through `b074b5f4`; root fast-forwarded and switched after full promotion PASS. Generic live-cognition `ebc4542c` and playback `002f37a0` are committed on `main`;205 related tests, DOM86/one existing skip,21 actual served-HTML checkpoints and final full promotion25 commands PASS. User explicitly authorized sequential local solving across all 25 catalog games under one finite guest at a time, switching after two failed attempts on one blocked level. One complete 25-task official submission is separately authorized after finite DC22/VC33 attempts; pause remaining local games during it. Do not expand this into repeated or open-ended livebench.

## Current Architecture

- Python owns composition, application orchestration and execution. The existing Prime session owns model continuation; P7 does not add another runner.
- Prime owns the persistent Python namespace, finite computation, explicit source/JSON exports and checkpoint recovery. Worker and its async transports live on one bridge event loop through cleanup.
- P7 supplies immutable `ObservationState` and Broker history, a read-only context/history/frame/artifact service, and versioned WorldMap/task/model/report records. Research code has no injected action channel; this is not an OS sandbox.
- Default verified runs register exactly `ipython`, `p7_workspace`, `p7_execute_plan` through the packaged TypeScript extension. The actor alone publishes research and submits short predictions through the existing Broker. Cross-attempt experience loader is committed and exposes bounded prior evidence without carrying old execution authority. Default runs do not load Playbook, shared cognition, exact prefixes or offline engine search. An operator-explicit saved-run continuation is deployed and verified in bounded warm continuation: verified pose restoration and advisory prior rules, with restoration/new actions counted separately.
- Semantic `revise` is the low-cost WorldMap path: current evidence and parent revision bind a language model of goals/rules/unknowns. Program `publish` and host-checked reports remain available when computation is useful. A checked report certifies comparison with its referenced observations, not model completeness or new prose.
- Plans bind exact observation and workspace revision. Mismatch, RESET, level change, pause and unknown environment results stop the remaining steps. Matched plans can retain their model. Unknown actions are never automatically replayed.
- Kernel recovery restores only explicit source and JSON, then requires current-observation calibration. It does not reconstruct arbitrary process objects or replay action cells.
- `SolverControl` uses the existing shared run directory for bounded pause/resume acknowledgments. The current bounded cell/action settles before pause; its tool response is held so Pi cannot request another model turn. Resume retains the absolute deadline; stop uses actual process cleanup.
- Console research events share the action/event timeline, including multiple revisions at one frame. Historical cursors select the matching model, prediction and feedback; the live stop control remains independent of history. HTTP/DOM/export checks validate the projection; the user also requests verification in existing Chrome. Browser transport currently times out, so actual Chrome acceptance is not claimed.
- Explicit legacy/cognition modes retain `WorldModelStore`, `SemanticCognitionStore`, `CognitionSession`, `GameMechanicsStore` and certificate-gated DSL search. These are not the new default solver or a prerequisite for general Python research.
- HUMAN play is independent of P7, with one finite SDK worker and per-game/per-level persisted origin/action/observation journals. Selection/restart restores verified poses. Current-level clear/restart replaces only that save; ordinary RESET preserves history. Human actions never enter P7 history or learning.

## Open Problems

- Semantic revisions and actual IPython computation now participate in the deployed action path. The provider composite-ID defect is fixed; earlier zero-cell runs cannot establish voluntary avoidance of computation.
- Failure-experience reuse now delivers bounded prior evidence and has focused/joint tests plus an inert subprocess reproduction. DC22 sealed/replayed at4/6 with observed negative-hypothesis consumption and retained assumptions; no improvement guarantee or executable program restoration is established. The request-boundary compaction fix is committed; a user-released DC22 continuation is now active from the saved191-action/four-level prefix, pending real end-to-end outcome.
- Full promotion at `b074b5f4` PASS:25 commands, provider_operations=0, full_dataset=no. The earlier three ANSI fixture failures are corrected. Follow-ups at `002f37a0` passed their final full promotion25 commands, plus205 related Python and DOM86/one existing skip checks. Actual served-HTML cognition acceptance passed21 checkpoints; no Chrome visual claim.
- The read service is an application boundary under the operator UID, not a host filesystem/SDK sandbox. Enforcing a stronger sandbox is outside this research change.

## Key Files

- `AGENTS.md`, `MEMORY.md` — repository and collaboration instructions.
- `docs/status/INDEX.md`, `JOURNAL.md`, `RESUME-NEXT-SESSION.md`, `DECISIONS.md` — discovery, events, active recovery and decisions.
- `docs/superpowers/specs/2026-10-05-p7-worldmap-solver-redesign.md` — approved overall design and evidence-driven semantic supplement.
- `docs/superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md` — canonical implementation worklist.
- `docs/reviews/2026-10-05-p7-worldmap-solving-design-review.md` — pinned reference-system comparison.
- `docs/reviews/2026-10-05-p7-worldmap-implementation-review.md` — reviews, tests, deployment and actual ability boundaries.
- `src/asterion/agents/prime/ipython.py`, `ipython_worker.py`, `execution.py`, `session.py` — generic computation/recovery/model admission.
- `src/asterion/applications/prime/p7/research.py`, `solver.py`, `research_runtime.py`, `research_bridge.py` — WorldMap records, plans, Prime integration and read-only evidence access.
- `src/asterion/applications/prime/p7/operator.py`, `runtime_binding.py`, `prompt.py`, `tool_registry.py` — selected default/legacy application wiring.
- `packages/typescript/asterion-prime-extension/` and `src/asterion/applications/prime/resources/ipython-extension.mjs` — typed tool registration and packaged resource.
- `src/asterion/applications/prime/p7/solver_control.py`, `console_events.py`, `console_snapshot.py`, `console_session.py`, `console_server.py`, `console_assets/` — control handshake, timeline and web console.
- `src/asterion/applications/prime/p7/console_manual.py`, `console_manual_saves.py`, `console_preferences.py` — independent HUMAN lifecycle, journals and selection metadata.

## Evidence Boundary

- Implemented, provider-free verified, deployed and real solving are distinct claims. Sealed actual trace plus replay and cleanup support a live outcome; fixture success does not.
- Fresh HTTP overview at fixed port57515 confirms1/25 games,10/183 levels, local5.904762/100,737 actual actions (257 restored+480 new). SP80 contributes6/6;DC22 sealed4/6. Latest L5 attempt2 is in the recovery checkpoint.
- Experience reuse can load bounded prior evidence, including negative hypotheses and cells, but does not carry old plans or execution authority. Current active DC22 run and source evidence are in the recovery checkpoint.
- Local sequential solving is explicitly authorized as described in the live checkpoint. One official 25-task submission is authorized after DC22/VC33 finite attempts; its preflight is ready but no card was opened or submitted. Never infer official performance from local RHAE.

## Resume Instructions

1. Read this snapshot, `RESUME-NEXT-SESSION.md`, recent JOURNAL entries and AGENTS.md.
2. Check Git status/recent commits and any recorded process/unit before starting another run.
3. Follow the canonical worklist, preserving active work and known non-PASS boundaries.
4. Continue on `main`, preserve the active DC22 guest, and preserve exact source/campaign/official-submission boundaries. Latest named verification and official-submission gate are in `RESUME-NEXT-SESSION.md`.
