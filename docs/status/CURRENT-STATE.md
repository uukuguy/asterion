# Current State

## Project Snapshot

- Project: Asterion composable multi-runtime agent framework; native Prime / P7 research application.
- Current branch: `feat/p7-live-console`.
- Theme-level focus: WorldMap-driven P7 reasoning through the generic Prime persistent workspace.
- Project route: managed.
- Canonical worklist: `docs/superpowers/plans/2026-10-05-p7-worldmap-solver-redesign.md`.
- Active work package: P7 solver/console redesign; research execution is deployed; direct semantic revision admission is implemented and under packaged live verification.

## Current Architecture

- Python owns composition, application orchestration and execution. The existing Prime session owns model continuation; P7 does not add another runner.
- Prime owns the persistent Python namespace, finite computation, explicit source/JSON exports and checkpoint recovery. Worker and its async transports live on one bridge event loop through cleanup.
- P7 supplies immutable `ObservationState` and Broker history, a read-only context/history/frame/artifact service, and versioned WorldMap/task/model/report records. Research code has no injected action channel; this is not an OS sandbox.
- Default verified runs register exactly `ipython`, `p7_workspace`, `p7_execute_plan` through the packaged TypeScript extension. The actor alone publishes research and submits short predictions through the existing Broker. Default runs do not load Playbook, shared cognition, exact prefixes or offline engine search.
- Semantic `revise` is the low-cost WorldMap path: current evidence and parent revision bind a language model of goals/rules/unknowns. Program `publish` and host-checked reports remain available when computation is useful. A checked report certifies comparison with its referenced observations, not model completeness or new prose.
- Plans bind exact observation and workspace revision. Mismatch, RESET, level change, pause and unknown environment results stop the remaining steps. Matched plans can retain their model. Unknown actions are never automatically replayed.
- Kernel recovery restores only explicit source and JSON, then requires current-observation calibration. It does not reconstruct arbitrary process objects or replay action cells.
- `SolverControl` uses the existing shared run directory for bounded pause/resume acknowledgments. The current bounded cell/action settles before pause; its tool response is held so Pi cannot request another model turn. Resume retains the absolute deadline; stop uses actual process cleanup.
- Console research events share the action/event timeline, including multiple revisions at one frame. Historical cursors select the matching model, prediction and feedback; the live stop control remains independent of history. Background DOM/HTTP/export validation is the established acceptance method; opening Chrome is not required.
- Explicit legacy/cognition modes retain `WorldModelStore`, `SemanticCognitionStore`, `CognitionSession`, `GameMechanicsStore` and certificate-gated DSL search. These are not the new default solver or a prerequisite for general Python research.
- HUMAN play is independent of P7, with one finite SDK worker and per-game/per-level persisted origin/action/observation journals. Selection/restart restores verified poses. Current-level clear/restart replaces only that save; ordinary RESET preserves history. Human actions never enter P7 history or learning.

## Open Problems

- Direct planning can solve simple levels without external WorldMap publication; the semantic main-path revision contract now closes this bypass and requires new deployment evidence.
- Program-model-driven search, multi-level program reuse and cold/warm improvement remain unproven by the current live attempts.
- Full promotion is non-PASS. Current and historical failures are classified in the implementation review; environment-specific differences must not be silently treated as old failures.
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
- Old exact prefixes and human saves cannot be evidence of fresh solving. Read the current recovery baton for run IDs and counts.
- Full 25-game evaluation needs separate finite authorization. Do not widen a bounded witness to improve the result.

## Resume Instructions

1. Read this snapshot, `RESUME-NEXT-SESSION.md`, recent JOURNAL entries and AGENTS.md.
2. Check Git status/recent commits and any recorded process/unit before starting another run.
3. Follow the canonical worklist, preserving active work and known non-PASS boundaries.
4. After tool changes, synchronize packaged resources and perform extension/Python/promotion checks before the finite installed witness. Keep unrelated full-suite failures explicit.
