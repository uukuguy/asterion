# Prime Agent Typical Applications

## Purpose

This is the ordered application-level roadmap for reproducing the useful
end-to-end behavior of the pinned Prime Agent source.  It complements the
protocol and parity ledger: an implemented Gateway surface is not a completed
real-world workflow until a bounded, exact scenario has passed.

## Ordered applications

| Priority | Typical Prime Agent application | Asterion Prime readiness | Required bounded proof |
|---|---|---|---|
| 1 | README RLM: root agent spawns a child, sends a message, receives completion, and deletes the child | High; active work | One real `rlm(...)` lifecycle with message and deletion evidence |
| 2 | Single-repository coding: inspect, edit, test, and repair | High | One disposable-repository task with a named passing test |
| 3 | Background coding: detach, attach, and resume a task | High | One interrupted task resumed to a terminal result |
| 4 | Bounded autonomous repair with a quality gate | High | One finite run that either passes its named gate or truthfully reaches its limit |
| 5 | Multi-agent code review: implementation, tests, and review communicate directly | High | One three-role workflow with causal message evidence |
| 6 | Parallel research and synthesis | Medium-high | Injected research service plus a bounded synthesis result |
| 7 | Scheduled or heartbeat maintenance | Medium-high | One owned schedule/heartbeat trigger through recovery |
| 8 | Reusable project skills, packages, extensions, and MCP tools | Medium-high | One installed capability used by a bounded task |
| 9 | Continual Harness refinement with review and rollback | Medium | One evidence-backed refinement and exact rollback |
| 10 | CLI, JSON/RPC, ACP, headless, and interactive entry points | High | Existing Gateway interface evidence; not pixel-identical TUI reproduction |

## Boundaries

- The target is behaviorally equivalent controlled workflows, not a copy of
  Prime Agent's TUI, hidden reasoning, prompts, credentials, or unrestricted
  command execution.
- Prime source remains pinned at `a18809e00ea30638584d87b3afea7285a9d7296c`.
- Real runs use the operator-owned `.env` wiring, fixed internal bounds, and
  public-safe evidence only.  A failure is `External-limited`, not PASS.
- Framework evidence and real application evidence remain separate.

## Current start point

Priority 1 is active.  The Asterion-side RLM, message, deletion, authority,
and recovery paths are implemented.  The remaining proof is a bounded real
Prime daemon run whose checkpoint maintenance must not obscure the standalone
README RLM lifecycle.
