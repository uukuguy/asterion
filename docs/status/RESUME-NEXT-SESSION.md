# Live Session Checkpoint

> Updated: 2026-09-16 19:46. **Session remains active — not a final handoff.**
> Supersedes the 19:04 handoff; the P1 witness session resumed and ran the
> worker-evidence capture that the handoff named as its first next action.

## TL;DR

1. **The SIGTERM question is answered: nothing kills the worker from outside.**
   The worker destroys itself — a cell that is not `completed` sets `_poisoned`
   and calls `close()`, whose `_reap_blocking` SIGTERMs its own process group.
2. **Two different failures were observed in two runs, and one is fully root-caused.**
   A cell rejected by `worker_main.py:162` (any identifier starting with `_`)
   fails the whole run. That check is deliberate but over-broad, and relaxing it
   is a security-boundary decision that needs the operator.
3. **The compact path's real cause is still uncaptured.** The probe hook that
   retrieves it (`_receipt` + `sys.exc_info()`) is installed and verified to
   work, but the run that reached compact happened before it was added.

## 已验证事实

Evidence: live probe runs, frame fields, and a local zero-cost reproduction.

- **Probe tooling (all gitignored, under `.asterion-private/`):**
  - `p1-diagnose.py` — now hooks `execute_cell`, `_observation`, `_close`,
    `_read_stderr` and `_receipt` in addition to its original hooks.
  - `p1-probe.sh` — new host launcher. Mirrors `make asterion-prime-p1-run`
    (build wheel, run in Orb under preset node@22, same operator root / Pi
    entry) and changes only the entry point to the probe.
  - `p1-validate-check.py` — new, feeds source directly to
    `worker_main._validate`. No worker, no provider, no side effects.
- **Run A, `p1-49a7bce76d73958cbac63e28`:** both cells `completed`,
  `audit_denials: 0`, `WORKER CLOSE {poisoned: false, closed: false,
  cells_recorded: 2}`. This is an orderly shutdown, not a self-destruct. The
  only failure is `compact.admit` → `COMPACT RECEIPT {status: "uncertain",
  reason_code: "recovery-required", payload: {"evidence_ref": null,
  "result": null}}`.
- **`_compact` swallows its own cause.** `backend.py:1087-1096` catches
  `Exception`, and when the command id is not already recorded it *returns* a
  bottom-out receipt (`uncertain` / `recovery-required`) instead of re-raising.
  Nothing about the failure reaches the caller. Because `_receipt` is called
  inside that `except` block, `sys.exc_info()` there still holds the cause —
  that is what the new hook reads.
- **Run B, `p1-5bb9dc46c8184f3b73ab4e4f`:** the first cell failed. Frame shows
  `audit_denials: 1`, `status: "uncertain"`, `accumulator_id: null`,
  `class_name: null`, `file_write_calls: 0`, empty `output`. The worker never
  ran the cell.
- **The rejection is `worker_main.py:162`.** `if isinstance(node, ast.Name):
  bad = bad or node.id.startswith("_") or node.id in forbidden_names`, followed
  by `state["audit_denials"] += 1` and `raise _Denied("P1 cell rejected")`. The
  model wrote `_stage_one_payload`, `_stage_one_bytes` and `_f`. The
  `__init__` / `__call__` exemption applies only to `FunctionDef` / `ClassDef`
  names, not to `ast.Name`.
- **Confirmed causally, not by inference** (`p1-validate-check.py`):
  the model's cell as written → `DENIED (denials=1)`; the same cell with only
  those three names renamed → `ACCEPTED (denials=0)`; minimal probe
  `x = 1 / _y = 2` → `DENIED`; control `x = 1 / y = 2` → `ACCEPTED`. The only
  variable is the leading underscore.
- **Worker stderr is empty in both runs** (`b''`). `shell.showtraceback` is
  disabled, cell output goes through `redirect_stderr(buffer)` and is discarded
  when the cell fails, and `_Denied` is caught by a bare `except BaseException`.
  The diagnosability gap exists on the worker side too; the frame fields are the
  only worker-side evidence that survives.
- Previous session's `returncode: -15` reading is explained: it is
  `_reap_blocking` signaling its own process group from `_close()`.

## 当前判断

Direction chosen on current evidence; not yet proven end to end.

- **The witness is blocked by at least two independent defects, not one.** Run A
  shows healthy cells and an orderly worker with the failure at compaction; run
  B shows a cell rejected before execution. Both must clear before the witness
  can pass.
- **The underscore rejection is the clearer of the two, and it is a
  usability defect with a security rationale.** Rejecting `_ih`,
  `__builtins__`, `obj.__dict__` and friends is deliberate and must stay. What
  is over-broad is that the same rule also rejects a model-defined local
  variable named `_f`. The fix is a narrowing (e.g. exempt names the cell
  itself binds), not a removal.
- **This is a security-boundary change**, so per AGENTS.md it waits for the
  operator rather than being decided here.
- **The compact failure is expected to be the D-2026-09-16-01 area** — the
  interim `customInstructions` append rather than Asterion-owned summarization
  — but that is a hypothesis, not a finding. It has not been read out yet.

## 历史归档

Rejected or superseded paths, recorded so they are not re-walked.

- **"The worker is being closed or terminated mid-run by something unknown."**
  Superseded: the worker closes itself, and the trigger is a failed cell
  (`ipython_host.py:571-573`) or a failed start (`:375`).
- **"Capture worker stderr to explain the failure."** Tried; both runs returned
  `b''`. Cell output is redirected into an in-process buffer and discarded on
  failure. Do not re-invest here — read the frame instead.
- Carried over from the 19:04 handoff and still valid: rebuilding the Prime
  compaction dependency against another source; letting the extension import
  Pi's compaction internals; treating `customInstructions` as sufficient;
  asking upstream for `replaceInstructions`; two Pi instances for independence.

## 未完成边界

Must not be inferred as complete from local code or unit tests.

- **The P1 witness has NOT passed. P1 stays unpublished.**
- **Phases 4-9 remain unstarted. P1-P7 native implementations: 1 of 7.**
- **The compact path's cause is not yet read out.** The `_receipt` hook is in
  place but has never fired on the compact path.
- **Run-to-run variation is real**: run A reached compact, run B failed at the
  first cell. A single green run would not prove the others fixed.
- `validate_compaction_witness` still requires `entry.get("fromHook") is not
  False`; relax only as part of D-2026-09-16-01.
- Known-unverified carry-overs: `test/context-witness.test.mjs` cannot run;
  `tests/test_core_only_install.py` was already red at HEAD.
- `.asterion-private/p1-diagnose.py`, `p1-probe.sh` and `p1-validate-check.py`
  are temporary diagnostics. Delete them when the diagnosis is done.
- Phase 3's completion stays bounded to Level 1 of one game, seed 0,
  `deepseek-v4-flash`, `promotion: unpromoted`.
- The `climb/` loop is dormant and its `next_action` is stale — not the
  project's next action.

## 下一动作

**Blocked on an operator decision** (security boundary, per AGENTS.md):

1. Decide the underscore rule: narrow `worker_main.py:162` so a cell may bind
   its own `_`-prefixed locals while `_ih` / `__builtins__` / private attribute
   reads stay denied, or leave the rule and constrain the task statement /
   prompt instead.
2. Then re-run the probe to capture the compact path's cause with the `_receipt`
   hook now installed.
3. Implement D-2026-09-16-01 once the witness is stable.

## Ready-to-paste commands

```bash
# Probe run (Orb, real path, probe entry instead of the operator module):
sh .asterion-private/p1-probe.sh

# Zero-cost validator reproduction:
uv run python .asterion-private/p1-validate-check.py

# The official preset (expect the same failures until the above are fixed):
make asterion-prime-p1-run \
  ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

**Two Orb traps, both verified the hard way:** OrbStack mounts the Mac at
`/mnt/mac` (the host path `/opt/homebrew/...` does not exist inside the VM), and
Orb's system node is v20 while the Pi needs Node 22 — the preset's own
`npm exec --package=node@22` is load-bearing and must not be simplified.

## Workspace boundary

- **Asterion prime must never import or depend on Prime Agent.** Reading
  `3th-party/prime-agent.git` read-only to extract a design principle is the
  authorised exception (given 2026-09-16); every shipped line must be Asterion's
  own. The detachment gate must stay 0, and it scans comments.
- Do not restore Prime launch, Prime locks, or Prime compaction imports.
- **On the DeepSeek backend, pass no `model` to any subagent** (see AGENTS.md).
- **Run `date` — never estimate a timestamp.**
- **Search `PATH` and the real environment before concluding a resource is absent.**
- **Research intensity:** review changed code plus boundary assertions, run small
  targeted regressions. Do not re-run full suites or harden tooling.
