# P7 Supervised Research Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use subagent-driven-development to implement task-by-task.

**Goal:** Explicit supervised P7 research without aggregate budget stops, with monitored usage and bounded cancellation.
**Architecture:** Operator authorizes research mode; existing Prime all-None limits enforce caller-owned stop. P7 domain broker represents unbounded aggregate actions explicitly, and existing execution/trace remains authoritative.
**Tech Stack:** Python unittest, installed wheel, Make/Orb/systemd; no new dependencies.

## Global Constraints

- Design: ../specs/2026-10-11-p7-supervised-research-design.md, user approved.
- Preserve finite automated presets and official contracts.
- Preserve per-call bounded execution, unknown effects, sequential dispatch and cancellation.
- No model invocation or new BP35 evaluation in this implementation.

### Task 1: Domain action/evidence contract

Files: p7/game.py, broker.py, replay.py, private_trace.py, solutions.py and directly related domain readers; focused unittest.
Interface: P7GameSelection.supervised_research=False; True gives action_cap=None. ArcStatus.actions_remaining=None for supervised. Invalid override+supervised rejected.
- [x] Add failing tests for nullcap, no old-cap stop, finitebatch and existing finite rejection.
- [x] Run unittest, observe expected failure.
- [x] Implement explicit bool selection and cap-aware comparisons; no fake huge cap. Preserve finite batch (64 max in supervised mode) and effect rules.
- [x] Test trace/replay with explicit supervised provenance; inspect consumers with rg.
- [x] Commit scoped domain changes.

### Task 2: Entry, lifecycle and monitor

Files: p7/operator.py, runtime_binding.py, research_runtime.py, solver_control.py, new p7/research_monitor.py; tools/run_prime_p7_guest.py, tools/p7_guest_environment.txt, Makefile; own corresponding tests.
Interface: research mode requires supervised game; model/tool/deadline allNone, max_actions=None rendered as 'none'; use explicit game.supervised_research in binding, reject mode mixing.
- [x] Add failing tests for explicit research vs finite modes, no hidden total deadline, monitored counters and cancellation.
- [x] Run focused unittest, observe expected failure.
- [x] Add Make research target and cgroup preset, no total RuntimeMaxSec, TimeoutStopSec180.
- [x] Remove control deadline fallback only for explicit research; retain per-call limits and bounded settlement at stop.
- [x] Emit safe atomic research-status from trusted runtime events and heartbeat, retain continuous counts through pause/RESET.
- [x] Run focused tests and commit owned files.

### Task 3: Independent review and package verification

Files: guides, DECISIONS, INDEX, CURRENT-STATE, JOURNAL, RESUME; root integration.
- [x] Review changed implementation for explicit authority, nullable domain consumers, cancellation and redaction.
- [x] Fix material findings, run focused unittest and lint/docs.
- [ ] Run make promotion-check for changed distribution/entry assumptions, preserve any External-limited status.
- [ ] Record actual boundaries and commit; no claim of real nine-level completion.
