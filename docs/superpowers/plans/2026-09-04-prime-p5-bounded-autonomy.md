# Prime P5 Bounded Autonomy Implementation Plan

**Goal:** Build one fixed IPython-only repair loop with deterministic gate feedback and workspace-digest de-duplication.

**Architecture:** A fixed workload and private trace validate the two-gate causal sequence. A narrow adapter refuses a second gate on the same workspace digest. Provider-free acceptance cannot issue bounded evidence; a separate live reducer requires an admitted worker boundary and operator authorization.

## Tasks

### Task 1: Workload and trace

- Create `operator/bounded_autonomy_workload.py` and `bounded_autonomy_receipt.py` plus focused tests.
- Write failing tests first for exact workload/model/oracle/schema identities, `("ipython",)`, one feedback, two gates, changed workspace digest, terminal/gate/cleanup facts, exact field set, redaction, and bool/count bypasses.
- Implement only canonical SHA-256 manifest bytes and a non-signing immutable trace validator.
- Verify focused unittest, Ruff, Pyright, and diff check; commit `feat(prime): define bounded autonomy trace`.

### Task 2: Gate deduplication adapter

- Create `bounded_autonomy_gate.py` and focused tests.
- Write failing tests proving an unchanged workspace digest rejects before injected gate access, while a changed digest permits exactly one second gate.
- Implement immutable gate-result normalization and no retry/replay API.
- Verify focused unittest, Ruff, Pyright, and diff check; commit `feat(prime): fence bounded autonomy gate`.

### Task 3: Acceptance and live reducer

- Create provider-free acceptance/live validation modules and focused tests.
- Write failing tests proving fake full chain returns only provider-free and raw trace, missing authorization, false attestation, or mismatched worker result cannot issue bounded evidence.
- Bind a private live observation to trace, full platform lock, admitted worker boundary, and all required attestation booleans.
- Verify all P5 tests plus worker-gate regressions, Ruff, Pyright, and diff check; record External-limited real execution; commit `feat(prime): accept bounded autonomy`.

## Constraints

- No Docker, model, network, benchmark, provider, or `.env` access in tests.
- No prompt, source, path, workspace content, gate output, credential, or provider payload in public values.
- Provider-free evidence remains non-promotable.
