# Framework Integration Worklist

> Updated: 2026-09-06. Status: complete.

## Goal

Asterion is a unified agent application framework for installing, composing,
and executing capability packages across compatible runtimes. Framework and
integration contracts are the main product. Prime and Native are parallel
runtime integrations and reference evidence; neither defines framework
completion. DCI remains a reference product.

This worklist supersedes the execution order of the historical Prime parity
roadmap after the seven bounded Prime development applications reached CLI
closure. It preserves all historical evidence and does not promote those runs
to production.

## Completion criteria

Framework integration is complete for this milestone only when current
evidence proves all of the following:

1. A capability generated from the public SDK can be discovered, exactly
   selected, installed, assembled, bound, and executed without a framework
   source edit.
2. Two independently packaged, different-domain extensions can compose and
   execute from installed wheels outside the repository source tree.
3. One domain-neutral capability executes with the same public lifecycle and
   output semantics through two declared-compatible runtime adapters.
4. Missing services, ambiguous composition, invalid output, cancellation, and
   runtime mismatch fail before or at their declared boundary without leaking
   private values.
5. Core contract verification does not require Prime source, product data,
   credentials, Docker, or a model provider. Product integrations retain their
   own bounded end-to-end gates.

## Completed sequence

| ID | Work package | Deliverable and acceptance boundary | Status | Depends on |
|---|---|---|---|---|
| W0 | Goal and inventory alignment | This canonical worklist; public provider/application/package/runtime inventory; historical product plans marked as non-blocking evidence | Complete | Prime P1–P7 development closure |
| W1a | Executable-kind consistency | Public SDK `research` capability reaches its exact implementation through provider, assembly, and runner; missing binding fails before execution | Complete | W0 |
| W1b | Lockable source candidate flow | One source-neutral host step turns metadata candidates into digest-bearing candidates before exact lock resolution; builtin, local, and distribution sources share the same lifecycle without provider import during discovery | Complete | W1a |
| W1c | Framework/product boundary | `runtime/defaults.py` has no Prime application routing; provider-owned integration supplies exact bindings. Agent runtime and control-plane responsibilities are documented as orthogonal contracts before Native routing changes | Complete | W1b |
| W1d | Core-only boundary | Core import/install gate identifies and removes mandatory product dependencies and core-to-product imports without breaking provider entry points | Complete | W1c |
| W2 | Public extension reference | A copyable external extension uses only public SDK/API from manifest through installed CLI execution; its documentation command runs in an isolated environment | Complete | W1 |
| W3a | Cross-package evidence | Two different-domain extension wheels install, compose, and execute outside the source tree with deterministic ordering and exact bindings | Complete | W2 |
| W3b | Cross-runtime evidence | One neutral capability passes the same lifecycle/output suite through two compatible adapters, including cancellation and missing-service rejection | Complete | W3a |
| W4 | Evidence-led protocol evolution | Record whether real W2/W3 cases require a new protocol. If required, introduce a separate version with schema, Python, TypeScript, fixture, and migration parity; otherwise retain v1 unchanged | Complete | W3 |
| W5 | Layered release gates | Separate core, cross-language contracts, extension wheel, provider integration, and bounded end-to-end commands; retain full release regression separately | Complete | W4 |

## Parallel tracks and exclusions

- Native Phase 3.2 may continue as a parallel runtime/control integration, but
  its parity rows do not block W1–W3 and cannot substitute for cross-runtime
  framework evidence.
- Prime P1–P7 remain closed at their named development boundaries. Further
  Prime UX parity, ARC multi-game runs, and production promotion require their
  own scope and authorization.
- `host_policies` remain declarative compatibility requirements. Preserving
  them in a resolved plan must not make the runner an authorization service.
- Closed v1 contracts are not extended in place. New routing, cardinality, or
  port semantics require evidence from W2/W3 and a separate version decision.

## Resolved and deferred decisions

1. W1b resolved source preparation through a public digest-bearing candidate
   operation without loading provider code during discovery.
2. W1c resolved provider-owned runtime bindings while preserving metadata-only
   list and selected-only loading.
3. Native runtime integration remains a parallel future milestone and must be
   related explicitly to the existing control provider before a route is added.
4. TypeScript package naming and executor protocol migration remain deferred
   until a concrete compatibility requirement justifies them.

## Evidence policy

Each row closes with a named command and observable behavior at the row's own
boundary. Test totals, internal receipts, compatibility fixtures, and product
parity counts do not by themselves close a framework integration row.
