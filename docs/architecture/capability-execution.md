# Composable Capability Execution

## Package and application ownership

An Asterion capability package is a **reusable executable unit**. It declares
portable requirements and outputs in `dci.package/v1`, and an independently
owned implementation supplies its behavior. An application is the executable composition boundary:
it selects exact package versions, one runtime, host
services, and operator input.

Policy packages remain declarative in the first execution slice. Capability,
workflow, memory, observability, and evaluation packages require an exact
implementation binding before execution. Missing, duplicate, unknown, or
partial bindings fail before a runtime or implementation is invoked.

## Explicit execution

The application host resolves an assembly and supplies bindings directly:

```python
from asterion.packages.catalog import PackageRef
from asterion.runner import run_composed_application
from asterion.capabilities.dci_research import DciLocalResearchImplementation

result = await run_composed_application(
    plan,
    implementations=((
        PackageRef("dci.research", "1.0.0"),
        DciLocalResearchImplementation(),
    ),),
    runtime=runtime,
    run_id="research-1",
    input_text=question,
    host_services=host_services,
)
```

Here `host_services` is the exact operator-opened mapping declared by the
assembly; the runner does not construct it.

AF-110 execution is deterministic and sequential. The runner traverses the
resolved package order, skips declarative policy packages, supplies only
compatible upstream artifacts, validates declared event and artifact outputs,
and stops before later packages after failure or cancellation. The composition
has one provider for every package-consumed capability, policy, event, or
artifact edge; provider overlap between packages or between a package and the
host is an ambiguity, not precedence.

## Evidence and result semantics

An assembly declares sorted, unique host event types and artifact media types.
At invocation, the host supplies the actual values, not synthetic manifest
stand-ins. The runner preflights their closed shapes and requires their observed
types to match the assembly declarations exactly before it validates bindings or
starts package work. It snapshots them deeply, then independently passes each
package only the compatible package-produced `upstream_events` and
`upstream_artifacts`, plus compatible caller-owned `host_events` and
`host_artifacts`. All four invocation evidence collections are deeply immutable.

Package result declarations are v1 allowlists: an emitted event type or artifact
media type must be declared, but a package may emit no values and there is no
per-type cardinality guarantee. Artifact IDs must be non-empty and unique
inside each `PackageExecutionResult`. Across package-produced results, the
composed runner maintains one ID set and rejects a duplicate before returning
the aggregate `ApplicationRunResult`. Host artifacts are separate application
inputs: their IDs must be unique among host inputs, but they neither enter nor
seed the package-result/ApplicationRunResult global ID set. Future declarations
for cross-boundary identity, minimum/maximum cardinality, or richer artifact
routing require a new protocol version; they cannot be added silently to v1.

Sensitive in-process stage data uses `InProcessArtifactPayload`. Its private
value and separate public projection are deeply immutable, and its `repr` and
`str` are fixed redactions. Generic output calls `project_public_value`, which
emits only the explicit public projection and rejects unknown opaque objects;
it never recursively serializes arbitrary implementation state.

The runner does not discover modules, import capability implementations,
resolve version ranges, start services, retry work, persist state, schedule
parallel branches, or authorize tools. Manifests describe compatibility rather
than authority.

## DCI capability and baseline isolation

The DCI local-corpus implementation and the independent `asterion-dci` product
live in the one `asterion` wheel. `asterion.dci.run.DciRunResult` is converted
only by `asterion.dci.bridge.project_dci_run`, which exposes native artifact
references without answer, question, command, or stderr bodies. The generic
Asterion CLI stays framework-neutral: it imports no DCI modules, and
provider-free commands remain provider-free. DCI-specific behavior enters only
after installed-provider selection; executable application runs additionally
open all declared host services before runtime construction. The `asterion-dci`
CLI owns its product-specific arguments. Neither it nor Asterion imports or
modifies the parent workspace's original DCI baseline under `src/dci/benchmark/`.

The package-local `asterion-dci resume --output-dir RUN_DIR` command restores
only the immutable request recorded in native `state.json`; it rejects
completed or malformed state before Pi starts and isolates each retry under
`protocol/`. Native evidence includes `conversation_full.json`, the processed
`conversation.json`, and `latest_model_context.json`. Full conversation and
tool-result bodies remain protected native artifacts. A package projection may
name only body-free references, including `conversation.json`,
`latest_model_context.json`, `events.jsonl`, `state.json`, `final.txt`, and
`protocol/`; it never contains their bodies.

`asterion-dci evaluate` uses an Asterion-owned OpenAI-compatible judge contract.
It stores `eval_result.json` only after a structured verdict and reuses it only
when the full public configuration plus shaped request fingerprint matches.
Only the two complete assemblies declare `evaluation.answer-judge`; the
research-only assemblies never load it. The Judge service exposes only a public
identity digest family to package code, while endpoint, model, credential,
timeout, token, pricing, retry, and transport details remain behind the
service boundary.
`asterion-dci benchmark` accepts explicit JSONL rows and reuses only Asterion
native run directories; aggregate package results contain references and public
counts, not question, answer, credential, or provider-response bodies.

The complete application and standalone benchmark share one deterministic
65-resource DCI product identity. It covers the transitive product modules,
the selected manifests and assemblies, and their packaged schemas, profiles,
fixtures, and extension resources. The digest participates in run, batch, and
row fingerprints and is recorded in item, terminal result, summary, analysis,
and complete-stage evidence. Missing or mismatched prior identity rejects
reuse before Agent or Judge work. Generic framework and runtime source stay
outside this product digest; their exact package/runtime contract identities
remain separate execution-boundary inputs.

The existing `dci-agent-lite` command remains the external baseline. Asterion
and baseline runs may share questions and corpora for comparison, but they do
not share benchmark execution code. Equivalent provider reasoning traces are
not required; comparison covers protocol lifecycle, declared capability
behavior, normalized artifacts, and answer quality.

## Runtime and failure boundary

The application host owns runtime construction and configuration. The DCI
implementation sends one portable `RunRequest` through the supplied client and
projects a normalized answer artifact into its declared
`application/vnd.dci.research+json` output.

Public errors identify structural failure classes only. They never include
application input, corpus content, prompts, credentials, provider payloads,
raw tool output, implementation objects, or host-service values. Cancellation
propagates through application runner, capability implementation, and runtime;
later packages do not start after cancellation.

## Installed application binding

The generic `asterion run` path loads one selected provider entry point,
selects one exact application/runtime assembly, resolves one exact runtime
factory, and uses the provider's exact implementation bindings. Manifests
contain no module paths, provider configuration, credentials, or executable
authority. `asterion list` remains metadata-only, and the host does not scan
modules, solve ranges, install packages, select providers automatically, start
services automatically, or consult a remote registry.
