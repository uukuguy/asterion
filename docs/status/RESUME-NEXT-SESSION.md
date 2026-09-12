# Live Session Checkpoint

> Updated: 2026-09-12 11:50 CST. **Session remains active — not a final handoff.**

## TL;DR

- P7 is the completed Asterion Prime native implementation anchor.
- P1-P6 must be rebuilt on P7's `asterion.prime` path; Prime Agent code/SDK is behavioral history only.
- Unified design `49dad716` is written and independently approved; user review is the gate before implementation planning.

## Verified facts

- Current P1 operator still launches Prime Agent source modules, so its live attempts are invalid as native acceptance.
- Current P2-P6 formal development execution paths use Prime SDK/Gateway/source preparation and have no native replacements yet.
- The legacy `prime-agent` provider/runtime, host-service entry points, package resources, Make targets, and source locks remain distributed surfaces.
- The local Prime checkout was renamed by the user and is strictly outside the execution/test boundary.
- `make docs-check` passes: 207 Markdown files and 57 local links.
- The new design passed critical review after adding exact application/package/assembly/service mappings, a complete legacy-surface inventory, and minimal P1-P7 witnesses.

## Approved architecture

- Formal applications select only `prime-applications`; formal runtime is only `asterion.prime`.
- Remove Prime Agent provider/SDK execution from distribution and formal entry points; retain only neutral exported-log comparison.
- P1 retains Asterion-owned worker/oracle/control components but replaces its execution spine.
- P2-P6 receive native implementations under `src/asterion/applications/prime/` and native capability packages.
- Verification remains research-weight: focused boundary tests, one provider-free installed-wheel witness, P7 anchor regression, then one bounded live run.

## Unfinished boundary

- No implementation changes for the unified reset have started.
- P1-P6 are not native-complete and must not expose legacy fallback selectors while unavailable.
- P7 must be revalidated after legacy release surfaces are removed; its application logic is not being rewritten.

## Immediate next action

1. User reviews `docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`.
2. After approval, invoke `writing-plans` and create the phased implementation plan.
3. Execute global release-surface removal and expanded detachment gate before rebuilding P1.

## Working tree boundary

- Preserve user-owned modifications to `.superpowers/sdd/task-*-report.md`, `AGENTS.md`, old untracked plans, and `tmp*` directories.
- Do not inspect or invoke the renamed external Prime checkout.
- No push is authorized.
