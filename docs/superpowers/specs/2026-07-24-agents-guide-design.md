# AGENTS.md Architecture-Guardrail Design

## Purpose

Rewrite `AGENTS.md` as the repository's contributor-facing architecture contract. Its primary job is to prevent changes from expanding Asterion's scope, reversing dependency direction, weakening trust boundaries, or claiming evidence beyond what was verified. General onboarding material is secondary.

## Document Shape

The guide will retain the required title, `Repository Guidelines`, and use short normative sections:

1. **Project Scope & Authority** — define the standalone wheel as authoritative, identify language ownership, and name external/non-goal components.
2. **Architecture & Dependency Direction** — map framework layers and require product-to-framework dependencies only.
3. **Protocol & Composition Invariants** — require closed versioned manifests/assemblies, exact identities, deterministic composition, immutable values, and exact implementation bindings.
4. **Runtime & Host Boundaries** — keep adapters product-neutral, runners explicit and narrow, and host services operator-injected.
5. **Change Rules** — distinguish the files and tests needed for a new runtime, capability, application, schema, or host service.
6. **Security, Privacy & Cost** — require fail-closed/redacted behavior and explicit authorization for provider-backed or full-dataset work.
7. **Verification & Evidence** — prescribe focused tests plus provider-free repository gates and preserve evidence labels.

## Normative Emphasis

Use `must`, `must not`, and concrete paths where violating a rule would change architecture or trust boundaries. Include a compact pre-review checklist. Keep commands only when they prove a boundary. Avoid generic style advice unless it supports deterministic protocols, tests, or portable packaging.

## Accuracy Constraints

The guide must describe current implementation, not planned features. It must not call the Rust executor an OS sandbox, imply runtime trace equivalence, treat manifests as authority, depend on the parent DCI workspace, or equate command reachability with functional verification.

## Acceptance Criteria

- Every normative claim is supported by production code or maintained architecture/verification documentation.
- A contributor can determine where a change belongs and which adjacent layers it must not modify.
- New protocol behavior requires canonical schema, implementation validation, positive/negative fixtures, and cross-language checks where applicable.
- Provider-free and cost-bearing commands remain visibly separated.
- The final Markdown passes repository documentation checks and contains no absolute developer paths or stale mixed-repository claims.
