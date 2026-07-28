# Architectural Decisions

## Index

| ID | Status | Decision |
|---|---|---|
| D-2026-07-26-01 | 🟢 active | Anchor explicit operator configuration to the environment-file directory |
| D-2026-07-28-01 | 🟢 active | Keep Python source envelopes outside closed portable payload roots |

## D-2026-07-26-01 — Operator configuration root

- Status: 🟢 active
- Decision: The parent directory of an explicit environment file is the root
  for relative Pi, Agent, corpus, and output paths during DCI verification.
  Installed provider resources remain rooted under the package.
- Rationale: Package resources and operator-owned configuration are different
  trust boundaries. Using the package root for both produced false missing
  setup diagnostics and could make preflight disagree with basic execution.
- Consequence: `make doctor` passes the repository `.env` explicitly, and
  preflight/basic resolve the same operator paths without changing generic
  provider discovery or package resource ownership.
- Evidence: commit `2358d49`; `make doctor`; `make check`;
  `make promotion-check`.

## D-2026-07-28-01 — Portable payload source envelope

- Status: 🟢 active
- Decision: `src/asterion/capabilities/dci/` is the Python/source envelope;
  its exact authority-free portable closure lives below `dci/payload/`.
- Rationale: Portable roots accept only canonical descriptor, capability,
  suite, resource, implementation, and conformance members. Placing
  `__init__.py` beside `capability-package.json` would either violate the
  closed-root validator or require a DCI-specific exception.
- Consequence: External, local, and built-in forms can reuse identical payload
  bytes while their source envelopes remain outside the digest. Transitional
  `dci_research/manifests/` copies remain only until Task 3 migrates readers.
- Evidence: commit `f686b75`; `tests.test_dci_capability_payload`; independent
  Task 1 review approved.
