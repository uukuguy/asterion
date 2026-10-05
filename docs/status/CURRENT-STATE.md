# Current State

## Project Snapshot

- Project: Asterion composable multi-runtime agent framework; native Prime / P7 research application.
- Current branch: `main`.
- Theme-level focus: WorldMap-driven P7 reasoning through the generic Prime persistent workspace, with cross-attempt research reuse.
- Project route: managed.
- Canonical worklist: `docs/superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md`.
- Active work package: P7 WorldMap solver and local 25-game console. Default WorldMap reasoning, inert failure-experience reuse, saved-prefix continuation, exact cognition provenance and fixed-port playback are integrated on `main`. Local solving is authorized for the25-game catalog under at most two independent guests; each level attempt has a900-second bound. Current saved-route integration, named verification and the one complete25-game official submission gate belong to `RESUME-NEXT-SESSION.md`. This authorization does not permit repeated or open-ended live benchmarks.

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
- Efficiency tasks persist once per game/seed/level when actual actions >= baseline and per-level score <115. Explicit target witnesses clip an SDK-verified source before that level; only improved results replace saved routes. Scheduling accepts a native partial suffix at the current saved highest level; prioritize a pending efficiency task when that game is free.
- Saved routes, current attempts and offline previews are separate console scopes. Live observed completions update overview immediately, while saved-route score/action authority remains sealed. Saved-route progress/actions use one selected verified route per game; attempt diagnostics retain failed/repeated execution. Offline route composition replays existing actions with pinned source evidence and a checked settled seam, without launching the model.
- A selected console level binds one observation source for frames, actions, decisions and cognition. Saved-route authority requires the exact current best-run ID; historical retained views remain labeled while replacement loads. Preview fallback covers missing levels in attempted games as well as unplayed games.
- A trusted acknowledged process interruption may seal failed research without a success receipt. Uncertain environment results and ordinary model errors do not become replayable failures by relabeling.
- HUMAN play is independent of P7, with one finite SDK worker and per-game/per-level persisted origin/action/observation journals. Selection/restart restores verified poses. Current-level clear/restart replaces only that save; ordinary RESET preserves history. Human actions never enter P7 history or learning.

## Open Problems

- Semantic revisions and actual IPython computation now participate in the deployed action path. The provider composite-ID defect is fixed; earlier zero-cell runs cannot establish voluntary avoidance of computation.
- Failure-experience reuse delivers bounded historical evidence, inert source code and explicit provenance. Loading/reading historical research is observed; improved success probability is not established.
- Model runtime settlement and game outcome are separate evidence boundaries. Post-WIN runtime failure keeps its original failure/empty model receipt; a separately audited full SDK replay may create a new sealed game record with immutable source lineage. This does not certify the original native execution.
- Per-level action efficiency and game aggregate are distinct. Equal human baseline gives100 per-level points, capped at115; game aggregation can offset an inefficient early level. The console must label both scopes explicitly.
- Current named checks and external browser limits are recorded in the live checkpoint; historical full promotion does not certify later edits.
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
- `src/asterion/applications/prime/p7/route_composition.py`, `solutions.py` — pinned offline saved-route composition/admission, independent of new model solving.
- `src/asterion/applications/prime/p7/console_preview.py` — isolated each-level initial preview, no solved-state promotion.
- `src/asterion/applications/prime/p7/console_manual.py`, `console_manual_saves.py`, `console_preferences.py` — independent HUMAN lifecycle, journals and selection metadata.

## Evidence Boundary

- Implemented, provider-free verified, deployed and real solving are distinct claims. Sealed actual trace plus replay and cleanup support a live outcome; fixture success does not.
- Local saved-route results, per-level counts, exact run IDs and currently owned processes are recorded in the live checkpoint, with restoration and new actions separated. Local warm replay is not a fresh full benchmark.
- Experience reuse does not carry historical plans or execution authority. Original failed attempts and independent replay recoveries remain distinguishable.
- Exactly one official25-game submission is authorized using saved SP80/DC22 and the new VC33 L1 route; DC22 L6 already passed and must not be re-solved merely to refresh the console. Never infer official performance from local RHAE; official receipt/result and any source selection limitation must be retained.

## Resume Instructions

1. Read this snapshot, `RESUME-NEXT-SESSION.md`, recent JOURNAL entries and AGENTS.md.
2. Check Git status/recent commits and any recorded process/unit before starting another run.
3. Follow the canonical worklist, preserving active work and known non-PASS boundaries.
4. Continue on `main`, inspect actual active guest units, and preserve exact source/campaign/official-submission boundaries. Latest named verification and official-submission gate are in `RESUME-NEXT-SESSION.md`.
