# Next-Session Handoff

> Updated: 2026-09-12 12:05 CST, end of session.

## TL;DR

- P7 is the completed native Asterion Prime implementation anchor. Rebuild P1-P6 on it; do not repair Prime Agent wrappers.
- Unified native-detachment design is committed at `49dad716` and passed independent critical review. The next session begins with written-spec confirmation, then `writing-plans`.
- Prime Agent source/SDK is outside the execution boundary. Legacy P1-P6 runs are historical behavior evidence only.

## 已验证事实

- Native P7 run `p7-live-20260909065351` completed ARC-AGI-3 `ls20-9607627b` Level 1 through `asterion.prime`, with sealed replay/score/cleanup evidence recorded in `ASTERION-PRIME-P7-EVIDENCE.md`.
- Repository audit found P1's current operator launches Prime Agent modules and P2-P6 formal development paths use Prime SDK/Gateway/source preparation. None counts as native closure.
- The distributed legacy surface still includes the `prime-agent` provider, `prime.agent` runtime, host-service entry points, package resources, Make targets, preparation tools, and source locks.
- The user renamed the local checkout to `3th-party/prime-agent.git`; it is strictly off-limits and must not be read, launched, locked, or retargeted through configuration.
- Design `docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md` defines exact P1-P7 IDs, packages, assemblies, host services, presets, removal inventory, and minimal witnesses.
- Independent critical review returned APPROVE with no blocker/major after revision.
- `make docs-check` passed with 207 Markdown files and 57 local links.
- No Asterion/P1/Prime process from this session remains running.
- Twelve pre-existing benchmark temporary directories were preserved in Git
  stash `181800a4656fe4cf568991724ae88eaccd4eb5bf`; they are not active inputs.

## 当前判断

- Use a trust-boundary rewrite: retain Asterion-owned domain components, but replace the execution spine.
- P1 retains its task, worker, oracle, coordination, receipt, and generic Asterion control/backend pieces; its operator preflight, Pi launch, session/compaction integration, extension dependencies, and acceptance are replaced.
- P2-P6 receive new native implementations under `src/asterion/applications/prime/`; old `applications/prime_agent` execution code is behavioral reference only and leaves the distribution.
- Execute in order: global legacy-surface removal and detachment gate, P7 revalidation, then P1, P2, P4, P3, P5, P6.
- Keep testing research-weight: focused changed-code review and boundary assertions, one provider-free installed-wheel witness, P7 anchor regression, then one bounded live run. Do not revive the 4060-test release gate.

## 历史归档

- Prime-backed P1-P7 CLI traces and development receipts remain historical compatibility evidence; they do not prove native Asterion Prime capability.
- The recent P1 live attempts and event-terminal fixes operated on a forbidden Prime-backed path and must not be continued as acceptance work.
- `3450428e` used the wrong `outputs/...-r9` terminal contract; `26519254` corrected the selected legacy source behavior, but neither makes the path native.
- Old Prime planning artifacts were committed at `a107c7e6` for traceability and are superseded where they require Prime source/SDK execution.

## 未完成边界

- The written spec has not received an explicit post-write user confirmation required before implementation planning.
- No unified implementation plan has been written.
- No legacy provider/runtime/Gateway/package surface has yet been removed.
- P1-P6 native selectors are not complete; do not expose or fall back to legacy selectors while unavailable.
- P7 still requires installed-wheel revalidation after legacy release surfaces are removed; its application logic is not being rewritten.

## 下一动作

1. Read and confirm `docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`.
2. Invoke `writing-plans` and create a phased implementation plan from that spec.
3. First execution wave: remove/disable every legacy release entry and expand detachment checks across Python, TypeScript, Make, tools, package metadata/resources, wheel, and captured installed commands.
4. Revalidate native P7 without any Prime checkout before beginning P1.

## Ready-to-paste commands

```bash
project-state resume
sed -n '1,460p' docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md
git log --oneline -10
git status --short
```

## Workspace boundary

- Do not inspect or invoke `3th-party/prime-agent.git`.
- Do not restore Prime checkout dependencies to satisfy old tests.
- Do not push unless explicitly requested.
- Restore the benchmark-residue stash only if its old fixture files are needed;
  it is not part of the native reset implementation.
