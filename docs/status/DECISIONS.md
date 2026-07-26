# Architectural Decisions

## Index

| ID | Status | Decision |
|---|---|---|
| D-2026-07-26-01 | 🟢 active | Anchor explicit operator configuration to the environment-file directory |

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
