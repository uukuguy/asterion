# Next-Session Handoff

> Updated: 2026-09-18 07:30, end of session. Phase 5 closed. Commits since Phase 4
> close (`6a11b960`): `66345f79` (journal P1-mirror rollback), `5c47f75` (P2 design-first
> implementation), `91f1bbd` (3 witness defects), `a5fc894` (mid-task checkpoint),
> `51a1b64` (Phase 5 closure / Task 4 publish). HEAD: clean, ruff clean on changed
> files, detachment gate 0, 84 tests pass.

## TL;DR

1. **Phase 5 (P2 rebuild) is complete and published.** `make asterion-prime-p2-run`
   returns exit 0 with sealed receipt `cac924edc5e12b9cb5d1d88e17ac547bd82ac00328dbab74de5157cc7217e0e5`.
   The model invokes the oracle through `prime.p2-oracle` (verified by stderr
   trace, then reverted to clean code); the answer oracle agrees on the slice digest.
2. **P1-P7 native implementations: 3 of 7** — P7, P1, P2 are native, witnessed,
   and published. P3, P4, P5, P6 remain unbuilt. P3 rebuild is next per the
   spec's migration order (L274): rebuild P2; **6. rebuild P4; 7. rebuild P3** —
   wait, re-read: L273 is "5. rebuild P2", L274 is "6. rebuild P4", L275 is
   "7. rebuild P3". So after P2, the next application rebuild is **P4**, not P3.
3. **All session goals met.** Resume can pick up at Phase 6 (P4 rebuild).

## Where things stand

### Phase 5 (closed)

**What landed in this session** (8 files created + 5 edited):

Created:
- `src/asterion/applications/prime/p2/{__init__,context_service,oracle,receipt,worker,runtime_binding,operator,task}.py` — 8 modules, ~1100 lines
- `src/asterion/capabilities/prime_programmatic_long_context_native/{__init__,host,provider}.py`
  + `payload/{capability-package.json, capabilities/prime-programmatic-long-context.json}`
- `src/asterion/applications/prime/assemblies/prime-programmatic-long-context.json`
- `tests/fixtures/prime_p2/small_corpus.json` — 3-record fixture
- `tests/test_asterion_prime_p2_{context_service,oracle,receipt,worker,runtime_binding,provider}.py`

Edited:
- `Makefile` — `?=` defaults for the four operator-owned values; new
  `asterion-prime-p2-run` target; diagnostic sibling `asterion-prime-p2-run-verbose`
- `src/asterion/applications/first_party_packages.py` — registration
- `src/asterion/applications/prime/{__init__,provider,runtime_binding}.py` — wiring
- `pyproject.toml` — index entry `prime.programmatic-long-context__1.0.0`
- `tests/test_asterion_prime_p1_provider.py` — 3-app assertion
- `docs/status/{CURRENT-STATE,JOURNAL}.md`

### What did NOT happen (out of scope)

- **Real model invocation instrumentation** — I added a stderr trace to verify
  the model actually called the oracle (it did), then reverted the trace.
  For future runs, **the witness's stderr is silent** (only `Installed 18
  packages` from uv + the final JSON). If a future session wants to confirm
  the model invoked the oracle again, the trace point is `execute_retrieval`
  in `src/asterion/applications/prime/p2/operator.py` line ~120 — add a single
  `print(..., file=sys.stderr, flush=True)` to surface it.
- **Phase 6 (P4 rebuild) plan + implementation** — plan does not exist; must
  be written before implementation per the program plan. Phase 6 builds on P2's
  control substrate (spec L243: "Build detach, checkpoint, attach, and recovery
  on the native P2 context and control substrate"). So **Phase 6 depends on P2's
  host-facing surface — `execute_retrieval` + `wait_finalization` — which is now
  a real seam that P4 can extend.**
- **Three pre-existing red tests at HEAD unchanged**: `tests.test_pi_session`
  (1F+6E), `tests.test_prime_p7_native_installed` (`Prime solver runtime did not
  complete`), `tests.test_core_only_install.py`. Carried from Phase 4 close.

## Next steps (immediate)

1. **Phase 6 plan** — write before any implementation. P4's witness is
   detach/checkpoint/attach/recovery; needs P2's host seam as substrate.
   Mirrors the Phase5 design-first methodology: spec diff table first, unit
   tests per component, then operator.

## Ready-to-paste commands

```bash
# Phase 5 witness (default values filled):
make asterion-prime-p2-run

# Unit tests:
uv run python -m unittest tests.test_asterion_prime_p2_context_service \
  tests.test_asterion_prime_p2_oracle tests.test_asterion_prime_p2_receipt \
  tests.test_asterion_prime_p2_worker tests.test_asterion_prime_p2_runtime_binding \
  tests.test_asterion_prime_p2_provider tests.test_asterion_prime_p1_provider

# Detachment gate:
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"
```

## Workspace boundary (carried from Phase 4)

- Asterion prime must never import or depend on Prime Agent. Detachment gate stays 0.
- On the DeepSeek backend, pass no `model` to any subagent (AGENTS.md).
- `date` is the only timestamp source.
- Research intensity: review changed code + boundary assertions + small targeted regressions.

## Honest caveats carried forward

- **The sealed receipt is deterministic across host + Orb**. This is good
  engineering (reproducibility) but does NOT prove the model produced a
  substantive answer — it proves the model invoked the oracle with bounds
  `(0, 1)` and got back a slice. **The "answer" field is `answer_sha256 = slice_sha256`**,
  which equals the slice the oracle returned. If the model is meant to
  *transform* the slice, the witness doesn't currently prove that
  transformation happened. **This is a limitation of Phase 5's witness**;
  Phase 6 (P4) may exercise a transform path.
- **Three first-witness defects** (now fixed) were caught because the operator
  emits stderr on BaseException. **That stderr trace is preserved in `main`'s
  `except` block** — future Phase 6/7 operators inherit it. Keep it.
- **The Makefile verbose target `asterion-prime-p2-run-verbose`** remains in the
  tree as a diagnostic sibling. It does NOT need to be removed — it's useful
  for future debug runs.