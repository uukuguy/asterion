# Architectural Decisions

## Index

| ID | Status | Decision |
|---|---|---|
| D-2026-07-26-01 | 🟢 active | Anchor explicit operator configuration to the environment-file directory |
| D-2026-07-28-01 | 🟢 active | Keep Python source envelopes outside closed portable payload roots |
| D-2026-07-28-02 | 🟢 active | Keep application acceptance inventory outside package implementation |
| D-2026-07-28-03 | 🟢 active | Configure generic package sources instead of implementing lifecycle in adapters |

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
  bytes while their source envelopes remain outside the digest. Plan 4 moved
  all readers to the package-owned payload and removed the transitional source
  copies.
- Evidence: commits `f686b75`, `7168667`, and `b9da51d`;
  `tests.test_dci_capability_payload`, `tests.test_dci_package_ownership`, and
  independent Task 1, Task 3, and Task 8 reviews.

## D-2026-07-28-02 — Application-owned acceptance inventory

- Status: 🟢 active
- Decision: Application assembly identities, provider/package factories, and
  assembly discovery remain in `dci_agent_lite`; package verification accepts
  one injected immutable application inventory and contains no application
  path or identity knowledge.
- Rationale: The DCI package owns portable compatibility, implementation, and
  resources, while an application owns exact composition and provider
  exposure. Package-side assembly scanning reverses that dependency.
- Consequence: Installed acceptance can still validate the complete bundled
  product, but the same DCI package remains usable from an external provider
  without importing or naming the first-party application.
- Evidence: commits `d89c51f` and `fce7ba5`;
  `tests.test_dci_package_ownership`,
  `tests.test_dci_complete_application`, and final Task 3 review approved.

## D-2026-07-28-03 — Generic source lifecycle

- Status: 🟢 active
- Decision: Product adapters may register an exact payload and deferred bound
  provider through `BuiltinCapabilityPackageSource`, but they do not implement
  discovery, payload opening, identity validation, or provider loading.
- Rationale: Package-source lifecycle is generic framework behavior. Duplicating
  it in an application adapter weakens source neutrality and can bypass shared
  identity checks.
- Consequence: The DCI adapter owns private input translation and binding
  injection while the generic built-in source owns metadata-first discovery
  and exact payload/provider validation.
- Evidence: commit `af26301`; `tests.test_dci_application_adapter`; final Task 4
  re-review approved.
