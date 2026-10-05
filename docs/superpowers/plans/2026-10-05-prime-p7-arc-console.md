# P7 ARC Console Implementation Plan

> **For agentic workers:** Execute the approved design task by task, with bounded tests and final code review.

**Goal:** Export a real P7 run as a self-contained Chinese HTML level console.

**Architecture:** Keep conversion and rendering in the Prime application. Read existing recordings and summary projections; do not change runtime contracts. Unlike the sealed run-story reader, explicitly support incomplete runs and mark missing or unaligned evidence.

**Tech Stack:** Python standard library, packaged HTML/CSS/JavaScript, vendored Tailwind utilities, canvas.

## Global constraints

- Single file output; no browser requests, CDN or user build step.
- Read-only replay; all facts come from the selected run.
- P7 is the primary process; cognition is planning background. Missing decision prose is not reconstructed.
- Game level uses levels_completed + 1 before the action; transition frames retain their actual level metadata.
- Cognition snapshots without frame alignment are explicitly final snapshots, never passed off as earlier knowledge.
- Reuse run-story safe JSON embedding, atomic output conventions and existing Chinese cognition renderer where appropriate.
- No prompts, provider responses, worker code or private paths in exported state.

## Shared interface

`build_console_snapshot(run_root: Path) -> dict[str, object]` in `src/asterion/applications/prime/p7/console_snapshot.py`.

Snapshot schema `asterion.arc-agi3-p7-console/v1` has `run`, `levels`, `warnings`, `generated_at`. Run: run_id, game_id, status, completed_level_count, win_levels, target_level, primitive_action_count, replay_verified, sealed_trace, model. Each level: level, status, frames, actions, decisions, cognition, receipt. Frames: id, grid, timestamp, state, levels_completed. Actions: id, name, before_frame, after_frame (frame IDs), data (x/y only), levels_completed, changed_cells, trace_sequence (nullable), decision_id (nullable). Decisions: id, round_index, trace_sequence, action_ids, prompt_signals, output_signals; no invented prose. Cognition: stable_description (Chinese multiline string), scope (`final` or `unavailable`), updates (type, sequence, changes with id/kind/status/claim), world_map_facts (counts only). No exact event/frame connection without source evidence.

## Task 1 — Evidence snapshot

Files: create `console_snapshot.py`, `tests/test_prime_p7_console.py`.

- [x] Add unittest fixtures for reset duplication, no-op action, level advance, multiple frame layers, incomplete receipt, missing records, cross-game mismatch, malicious extra fields and truncated JSONL.
- [x] Read summary and only `recordings/` (never replay directories); reject ambiguous recording identity. Match actions to trace by observation hashes where available. Keep unaligned records visible and labelled.
- [x] Project model round signal metadata. Link only provable actions; do not assign preceding/following events speculatively.
- [x] Use the existing stable Chinese description renderer on the final semantic projection. Load sibling cognition event file by exact session name, only if session identity matches. Strip raw diagnostics and private fields.
- [x] Run `uv run python -m unittest -v tests.test_prime_p7_console`.

## Task 2 — Interactive document

Files: `src/asterion/applications/prime/p7/console_assets/index.html`, `app.js`, `styles.css`, `tailwind.css`, `TAILWIND-LICENSE.txt`.

- [x] Build Chinese header, left level rail, large board, right world-map panel and P7-first process section. Distinguish local proof from missing proof.
- [x] Consume the shared interface via `JSON.parse(document.getElementById('console-data').textContent)`; expose `window.__ASTERION_STATE__` for offline inspection.
- [x] Canvas renders ARC-AGI-3 official colors. Slider and playback drive frame index, action selection and differences. Preserve aspect ratio, responsive layout and reduced-motion preference.
- [x] Use textContent for all evidence. No fetch, external assets, HTML interpolation of run data or eval.
- [x] Keyboard arrows/space skip inputs; selection of a no-data level stops playback and shows empty state.
- [x] P7/actions/cognition tabs with honest absence messages, full claim details behind disclosure, neutral body colors.
- [x] Vendor actual Tailwind output with license; user requires no build step.

## Task 3 — Export and delivery

Files: `console_export.py`, first-party CLI route, Makefile target, pyproject packaged resources, usage documentation.

- [x] Implement `export_console(run_root: Path, output: Path | None = None) -> Path` with script-safe JSON and hashed CSP. Default output is `run_root / 'p7-console.html'`.
- [x] Add `asterion arc-console RUN_ROOT --output FILE` and `make asterion-prime-p7-console RUN=... OUTPUT=...`; no model call.
- [x] Test single file, content escaping, no network resources, output from installed wheel and actual recent unsuccessful run.
- [ ] Browser visual/mobile check is external-limited: installed Chrome extension transport repeatedly timed out. Four jsdom tests cover slider, play/pause, level switching, tabs, differences, no-data states and real exported HTML without resource requests; they do not prove pixel layout.
- [x] Run related Python tests, lint and promotion-check. Inspect every failure before attributing it to baseline. No solver behavior/tool registration change is needed for this export feature.
- [x] Independent code review, fix material issues, generate final HTML, update journal and commit implementation.

## Recovery

Approved design: `docs/superpowers/specs/2026-10-05-prime-p7-arc-console-design.md`.
Real sample: `.asterion-private/prime-p7-live/p7-live-20261004130719-6ff8ee64f2d4c2c8fb971b1b` (five recorded actions, interrupted, no sealed success).
Existing `run_story` remains unchanged. Its strict sealed-evidence contract must not be weakened for the console.

## Verification record

- 29 focused Python snapshot/export tests pass; related run-story and cognition tests passed in the combined 69-test run before final backend fixes.
- 4 DOM integration tests pass (jsdom 26.1.0 installed in a temporary developer directory; no user runtime dependency).
- `make lint`, `make docs-check`, `git diff --check` pass.
- Built wheel exported real sample from `/tmp` through isolated `python -I`, with no source checkout dependency.
- Final independent code review approved after fixing scope, action proof and absolute-path redaction.
- Full promotion result is recorded in JOURNAL and the live checkpoint after completion.
- No new paid/model witness was launched: this change exports already recorded evidence and does not modify solver/tool registration.
