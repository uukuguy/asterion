# Live Session Checkpoint

> Updated: 2026-09-16 18:40. **Session remains active — not a final handoff.**

## TL;DR

1. **Phase 4's P1 launch path is committed and green.** P1 runs further every
   time: the live witness now completes **stage one end to end** (setup, verify,
   oracle, `stage1.complete`) and reaches `compact.admit`.
2. **Two real defects were found and fixed** on the way: the Prime-coupled
   extension dependency (deleted), and a Pi event-vocabulary gap that had been
   latent since 2026-09-11 and only a multi-round application could hit.
3. **The current blocker is in the compaction step** and points at the IPython
   worker going invalid after the first turn. That is where the next session
   should start, with the probe described below.

## 已验证事实

- **Commits this session** (all pushed to local `main`, tree clean):
  - `fd962a66` delete the pinned Pi dependency channel (−686 lines) — the
    disguised runtime import of Prime Agent's modified Pi
  - `c21d0dae` Asterion's own compaction summarization module
  - `f1b08c1f` rebuild the native P1 launch path + decouple P1 from the published
    provider + carry the summarization instruction into Pi's compaction
  - `774ae137` docs
  - `540283b8` accept Pi's trailing `agent_settled` event
- **P1 no longer resolves itself out of the published provider.** It composes
  from its own record via `create_prime_ipython_coding_provider()`. The public
  list is unchanged (P7 only). This removed the cause of 34 skipped tests: the
  P1 set went from 38 passed / 34 skipped to **83 passed / 0 skipped**.
- **Detachment gate 0** throughout; targeted set **162 passed**; lint unchanged
  at its 4 pre-existing findings.
- **Live witness progression** (each run is model-driven and therefore
  non-deterministic in where it stops):
  - run 1 `p1-debe34e5…`: died at the first turn — the Pi child refused the
    extension because the context witness needed Prime's compaction internals
  - run 2 `p1-bb85dc5e…`: first turn passed, died on the second — `agent_settled`
  - run 3 `p1-f6f4d6e4…`: **stage one complete**, died at `compact.admit`
- **`agent_settled` root cause:** commit `26519254` swapped the round terminal
  from `agent_settled` to `agent_end` and dropped `agent_settled` from the
  accepted vocabulary entirely. Pi emits `agent_end` then `agent_settled`; the
  round driver stops at its terminal, so the trailing event lands on the *next*
  round. Single-round P7 never sees it; P1 is the first multi-round application.

## 当前判断

- **The compaction blocker most likely is the IPython worker, not the
  summarization wiring.** The probe's last reading before the failure is
  `tool_executor.validate_lifecycle()` raising
  `RuntimeFactoryError('Asterion-prime runtime configuration is invalid')`, and
  `P1WorkerOwnerAdapter.validate_lifecycle` compares the worker's lifecycle token
  by identity — so either the worker's `validate_lifecycle()` raised, or it
  returned a different object. Not yet narrowed further.
- **Method that worked and should be reused:** `PrimeBackendError` is raised
  `from None`, which suppresses the display but leaves the original in
  `__context__`; walking it recovered the real cause every time. The probe also
  logs every Pi event type, which is how the `agent_settled` gap was found —
  the diagnostic only said "event type is invalid" and named nothing.

## 未完成边界

- **The P1 witness has NOT passed.** P1 stays unpublished. Do not publish it
  without a passing witness.
- **Phases 4-9 unstarted; P1-P7 native implementations: 1 of 7** — P7 only.
- **D-2026-09-16-01 is decided but not implemented:** Asterion should own
  compaction summarization via Pi's `session_before_compact` takeover using
  `ctx.modelRegistry.runtime.complete()`. The interim step now in the tree is the
  `customInstructions` append, which reaches the model only on compaction
  Asterion drives itself.
- **Plan risk 1 is now being exercised for the first time** — the run reaches
  compaction. Nothing about it is proven yet.

## 下一动作

1. Narrow why the worker's lifecycle token goes invalid after the first turn.
   Start from `P1WorkerProcess.validate_lifecycle` (`p1/ipython_host.py`) and
   `P1WorkerOwnerAdapter.validate_lifecycle` (`p1/runtime_binding.py`).
2. Re-run with the probe (it is already written and working):
   `.asterion-private/p1-diagnose.py` — it hooks `_validate_recovery`, `_compact`
   and `PiRpcSession.prompt`, and walks `__context__`.

## Ready-to-paste

```bash
# The live witness (operator-authorized; provider-backed; ~2 min):
make asterion-prime-p1-run \
  ASTERION_PRIME_PI_ENTRY=/mnt/mac/opt/homebrew/lib/node_modules/@earendil-works/pi-coding-agent/dist/bundle/rpc-entry.js

# Detachment gate (expect 0):
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

Note the two Orb traps: Orb reaches the Mac only at `/mnt/mac/...`, and its
system node v20 is too old for the Pi — the preset's own `npm exec
--package=node@22` is load-bearing.

## Workspace boundary

- **Asterion prime must never import or depend on Prime Agent.** Reading
  `3th-party/prime-agent.git` read-only to extract a design principle is the
  authorised exception (2026-09-16); every shipped line must be Asterion's own.
- Do not restore Prime launch, Prime locks, or Prime compaction imports.
- On the DeepSeek backend, pass no `model` to any subagent.
- **Run `date` — never estimate a timestamp.**
- **Research intensity:** review changed code plus boundary assertions, run small
  targeted regressions. Do not re-run full suites or harden tooling.
