# Frozen Catalog Composition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** Bind application plans to the exact validated package payload bytes and reject event or artifact self-consumption.

**Architecture:** Keep the existing secure catalog discovery and its single parsed snapshot. Preserve each selected capability file's raw bytes in that snapshot. A bound package carries the matching immutable bytes from its validated portable payload; composition compares the selected catalog bytes to that authority before resolving any assembly. Drift fails closed, including unchanged refs. Dependency construction retains self edges only for event and artifact inputs.

**Tech Stack:** Python dataclasses, secure catalog discovery, `unittest`.

## Global Constraints

- Preserve exact package refs, package ownership, deterministic order, and existing source lock validation.
- Manifest bytes remain private; public errors do not expose them or paths.
- Tests are provider-free and do not invoke a model.
- Do not commit; root agent owns integration review and commit.

---

### Task 1: Bound package catalog bytes

**Files:** `src/asterion/capability_packages/model.py`, `src/asterion/capabilities/catalog.py`, `src/asterion/applications/provider.py`, `tests/test_installed_application_provider.py`.

**Interfaces:** `InstalledCapabilityPackage._catalog_payload_bytes` holds sorted `(filename, bytes)` for a bound package; `CatalogEntry._document_bytes` holds bytes read in the same descriptor pass as its parsed manifest.

- [x] Add a failing provider test: bind a valid payload, mutate `capabilities/research.json` with the same ID/version and one changed event, then assert `resolve_installed_provider` raises `ApplicationProviderError` and the changed event never reaches a plan. Assert the unchanged bound payload resolves.
- [x] Run `uv run python -m unittest -v tests.test_installed_application_provider.InstalledApplicationProviderTests.test_bound_payload_rejects_same_ref_manifest_drift`; expect the drift assertion to fail on current code.
- [x] At authority binding, copy the already validated frozen payload capability file bytes into a sorted immutable tuple. Add raw bytes to `CatalogEntry` during the existing secure file read; return the parsed manifest and bytes together. In provider composition, compare each bound package's expected filename-to-byte map with entries under its exact catalog root. Keep one aggregate discovery and use that very catalog for `resolve_assembly`.
- [x] Run that test and the complete `tests.test_installed_application_provider` module; expect PASS.

### Task 2: Self-consumed outputs

**Files:** `src/asterion/capabilities/composition.py`, `tests/test_capability_composition.py`.

**Interfaces:** `compose_capabilities` rejects a capability whose consumed event or artifact resolves to itself, while self-referential capability/policy declarations retain their current meaning.

- [x] Add a failing `subTest` matrix for an event and an artifact self-consumer, plus a passing self-provided capability case and the existing ordinary DAG case.
- [x] Run `uv run python -m unittest -v tests.test_capability_composition.CapabilityCompositionTests.test_rejects_self_consumed_outputs`; expect both new cases to fail.
- [x] Remove only event/artifact self-edge suppression: preserve semantic self edges for capability/policy requirements and let the existing cycle detector reject output self-consumption.
- [x] Run `uv run python -m unittest -v tests.test_capability_composition`; expect PASS.

### Task 3: Focused compatibility check

**Files:** tests touched in Tasks 1 and 2 only.

- [x] Run `uv run python -m unittest -v tests.test_capability_source_preparation tests.test_cross_package_extension tests.test_capability_catalog`; expect PASS, confirming exact lock, multipackage ownership and order, and catalog behavior.
- [x] Review diff for source bytes in public repr/errors, unintended path reads, and modifications outside ownership. Report red and green commands to root; do not commit.
