# Live Session Checkpoint

> Updated: 2026-09-18 13:42. **Session remains active — not a final handoff.**

## TL;DR

1. **Phase 6 plan written and approved.** At `~/.claude/plans/serene-mixing-cat.md`
   (255 lines, sha256 `aa45271e531eaf55150d48011a4c88f290087c780182bb58f9988c698bf017ac`).
   17 tasks; design-first methodology (spec diff table P4 vs P1 vs P2 first, then
   component decomposition, then witness acceptance, then out-of-scope).
2. **Phase 5 (P2) is closed and stays closed.** P1-P7 native = 3/7 (P7, P1, P2).
3. **Phase 6 (P4 rebuild) is the active package.** P4 = `prime.long-session-continuity`.
   Witness = two `make` invocations against a persistent `ASTERION_PRIME_P4_PRIVATE_ROOT`
   (commit, then recover with `generation = prior + 1`); deterministic fake-worker
   (no real Pi subprocess). Provider gate stays closed until witness exits 0
   (Task-4 mirror of P2 closure).

## Where things stand

- Plan file: `~/.claude/plans/serene-mixing-cat.md` (NOT in repo — keep durable
  on the harness side per the project's plan-file convention).
- JOURNAL entry added at 13:42 confirming plan + sha + key decisions.
- `git status` clean (plan file lives outside the repo, no commit needed).
- No background processes, no Orb VM, no Pi subprocess, no `python -m asterion`
  lingering.
- Three pre-existing red tests carried from Phase 4 still untouched:
  `tests.test_pi_session` (1F+6E), `tests.test_prime_p7_native_installed`,
  `tests.test_core_only_install.py`.

## What this turn delivered

- Read Phase 6 spec (`docs/superpowers/specs/2026-09-12-asterion-prime-p1-p7-native-detachment-design.md`
  L241–L245, L274, L342–L351).
- Three Explore agents in parallel: (1) checkpoint/continuity substrate in
  `agents/prime/` — `PrimeSessionBackend` + `FilePrimeSessionStore` +
  `PrimeBackendIdentity.generation` + `PrimeAttachment` already exist, but no
  cross-process continuation path; (2) assembly / capability / package JSON
  contracts and the absence of a global `host_capabilities` allowlist;
  (3) operator/runtime boundary — `python -m asterion.applications.prime.pN.operator`
  is a one-shot CLI process, so process replacement = two `make` invocations
  against a persistent private_root (cleaner than a child-process supervisor).
- One Plan agent produced the 17-task decomposition.
- Two clarifying questions answered: fake-worker (P2-style) + Task-4 mirror
  for the provider gate.
- Final plan at `/Users/sujiangwen/.claude/plans/serene-mixing-cat.md`,
  approved.

## Next steps (immediate, action-level)

1. **Task 1** — `src/asterion/agents/prime/store.py` add
   `FilePrimeSessionStore.open_continued(prior_root, next_identity) -> FilePrimeSessionStore`.
   Classmethod. Fail-closed rules in plan §Task 1. Plus
   `tests/test_asterion_prime_p4_store.py` with 4 tests.
2. **Task 2** — capability-package.json + capability JSON. Two static files.
3. **Task 3** — `assemblies/prime-long-session-continuity.json`. One static file.
4. **Task 5** — `src/asterion/applications/prime/p4/host.py`. Type-only Protocol.
5. **Task 6, 7** — oracle + receipt. Pure functions, easy unit tests.
6. **Task 4** — `src/asterion/applications/prime/services.py` (host service).
7. **Task 8** — `src/asterion/applications/prime/p4/runtime_binding.py`.
8. **Task 9** — `src/asterion/applications/prime/p4/operator.py` (the heavy one).
9. **Task 10** — dispatcher branch in existing
   `src/asterion/applications/prime/runtime_binding.py`.
10. **Tasks 11–14** — provider factories, package registration, entry point,
    commit fixture.
11. **Task 15** — Makefile target `asterion-prime-p4-run` (two-invocation
    supervisor + `jq -e` assertions).
12. **Task 16** — full unit-test suite green, ruff clean, detachment gate 0.
13. **Witness** — Orb runs the target; `make asterion-prime-p4-run` exits 0;
    sealed `receipt_sha256` recorded in JOURNAL.
14. **Task 17** — Task-4 mirror: `create_provider()` adds P4 + index entry +
    P1 test guard updated to expect 4 apps. Separate commit.

## Don't go down these paths again (ruled out)

- **A child-process supervisor** (operator watches worker, respawns with higher
  generation). Cleaner mapping to the P4 witness text, but no precedent in the
  codebase; P2's worker is in-process; PiRpcSession only owns one prompt's
  evidence. Two `make` invocations are enough.
- **`os.execv` to replace the operator mid-loop.** Not idiomatic in this codebase;
  would orphan in-process state and the temp dir. Stick with two clean
  processes.
- **Real Pi subprocess in the P4 witness.** Witness proves continuity, not model
  capability. Real Pi stays P1/P7 territory.
- **Multi-generation recovery (gen=2 → gen=3 → …).** Out of scope for Phase 6.
  Recursive continuation is future work.

## Ready-to-paste commands / configs

```bash
# Plan file (read first thing on resume)
cat ~/.claude/plans/serene-mixing-cat.md

# Detachment gate (must stay 0 throughout Phase 6)
uv run python -c "from pathlib import Path; from asterion.agents.prime.detachment import find_source_detachment_violations as f; print(len(f(Path('.'))))"

# Targeted P4 unit tests (when Phase 6 implementation is in tree)
uv run python -m unittest -v \
  tests.test_asterion_prime_p4_store \
  tests.test_asterion_prime_p4_capability_package \
  tests.test_asterion_prime_p4_assembly \
  tests.test_asterion_prime_p4_continuity_store_service \
  tests.test_asterion_prime_p4_host_protocol \
  tests.test_asterion_prime_p4_oracle \
  tests.test_asterion_prime_p4_receipt \
  tests.test_asterion_prime_p4_runtime_binding \
  tests.test_asterion_prime_p4_operator \
  tests.test_asterion_prime_p4_provider \
  tests.test_asterion_prime_p4_entry_point

# Phase 6 witness (after Task 15 lands)
make asterion-prime-p4-run
```

## Workspace boundary (carried from Phase 5)

- Asterion prime must never import or depend on Prime Agent. Detachment gate stays 0.
- On the DeepSeek backend, pass no `model` to any subagent (AGENTS.md).
- `date` is the only timestamp source.
- Research intensity: review changed code + boundary assertions + small targeted regressions.
- Research / solve, do not harden past the point where it catches real violations.