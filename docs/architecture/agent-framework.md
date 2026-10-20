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

## Prime applications and CLI scope

P1–P7 are independent applications of Asterion Prime. The standard-entry
migration targets direct library use: an application supplies its domain goals,
tools, data and completion conditions. Prime owns the harness session.
The base `PiRpcSession` owns the Pi process. Central application registration, provider discovery and CLI
dispatch are not prerequisites of that interface. Task40 migrates the existing
P1 and P3–P7 live paths, including the P7 narrator, to the standard owner;
P2 retains its model-free local retrieval mechanism. Source migration and
provider-free verification do not establish cross-domain research ability.
Packaged/live acceptance is recorded in the active worklist and checkpoint.

The purpose and scope of a Prime CLI remain **undecided**. Task40 does not
design a unified application-management CLI. Existing Asterion CLI and
provider/assembly integrations remain compatibility surfaces; applications
may have their own commands or consoles. DCI belongs to the Native line, not
to the Prime application set, and does not establish a need for a Prime CLI.
See [D-2026-10-10-03](../status/DECISIONS.md#d-2026-10-10-03--stable-prime-application-entry-migrate-existing-live-paths-first).

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

## Asterion Prime positioning

Asterion Prime is for agents that autonomously solve problems requiring
substantial human time and effort. Its purpose is long-horizon, open-ended,
falsifiable computational research, with a research chain that humans can
understand, machines can check, evidence can trace, and conclusions can replay.
Games are one application domain; they do not define Prime's scope.

The application structure separates three responsibilities:

| Layer | Responsibility |
|---|---|
| Prime infrastructure | Persistent computation, tool execution, memory and continuity, source/result archives, and execution authority, budgets and recovery boundaries. |
| Domain research | Problem goals, objective rules and available research methods; the LLM owns hypotheses, representations, programs, experiments, interpretation and next actions. |
| Domain data | Exact observations, authorized actions and actual results, with source-bound evidence that the research process can inspect. |

P7 supplies the ARC-specific research and data layers over Prime. A new domain
adapts those layers without importing its semantics into generic framework
modules. These application responsibilities do not introduce another runner
or change the existing provider, assembly, runtime or host-service contracts.

The backend dependency is `P7 -> Asterion Prime -> PiRpcSession`. Prime owns
harness launch preparation, extension binding, tool registration, and session
use. `PiRpcSession` owns the Pi process, including forced close. The one-shot
`pi.reference` facade is still a separate subprocess until `P-PI-1` finishes.
The application operator resolves configuration and injects exact model and
resource context; the generic owner does not read `.env` or profile contents.
P1–P6 target `deepseek/deepseek-flash`; all P7 model paths use
`openai-codex/gpt-6.1-sol`. P2's default run remains local retrieval with
zero model tokens. A separate application inquiry lets an injected model
write one retrieval statement and the answer; the corpus scanner stays in
P2, and `make asterion-prime-p2-live` is the finite preset for that path.
P7 supplies domain tools, goal/continuation content and mappings
from framework events to game evidence. Naming a Pi transport with a neutral
alias does not transfer that ownership. The current migration and its
verification boundary are recorded in the active worklist.

For a persistent IPython kernel, compaction must retain useful identifiers,
function interfaces, computational state, counterexamples and evidence
references. The design assigns these default summarization semantics to Prime;
their specialized implementation is not yet wired into the current launch
chain and is not verified by Task40. Applications do not select summary prompts.
Pi continues to own compaction
triggering, source preparation and persistence. Normal research NOTES remain
the model's primary cognition; specialized compaction is a separate continuity
safeguard. Both capabilities require implementation and named verification.

The research chain records externalized hypotheses and assumptions, computation
source and outputs, experiments and actual observations, counterexamples,
revisions, and the evidence supporting conclusions. It is a reconstructable
research record, not a claim to capture every internal model thought. A
hypothesis remains open to contradiction by new evidence; execution success
alone does not verify a model's interpretation. Replay targets recorded inputs,
programs, execution conditions and result checks, rather than identical future
LLM generations. Required evidence and replay scope depend on the domain.

Prime owns that record's storage rules. `ResearchNotes` exposes the accepted
note epoch: a saved document stays uncommitted until the application persists
its revision, and only that revision and its ancestors are history.
`ResearchRecordStore` indexes opaque evidence with temporal links and unknown
causal support. P7 is the first consumer. It validates game observations and
keeps world models, action meaning, and effectful admission in the application.
An exact reread of a sealed snapshot is archive access, not a second epoch.

Research organization remains model-owned. The harness supplies reliable facts
and hard execution boundaries; it does not require a complete world model,
fixed reasoning sequence, mandatory note form or per-step prediction before
allowing useful research. Negative results and revised conclusions belong in
the record alongside successful results.

This is Prime's architectural objective. P7 provides named interface and solving
evidence at its tested boundaries; cross-domain research effectiveness and
complete replay coverage must be established separately for each application.

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

Prime and Native are peer products on the Asterion base. Prime is the
IPython harness. Native is the multi-package host. `asterion.native` names
the Native control provider, not the capability catalog. DCI is one Native
package. `asterion-prime` owns reusable Prime harness semantics using only
Asterion contracts; it does not import, load, launch, inspect, or require
Prime Agent source or SDK code. P1 through P7 are applications of Prime, not
the agent implementation itself. Prime Gateway evidence is historical and
non-native compatibility evidence; it cannot support a claim that Asterion
implements Prime-style capabilities. Python retains portable state, authority,
budgets, journal and application invocation; an engine retains only its opaque
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
