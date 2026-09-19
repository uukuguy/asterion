# Phase 10 (draft) — P1 verify path: multi-strategy + atomic pi-prompt

> Date: 2026-09-19. Drafted from session-end analysis after D-2026-09-19-03
> commit landed protocol-layer fix and exposed a deeper Asterion→Pi session-
> reuse contamination that the protocol layer cannot paper over.

## Ground truth — what we know

- `D-2026-09-19-03` accepts `agent_settled` as implicit ack + leading round
  terminal. This unblocks Asterion's protocol layer when Pi emits
  `agent_settled` as the first event of a fresh round.
- After `D-2026-09-19-03`, the protocol layer passes:
  `verify.start → verify.complete → oracle.start`. The remaining failure
  is at `oracle.verify_stage_one`, which rejects because the worker's
  verification cell `final_result` is `None` — Pi did not run any IPython
  tool during the second prompt.
- Five independent RPC probes against `pi-coding-agent` `rpc-entry.js`
  (cwd = empty tmp, no extension, no env, single `{id,type:"prompt",
  message}` payload, sequential with no idle gap) all produced **two
  complete model turns** — full `message_start → message_update × N →
  message_end → tool_execution_* → agent_end → agent_settled` sequences.
- Therefore: **Pi 0.85.1 is not broken on multi-prompt**. The
  Asterion→Pi wrapper path is contaminated between the two prompts in
  P1 specifically. The contamination is reproducible but its precise
  source has not been localized to a single line in this session.

## Why we are not chasing the contamination as the immediate next step

- The state-machine debugging trail (5 tracebacks across 4 layers, each
  one blocked by the next) consumed an hour of focused session time and
  pinned the issue to "between setup and verify in P1 only, not in any
  other Pi call site we instrumented."
- P2/P3/P4/P5/P6/P7 use the same `drive_prompt` machinery and **do not**
  exhibit this behaviour. The contamination is path-specific to P1's
  two-prompt-in-one-session design.
- The contamination is **consistent** (every P1 rerun produces the same
  broken event sequence), so it is not flaky — it is a deterministic
  side effect of how P1's setup→verify prompt sequence interacts with
  Pi 0.85.1 reuse logic, but the **exact mechanism** remains a
  best-guess set of suspects (extension side effect, session compaction
  triggered between prompts, IPC pipe state, or session_backend reusing
  an "open" flag in a way that hides the second prompt from Pi's
  scheduler).
- Memory has a new feedback (`verify the producer side independently`)
  for this exact failure mode, so the next session can resume cleanly.

## Architectural principle — isolation over reuse

P1's current design reuses one Pi session across setup and verify for
"economy" (avoid re-launching the Pi subprocess, avoid a fresh model
warm-up, avoid re-binding the IPython worker). This economy is paid for
by a fragile dependency on Pi's reuse-mode behaviour, which the
9-phase detachment charter did not cover.

The reuse was a **performance choice**, not a correctness requirement.
P7's research preset, P5/P6's fake-worker witnesses, and the full
detachment program all show that the rest of Asterion Prime tolerates
fresh-per-prompt sessions. P1's two-prompt flow is the only place where
"reuse one Pi session for two distinct prompts" was assumed.

The principle, going forward: **assume no implicit Pi-side state is
shared across prompts** unless the application explicitly asserts the
isolation contract and proves it works under the actual Pi version in
use.

## Decision

> D-2026-09-19-04 — P1 verify accepts one of three strategy modes; the
> default for any new make preset is **subagent**; the application
> contract is unchanged.

The three strategies, in **load-descending order**:

| Strategy | Load | Isolation | When to use |
|---|---|---|---|
| **`subagent`** (default) | In-process child | Same Python process, fresh `_invoke` state (fresh prompt boundary, fresh `_native_events`, fresh `round_terminal_seen`); commit isolation at the worker checkpoint. | **Default.** Any new preset that does not explicitly ask for a different strategy. |
| **`new-pi-subprocess`** | Fresh Pi process | Fresh OS process, fresh Pi session ID, fresh extension lease. State crosses only via the worker's private_root (file-backed). | When in-process subagent is too tightly coupled (e.g., debugging Pi-extended behaviour that depends on a real Pi session). The user's 2026-09-19 hint: "verify 用另一个 pi 进程是符合隔离独立策略的". |
| **`same-session-reuse`** | Existing Pi session | None — shares every Pi-side mutable with setup. | **Deprecated for P1 verify.** Kept only as an opt-in for experiments that want to compare reuse-path behaviour; never the default. |

The user's load-isolation principle (三条路径负载依次减少) maps to
this table directly: subagent (lowest load, full in-process isolation)
→ new-pi-subprocess (mid load, full process isolation) → same-session
reuse (zero load, zero isolation).

## Application contract — unchanged

The `application_id = prime.ipython-coding`, the capability
`prime.ipython-coding`, and the run-time output (verify cell result,
oracle pass/fail, native receipt SHA-256) all stay identical across the
three strategies. Strategy selection is a **make-preset-level knob**, not
an API-level knob — application code does not branch on strategy. The
selected strategy is recorded in the native receipt as a single
`execution_strategy` field (one of the three literal strings above),
recorded **at receipt seal time** so a worker cannot lie after the fact.

## Subagent default — what the implementation looks like (sketch)

The subagent strategy uses the existing `PrimeExecutionKernel` machinery
unchanged but with a fresh `_native_events` list and a fresh
`round_terminal_seen` flag (both already-scoped to a single
`PrimeExecutionKernel` instance — D-2026-09-19-03 fixes already proved
this scope is correct). The diff vs the current P1 verify path is:

1. The P1 operator opens **two** `PrimeExecutionKernel` instances at
   `execute_stage_one` time, sharing the underlying `PiRpcSession` and
   `ExtensionLease`. The first kernel runs the setup prompt and
   produces `worker.snapshot()`'s setup cell. The second kernel runs
   the verify prompt and produces `worker.snapshot()`'s verify cell.
2. Both kernels share the **same `PiRpcSession`** (same underlying Pi
   process, same subprocess, same pipe state), but **distinct**
   `_native_events` lists, distinct sequence counters, and distinct
   round-terminal state.
3. The worker's `compact_checkpoint` is shared (already implemented as
   `P1WorkerCheckpoint.mark_compact_checkpoint`); the first kernel
   calls it, the second kernel reads it through `recover_checkpoint`.

**What this changes**: the second kernel's first event will still be
the Pi-side `agent_settled` (because Pi 0.85.1 reuse path emits that
regardless of who is reading), but the second kernel's
`execution.py:431-444` branch will fire **fresh** and the second
kernel's `_native_events` list will hold whatever events Pi sends. The
oracle will then receive a verify cell that may or may not have
`final_result` set — **if Pi still does not run the cell** (the
contamination may persist even across kernel splits), the oracle
rejects, and the recipe is to escalate to the `new-pi-subprocess`
strategy.

**Why this is cheap to test**: the subagent strategy does not require
a new subprocess, a new extension lease, or new IPC plumbing — it is a
pure refactor of the existing `execute_stage_one` into two kernel
calls. The test surface is exactly the existing P1 unit tests plus
the existing `make asterion-prime-p1-run` shell wrapper; the cost of
trying it is one engineer-day.

## New-pi-subprocess strategy — when to escalate

If the subagent strategy still produces `verify cell final_result is
None` (i.e., the contamination persists even across kernel splits),
escalate to a fresh Pi subprocess for the verify prompt. The
escalation is automatic by default — the receipt records the strategy
that was used, and the next commit can choose to make the strategy
field a function of "did the previous strategy work?". This is **not**
required for the first cut, which only needs subagent-default plus a
manual `ASTERION_PRIME_P1_STRATEGY=new-pi-subprocess` override.

The new-pi-subprocess strategy reuses the `prime.launch` seam (per
`D-2026-09-14-01`): the launch material is plain data, so opening a
second `PiRpcSession` for verify is just another `runtime.launch()`
call sharing the worker's private_root and the canonical `_extension_path`.

## Same-session reuse — explicit deprecation

The existing path (one Pi session, two prompts, no isolation between
them) becomes the **same-session-reuse** strategy and is opt-in only
through `ASTERION_PRIME_P1_STRATEGY=same-session-reuse`. The default
flow **never** takes this path. This is recorded as **closed
enum discipline**: the strategy field on `P1NativeReceipt` has the
three literal values, no fourth "default" value, no "unspecified"
value. Missing or invalid strategy at receipt seal time is a
`P1OperatorError`, not a `recovery-required` — the failure is
deterministic and operator-visible.

## Atomic pi-prompt operation — direction (NOT yet implemented)

The user's 2026-09-19 directive: "能有安全原子化的 pi prompt 操作, 避免后续还有这样没头脑的问题出现".

The shape of the API (target, not in this commit):

```python
# Sketch, not committed code.
class PiPromptOperation:
    """One prompt bound to one Pi session, with one terminal.

    Lifecycle:
        open()  -> acquires a session, sends the prompt, runs to terminal
        cancel() -> bounded cleanup, partial result OK if state is partial
        close()  -> releases the session, sealed receipt

    Invariants:
        - exactly one terminal event reaches the caller
        - any state mutation between open() and the terminal is
          discarded by close() (rollback path)
        - the receipt carries the exact sequence number, exact
          event types, and exact session identity that produced it
    """

    async def open(self, *, request: PiPromptRequest, signal: ...) -> None: ...
    async def cancel(self) -> None: ...
    async def close(self) -> PiPromptReceipt: ...
```

The operation has **three** states (open / cancelled / sealed) — never
two, never four. Cancelled is terminal; sealed is terminal; reopening
on a new request is a new operation. The implementation target is the
existing `PiRpcSession.prompt(...)` method at
`runtimes/pi_rpc.py:1003`, wrapped by a state machine that owns the
event sequence boundary. This is **not in this commit** — it is the
target of a follow-up that lands the subagent strategy, learns its
boundary shape, and then proposes the wrapping.

## Non-goals

- This spec **does not** redesign P1's task statement or worker
  protocol. The verify-cell vs setup-cell split is preserved.
- This spec **does not** introduce a new application_id. The strategy
  field lives inside `P1NativeReceipt`, not in the assembly JSON.
- This spec **does not** change `make asterion-prime-p1-run` for the
  current task. The new make preset `make asterion-prime-p1-run-strategy
  <name>` is the entry point; the default preset stays unchanged for
  this commit.
- This spec **does not** investigate the contamination root cause
  further in this commit. The "Atomic pi-prompt operation" direction
  above is the long-term answer; the subagent strategy is the
  short-term answer.

## Verification plan

- `make asterion-prime-p1-run-strategy subagent` runs the subagent path;
  exits 0 only if oracle.verify_stage_one sees a `verify cell with
  final_result != None`.
- `make asterion-prime-p1-run-strategy new-pi-subprocess` runs the
  fresh-process path; exits 0 only if the oracle passes.
- `make asterion-prime-p1-run-strategy same-session-reuse` runs the
  existing (broken) path; documented to fail at oracle, kept for
  regression comparison.
- `make asterion-prime-p7-solve` and `make asterion-prime-p2-run` etc.
  are untouched (they already work and do not need this redesign).

## Open question for the implementation session

- **Where does the strategy field on `P1NativeReceipt` live?** Candidate:
  `P1NativeReceipt.execution_strategy: Literal["subagent",
  "new-pi-subprocess", "same-session-reuse"]`. Sealed by the strategy's
  kernel at receipt time. Must be added to the receipt hash (extends
  the canonical-form set). Needs a follow-up PR that touches the
  receipt schema + the validation fixtures.
