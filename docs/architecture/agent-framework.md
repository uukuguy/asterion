# Asterion Agent Application Framework

## Product objective

Asterion is a multi-runtime, multi-language framework for composing complete
agent applications from versioned capability packages. DCI is the first
complete reference product: it owns research, durable artifacts, evaluation,
benchmarking, analysis, and export inside the Asterion distribution.

Framework completion means the capability package is installable, executable
through public contracts, portable across supported runtimes, safe at trust
boundaries, and verifiable without hidden source-tree dependencies. Strict
paper reproduction is optional evidence, not a framework prerequisite.

## Layers

1. **Runtime Protocol** — versioned lifecycle, capabilities, events, artifacts,
   cancellation, deadlines, and conformance fixtures.
2. **Runtime adapters** — translate one native runtime into the protocol. Pi and
   Claude Code are independent adapters; native traces need not be identical.
3. **Capability package** — owns a complete domain behavior and exposes closed
   manifests, events, artifacts, policies, and implementation bindings.
4. **Application and assembly** — select exact packages, runtimes, services, and
   executable bindings without implicit version or provider policy.
5. **Provider** — publishes installed applications and constructs only the
   provider selected by exact identity.
6. **Agent system and control plane** — optionally bind one exact control
   provider above an immutable portfolio of application assemblies. The
   provider proposes long-running work; the Python host journals, authorizes
   and admits it before any assembly can execute.
7. **Language hosts** — Python owns research and orchestration, TypeScript owns
   Node/service integration, and Rust owns controlled execution infrastructure.
8. **Host service** — injects operator-authorized facilities such as controlled
   execution without leaking them into portable package contracts.

## Dependency direction

Generic framework modules do not import product implementations. Applications
depend on capability contracts and exact bindings; providers expose installed
applications; runtime adapters depend on the public Runtime Protocol. Product
CLIs may depend on their own package, but the generic `asterion` CLI stays
domain-neutral and loads only the selected provider.

The original DCI implementation used by the parent development workspace is an
external comparison baseline, not a runtime dependency, compatibility module,
or distribution input.

## Optional long-running control plane

Long-running agent systems add a control layer above existing applications;
they do not turn capability packages or assemblies into mutable agents. A
session starts from one resolved `asterion.agent-system/v1` plan containing an
exact control provider and an immutable portfolio. The selected provider then
implements the closed `asterion.agent-control/v1` command/event protocol.

```text
CLI / host -> exact agent system -> selected control provider
           -> canonical journal -> authority and admission
           -> exact application assembly -> runner -> runtime / host services
```

Prime Gateway and the future Asterion-native kernel are peer implementations
behind that boundary. Python retains portable state, authority, budgets,
journal and application invocation; an engine retains only its opaque
continuation capsule. Existing applications that do not select an agent system
continue through the ordinary provider and assembly path unchanged.

See [Agent Control Protocol](AGENT-CONTROL-PROTOCOL.md) for ownership,
state-machine, recovery, evidence and Phase 0 verification details.

## Delivery strategy

- Define and test protocol and package boundaries before adding adapters.
- Keep native provider translation inside the selected runtime adapter.
- Prove framework usability with complete capability behavior, not command
  reachability alone.
- Keep credentials, corpora, datasets, external Pi, and generated evidence out
  of the package and repository contract.
- Treat package-owned provider-free acceptance as the standalone closure gate.
- Keep cross-product selector parity as historical mixed-repository integration
  evidence rather than a standalone runtime dependency.

## Layered runtime configuration

Explicit CLI/application values override exported environment values; exported
values override repository `.env`; runtime-owned and Judge-owned defaults are
last. Runtime selection occurs before provider/model validation. Agent and Judge
credentials, requests, evidence, and cache identities remain separate.

`DCI_PI_DIR` locates the source-pinned external Pi checkout;
`DCI_PI_AGENT_DIR` separately locates user-managed Pi authentication. A global
Pi executable is not an equivalent runtime identity. `ASTERION_DCI_RESOURCE_ROOT`
locates external datasets and corpora consumed by package-owned benchmark task
bindings. Project-owned setup/check commands can provision or diagnose these
external paths without authorizing provider work or a full dataset.

## Verification model

Provider-free acceptance validates installed providers, applications,
assemblies, manifests, context profiles, benchmark identities, and paper scopes:

```bash
uv run asterion verify --provider dci-agent-lite --level acceptance
make check
```

`preflight` validates external readiness; `basic` and `complete` may perform
bounded provider-backed work. Full datasets and paper-score reproduction require
separate governance and budget authorization.

## Non-goals

- Identical reasoning traces across runtimes.
- Vendoring or modifying external Pi.
- Shipping datasets, corpora, credentials, or private evidence.
- Treating a host service as a general sandbox guarantee.
- Building every possible adapter or a multi-tenant control plane in the first
  release.

## Governance after promotion

This repository intentionally contains no parent-workspace planning ledger.
Maintainers should use their GitHub issues, roadmap, and release process while
preserving the public protocol, security, and cost boundaries documented here.
