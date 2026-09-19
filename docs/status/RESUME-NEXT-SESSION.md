# Next-Session Handoff

> Updated: 2026-09-19 19:50, end of session. **`handoff`** triggered; Phase 9
> + maintenance-window + maintenance-window-2 + the 2026-09-19
> D-2026-09-19-03/04 work session are all closed.
> HEAD: `ed1b0ec9` clean.

## TL;DR

1. **Phase 9 + all maintenance windows are closed.** 9-phase native
   detachment program COMPLETE; P1–P7 native implementations stand at
   **7 of 7** at the proven boundary.
2. **`D-2026-09-19-03` (commit `69787da6`) fixed the P1 protocol
   layer**: `agent_settled` is now a legal implicit ack (drive_prompt)
   and a legal leading round terminal (execution.py:431-444 +
   line-524 check). P1 stage flow now advances to
   `verify.complete → oracle.start`.
3. **`D-2026-09-19-04` (commit `ed1b0ec9`) shipped the Phase 10
   draft spec**: P1 verify accepts three strategies
   (subagent / new-pi-subprocess / same-session-reuse);
   **subagent default**. Application contract unchanged. Spec at
   `docs/superpowers/specs/2026-09-19-asterion-prime-p1-verify-strategies-design.md`.
4. **P1 真模型路径仍 fail** at `oracle.verify_stage_one` — the worker
   verification cell has `final_result = None` because Pi did not run
   the cell. **Pi 0.85.1 itself is not broken** (5 independent RPC
   probes on host all produced two complete model turns); the failure
   is a deterministic Asterion→Pi wrapper contamination, path-specific
   to P1, **root cause not yet localised**.

## Where things stand

- **Branch**: local `main`, clean at `ed1b0ec9` (was `c5e4611a` at
  session start).
- **Commits this session** (`c5e4611a → ed1b0ec9`):
  - `69787da6` — protocol-layer fix for `agent_settled`
  - `1cc542d3` — `D-2026-09-19-03` records + P1 acceptance guide
  - `ed1b0ec9` — Phase 10 draft spec + corrected root-cause narrative
- **Working tree**: clean. No `python -m asterion.*` background
  processes. No `ASTERION_PRIME_*` env residuals.
- **No Phase 10 implementation, plan, or design task breakdown yet** —
  just the design draft at the spec path above.

## What this session delivered

### Session arc

| Step | Outcome |
|---|---|
| User asked for `P1-P7 验收指南文档` | Wrote `docs/status/PRIME-P1-P7-ACCEPTANCE.md`, including a section stating P1 had "6 sealed runs" history. |
| User-driven rerun of `make asterion-prime-p{1..6}-run` | **5 of 6 passed; P1 failed with `status=recovery-required, receipt_sha256=null`** — a real, observable failure, not a doc drift. |
| 5 layer-by-layer diagnostic passes | Root cause localised to `runtimes/pi_rpc.py:769 drive_prompt` ack state machine. Three sibling layers needed the same `agent_settled` fix. |
| Applied A fix (commit `69787da6`) | Protocol layer now passes (`verify.start → verify.complete → oracle.start`). New failure: oracle.verify_stage_one. |
| User said "pi 无法连续执行 prompt 吗？不应该吧" + "verify 用另一个 pi 进程是符合隔离独立策略的" + "subagent 也是一条可以尝试的路径" + "可以多策略配置" + "安全原子化的 pi prompt 操作" | 5 independent RPC probes proved Pi 0.85.1 is not broken. Spec drafted for three-strategy P1 verify. |
| User said "本会话做完" | 4-step plan (root cause → multi-strategy spec → atomic API → subagent impl). Root cause not localised; spec delivered, rest deferred. |
| User said `handoff` | This document. |

### Files touched (all committed)

- `src/asterion/agents/prime/execution.py` — A fix (3 sites)
- `src/asterion/runtimes/pi_rpc.py` — A fix (1 site)
- `docs/superpowers/specs/2026-09-19-asterion-prime-p1-verify-strategies-design.md` — Phase 10 draft (NEW)
- `docs/status/DECISIONS.md` — D-2026-09-19-03 entry (D-2026-09-19-04 is in the spec, not in DECISIONS — spec is its decision record)
- `docs/status/JOURNAL.md` — three entries: 16:19 P1 rerun discovery,
  18:01 corrected root-cause narrative (Pi is not the bug), 19:36
  Phase 10 spec closure
- `docs/status/CURRENT-STATE.md` — Active work package moved from
  "Phase 9 closed" to "Phase 10 draft landed, implementation deferred"
- `docs/status/INDEX.md` — `PRIME-P1-P7-ACCEPTANCE.md` registered
- `docs/status/PRIME-P1-P7-ACCEPTANCE.md` — NEW; P1 section
  documents the current `protocol layer fixed, oracle layer blocked`
  state
- `MEMORY.md` — two new feedback entries:
  - "a state-machine bug fix in one layer is not done" (the
    `agent_settled` 3-layer lesson)
  - "verify the producer side independently before assigning blame"
    (the 5-RPC-probe lesson that refuted the "Pi has a reuse bug"
    hypothesis)

## 已验证事实 (verified)

- P1 真模型 `make asterion-prime-p1-run` exits 1 with
  `{"receipt_sha256":null, "status":"recovery-required"}` after
  `stage1.verify.start`. Before A fix: also reached `stage1.verify.start`
  then closed. After A fix: `verify.start → verify.complete →
  oracle.start → host.close` — i.e., stage flow progresses further,
  but oracle fails.
- Pi 0.85.1 (`/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/`)
  **can** run two consecutive prompts. Five host-side probes
  (different cwd, message lengths, idle gap) all completed both
  model turns cleanly. This was independently verified against
  `dist/bundle/rpc-entry.js` on host path
  `/opt/homebrew/lib/node_modules/...`.
- The detached `P7` research run (`p7-live-20260914141314`) was
  not retested this session; status quo from
  `docs/status/ASTERION-PRIME-P7-EVIDENCE.md`.
- P2/P3/P4/P5/P6 make targets all exit 0 (per the 16:19 rerun).
- A fix (`69787da6`) does not introduce regression in P2–P6's
  make targets — those still pass. **70 P6 tests + 324 P1–P5 regression
  not rerun this session**; the diff is structurally additive
  (one new branch in `execution.py:431-444`, one rename in
  benign-trailing set comment, one new state variable in
  `pi_rpc.py:751-781`, one new line of check on `execution.py:539`).
  Recommended next session: `make test` as the first action to
  confirm no regression.

## 当前判断 (current judgments)

- **The P1 contamination is Asterion-side, not Pi-side.** Root-cause
  investigation points to a deterministic side effect of how
  `execute_stage_one` keeps the same Pi session across setup and
  verify, but the exact code path was not localised in this session.
  Best-guess suspects (ranked by likelihood):
  1. **`compact_events=True` PiRpcConfig** (`applications/prime/p1/runtime_binding.py:81`)
     — large string events in setup cause the runtime to compress
     events; Pi may interpret the compressed event boundary as
     "session over".
  2. **`prime.ipython` extension** — only `registerTool` is registered;
     no session hooks, but the tool's behaviour (creating files,
     restoring kernel state) might leave Pi-side observable state
     that the second prompt reads as "already settled".
  3. **`_opened` flag reuse** (`backend.py:705 if not self._opened:`) —
     second prompt reuses the same subprocess; the `_rpc_lifecycle`
     snapshot from the first prompt may be stale.
  4. **The worker's `_checkpoint_value("settled-{command_id}")`**
     (`backend.py:776`) — checkpoint name "settled-*" matches
     Pi's "agent settled" vocabulary in a way that may collide
     semantically.
- **The subagent strategy (D-2026-09-19-04 default) is the cheapest
  next test.** Two `PrimeExecutionKernel` instances sharing one
  `PiRpcSession` is a pure refactor — no new subprocess, no new
  IPC, no new extension lease. If even this fails the same way,
  the contamination is in `PiRpcSession` itself (single-session
  reuse) and the next escalation is `new-pi-subprocess`.
- **P2/P3/P4/P5/P6/P7 are not affected.** Only P1 uses
  "two consecutive prompts on one Pi session"; the others use
  one prompt or use distinct session identities.

## 历史归档 (superseded / archived)

- The 2026-09-19 17:24 journal entry that concluded "Pi 0.85.1 reuse
  path has a functional regression; the second prompt produces only
  `agent_settled`, no model turn" is **withdrawn**. The 5 independent
  RPC probes on host proved Pi 0.85.1 itself runs multi-prompt cleanly;
  the difference is the Asterion wrapper, not the Pi runtime.
  Correction recorded in JOURNAL at 18:01.

## 未完成边界 (must NOT be inferred as done)

- **P1 真模型路径 does not run end-to-end.** `recovery-required`
  is the still-current outcome. The user-facing claim "P1-P7 7/7
  complete" remains true only at the **protocol-layer + witness**
  boundary; the **functional real-model acceptance** of P1 is not
  closed.
- **Phase 10 implementation, plan, and task breakdown**: not
  written. The spec is design-only.
- **`execution_strategy` field on `P1NativeReceipt`**: not added.
  Required by the spec, but the implementation changes the receipt
  canonical form (and therefore the receipt hash), which means a
  fixture + test sweep is required.
- **Atomic pi-prompt API** (`PiPromptOperation`): not designed.
  Direction only, in spec section "Atomic pi-prompt operation —
  direction (NOT yet implemented)".
- **70 P6 + 324 P1–P5 regression suite**: not run this session
  after A fix landed. Diff is structurally additive, so risk is low,
  but the suite should run as the first action of the next session
  to confirm.
- **`make asterion-prime-p1-run-strategy <name>`**: not added.
  The strategy entry point is spec'd but not implemented.
- **The Asterion→Pi contamination root cause**: not localised.
  The `compact_events=True` suspect has not been verified.

## Workspace boundary (carried forward, unchanged)

- Asterion prime must never import or depend on Prime Agent.
  Detachment gate stays 0. (`grep -rnE 'Pi[A-Z]|pi_extension|pi_rpc|
  runtimes\.pi' src/asterion/applications/prime/` returns nothing.)
- On the DeepSeek backend, pass no `model` to any subagent
  (AGENTS.md).
- `date` is the only timestamp source.
- Research intensity: review changed code + boundary assertions +
  small targeted regressions.
- No `python -m asterion.*` background processes may linger.
- **NEW (this session)**: D-2026-09-19-03 and D-2026-09-19-04 are
  closed; do not regress them.

## Honest caveats carried forward

- P2/P3/P4/P5/P6/P7 use `reusable=False` for their single-prompt
  flows and were not affected by the contamination. The risk that
  introducing subagent / new-pi-subprocess strategies elsewhere
  changes behaviour is bounded to P1's `execute_stage_one`,
  but a regression run is mandatory after each Phase 10 commit.
- The 5-RPC-probe was done on the host path
  (`/opt/homebrew/lib/node_modules/...`), not on the Orb path
  (`/mnt/mac/opt/homebrew/...`). The Asterion make targets run inside
  Orb. The probe proves Pi 0.85.1 is fine in principle; it does not
  prove Pi is fine when launched via Orb with a different env. The
  next-session investigation should either replicate the probe in
  Orb, or accept the host proof and proceed with subagent
  implementation.
- The agent_end/agent_settled distinction (D-2026-09-19-03) is
  based on observation of Pi 0.85.1 behaviour. Future Pi versions
  may emit them in a different order or rename one of them. The
  spec calls this out implicitly via the "Atomic pi-prompt API"
  direction, but the discriminator "leading vs trailing agent_settled"
  is implicit in the execution.py:431-444 comment.
- `TestPrimeBackendRealRpc` remains skipped (`2c7c40c6`); real-Pi
  environment wiring is still out-of-window. Phase 10 work does
  not change this status.

## Next steps (immediate, action-level)

The user said "本会话做完" (deliver the spec, defer the rest). The
next session has three natural entry points; pick one:

1. **Confirm zero regression after A fix.** Run `make test` (70 P6
   + 324 P1–P5 regression). If green, the protocol-layer fix is
   safe and Phase 10 implementation can proceed without rollback
   risk. Recommended first action.
2. **Implement the subagent strategy** (Phase 10 entry point).
   Touch `execute_stage_one` to open two `PrimeExecutionKernel`
   instances. Add `execution_strategy: Literal["subagent", ...]`
   field on `P1NativeReceipt` and update fixtures. Add
   `make asterion-prime-p1-run-strategy subagent` target.
3. **Continue root-cause investigation.** Check whether
   `compact_events=True` on P1's PiRpcConfig causes the
   contamination. Test by changing to `compact_events=False`
   (or temporarily disabling the compact-rpc-event filter) and
   re-running `make asterion-prime-p1-run`. If `agent_settled` is
   no longer the first event on the second prompt, the root cause
   is found and the spec's "same-session-reuse" strategy becomes
   a viable fallback. If `agent_settled` still appears first, the
   contamination is elsewhere; narrow the next suspect.

**Recommended sequence**: (1) → (2) → (3) only if (2) fails.

## Don't go down these paths again

- **Don't assume Pi is broken.** Five independent probes refuted
  this. MEMORY.md "verify the producer side independently" locks
  the lesson.
- **Don't blame "the next layer down" without instrumenting it
  first.** Five tracebacks in three layers (`backend.py:797`,
  `runtime_binding.py:204`, `execution.py:479`, `pi_rpc.py:769`)
  each hid the actual throw with `raise ... from None`. The fix
  was always one layer deeper than the visible failure. The lesson
  is in MEMORY: "instrument ack state, not just the surrounding
  exception".
- **Don't accept "the protocol passed, so it must be downstream"
  as a complete answer.** D-2026-09-19-03 fixed the protocol and
  immediately exposed the oracle-layer failure as the next
  bottleneck. The lesson applies recursively — every "fixed"
  layer may surface a sibling layer that still has the narrow
  shape.

## Ready-to-paste commands / configs

```bash
# First action: confirm A fix did not regress P2–P6.
make test

# Second action: re-run P1 to confirm current failure mode is
# still oracle-layer (not protocol-layer).
ASTERION_PRIME_OPERATOR_ROOT="$(pwd)" \
  ASTERION_PRIME_PI_ENTRY="/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js" \
  make asterion-prime-p1-run
# Expected: exit 1, JSON has receipt_sha256:null, status:recovery-required
# Stage flow: verify.start → verify.complete → oracle.start → close.

# Third action (if root-cause investigation is chosen):
# Temporarily edit src/asterion/applications/prime/p1/runtime_binding.py:81
# compact_events: bool = False
# rebuild and re-run P1. Compare event sequences.

# Or: run the subagent-strategy implementation per spec, commit as
# `feat(prime-p1): subagent verify strategy (D-2026-09-19-04)`.
```

**session-close** at 2026-09-19 19:50.
