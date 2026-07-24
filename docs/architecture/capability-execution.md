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
    host_services={},
)
```

AF-110 execution is deterministic and sequential. The runner traverses the
resolved package order, skips declarative policy packages, supplies only
compatible upstream artifacts, validates declared event and artifact outputs,
and stops before later packages after failure or cancellation.

The runner does not discover modules, import capability implementations,
resolve version ranges, start services, retry work, persist state, schedule
parallel branches, or authorize tools. Manifests describe compatibility rather
than authority.

## DCI capability and baseline isolation

The DCI local-corpus implementation and the independent `asterion-dci` product
live in the one `asterion` wheel. `asterion.dci.run.DciRunResult` is converted
only by `asterion.dci.bridge.project_dci_run`, which exposes native artifact
references without answer, question, command, or stderr bodies. The generic
Asterion CLI remains DCI-neutral; `asterion-dci` owns its product-specific
arguments. Neither it nor Asterion imports or modifies the parent workspace's original DCI baseline under `src/dci/benchmark/`.

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
`asterion-dci benchmark` accepts explicit JSONL rows and reuses only Asterion
native run directories; aggregate package results contain references and public
counts, not question, answer, credential, or provider-response bodies.

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

## Deferred application binding

AF-120 owns secure installed-application binding and the generic
`asterion run <assembly>` entry point. That phase must define how an installed
application supplies an exact implementation registry without making Asterion
core import DCI, embedding executable module paths in manifests, or silently
allowing arbitrary dynamic imports.

AF-110 therefore has an explicit Python application composition root but no
generic CLI, plug-in discovery, remote registry, package installation,
automatic provider selection, or automatic service startup.
