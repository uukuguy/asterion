# Native DCI research example

## Decision

Native keeps `native.packages@1.0.0` as the multi-package host. That application assembles `controlled-code@1.0.0` and `dci@1.0.0` together. One run of it executes every executable capability in the assembly, so it is not a DCI retrieval example.

Each installed package gains one single-package application. Both applications use the same assembly fields and the same entry. `native.dci-research@1.0.0` carries the DCI retrieval graph. `native.controlled-code@1.0.0` carries the controlled-code graph. Package differences stay in those assemblies and in the operator material. The entry does not branch on package id.

Native gains one direct library entry, `prepare_native_application`. It is the Native peer of `prepare_prime_application`. An application supplies its id and version. The operator supplies the runtime factory, host-service options, and managed host services. Preparation validates that material and does not start Pi. One later `run` executes the selected assembly through the existing composed runner.

The repository example and the live preset call this same entry. They do not resolve an assembly themselves.

This follows decision D-2026-10-20-04. Prime remains the product-independent harness, and `prepare_prime_application` remains the Prime door. DCI remains the retrieval package. The Native entry does not import package implementation modules. The base does not gain a second runner.

## Standard entry

Add the package `asterion.agents.native` and `src/asterion/agents/native/application.py`.

`NativeApplicationSpec` carries `application_id` and `application_version`.

`NativeOperatorContext` carries four values:

- A runtime factory registry.
- The string options for the selected runtime.
- Host-service options, keyed by host capability id.
- Managed host services, keyed by host capability id.

`prepare_native_application(spec, operator)` returns a `NativeApplication`. It calls `create_provider()` in `asterion.applications.native.provider` directly. It does not scan providers. It resolves that provider with `resolve_installed_provider`, the operator's runtime registry, and the builtin packages named by the provider's registered applications. It then selects the application whose id and version match the spec. An unknown id or version fails during preparation. A missing assembly runtime fails during preparation. The union of host-service option keys and managed-service keys must equal the selected assembly's host capabilities, and those two key sets must be disjoint. Any other combination fails during preparation. It does not spawn a process, read `.env`, or import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`. Resolving a sibling application does not execute it. After that selection, open and run follow the assembly. They do not switch behavior by package id or host capability id.

`NativeApplication.run` takes the input text, a run id, and an optional cancellation signal. It executes the selected assembly once. It opens the assembly's host capabilities through `HostServiceFactoryRegistry.open`, passing the operator's options and managed services. A registered factory opens an option-backed service. A managed context supplies an operator-owned service. The entry then creates one runtime from the operator's registry. The factory context uses provider id `native`, the selected application identity, and an empty host-service map. Opened host services are passed only to the composed runner. After `run` returns or fails, a second `run` fails. The entry does not keep a Pi process after the composed run finishes.

The same `prepare` and `run` accept `native.dci-research@1.0.0`, `native.controlled-code@1.0.0`, and `native.packages@1.0.0`.

## Package applications

Every single-package application uses the same assembly fields:

- Protocol `asterion.application-assembly/v1`.
- Runtime `pi.reference`.
- One capability package.
- Empty host policies, host events, and host artifacts.

Add `src/asterion/applications/native/assemblies/native-dci-research.json`.

- Application `native.dci-research` at version `1.0.0`.
- Package `dci@1.0.0`.
- Capabilities `dci.research@1.0.0` and `policy.local-corpus@1.0.0`.
- Host capability `corpus.local-root`.

`policy.local-corpus` stays declarative. The composed run executes `dci.research`.

Add `src/asterion/applications/native/assemblies/native-controlled-code.json`.

- Application `native.controlled-code` at version `1.0.0`.
- Package `controlled-code@1.0.0`.
- Capabilities `evaluation.code-quality@1.0.0`, `observability.execution-audit@1.0.0`, `policy.controlled-code-check@1.0.0`, and `workflow.code-quality@1.0.0`.
- Host capability `executor.controlled`.

`policy.controlled-code-check` stays declarative. The composed run executes the other three capabilities in the composed order.

`src/asterion/applications/native/provider.py` registers both applications beside `native.packages`. All three use provider id `native`. Implementations come from the installed package factories through the existing provider resolution. The provider source does not import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`.

`native.packages` and its assembly stay unchanged. It remains the multi-package host. One run of it still executes every executable capability in that assembly.

## Development example

Add `examples/applications/native_dci.py`.

The file builds a `NativeApplicationSpec` for `native.dci-research` at version `1.0.0`. It builds a `NativeOperatorContext` with the caller's runtime factory registry, the caller's runtime options, one host-service option, and no managed service. The option is `corpus.local-root` with `root` set to the absolute corpus path. It calls `prepare_native_application`, then `run`, and passes the question as the input text. It does not select a provider application by list position, resolve an assembly, or open a host service itself.

The caller owns the registry. The example does not spawn Pi and does not read `.env`.

`examples/README.md` states that this file runs the Native DCI retrieval application through `prepare_native_application`, and that the same entry runs every Native application. `examples/applications/dci_research.py` and `examples/applications/controlled_code.py` stay as they are. This spec does not add a second example script.

## Provider-free test

Add `tests/test_native_application.py`.

The test calls the same `prepare_native_application` and `run` for both single-package applications. Its operator registry binds `pi.reference` to a factory that returns a fixture runtime. The fixture manifest includes `filesystem.read`. The test does not read `.env` and does not start a process. The entry source does not import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`.

For `native.dci-research@1.0.0`, a successful runtime yields `run.started`, one `artifact.created` event whose artifact kind is `answer` and whose uri is non-empty, then `run.completed`. The test checks all of the following:

- Preparation does not call the runtime factory.
- The resolved packages contain `dci@1.0.0` and do not contain `controlled-code`.
- The corpus service receives the absolute root given by the test. The managed map is empty.
- The fixture runtime receives the question as its request input text, and the requested capability is `filesystem.read`.
- The composed result contains event `research.completed` and artifact media type `application/vnd.dci.research+json`.
- A relative corpus path and a missing directory fail while opening the corpus service, before the fixture factory is called.
- An already cancelled signal fails before the host service opens and before the fixture factory is called.
- A second `run` on the same owner fails.

For `native.controlled-code@1.0.0`, the operator passes a managed `executor.controlled` and no option for that capability. The fixture executor accepts the input text as its target and returns status `succeeded`, exit code `0`, and the byte, truncation, duration, and failure fields the workflow reads. The test checks all of the following:

- Preparation does not call the runtime factory.
- The resolved packages contain `controlled-code@1.0.0` and do not contain `dci`.
- `run` calls the runtime factory once, then the executor receives the input text.
- The composed result contains event `workflow.code-quality.completed` and artifact media type `application/vnd.dci.code-quality+json`.
- An already cancelled signal fails before the managed service opens and before the fixture factory is called.
- A second `run` on the same owner fails.

Preparation of `native.packages@1.0.0` succeeds when the operator supplies both the corpus option and the managed executor, and this test does not call `run` for it. Preparation fails when either host capability is missing. The existing `tests.test_native_package_host` remains the assembly proof for `native.packages`.

## Live preset

Add `examples/native_dci_example.sh` and the Make target `native-dci-example`.

The preset calls the same `prepare_native_application` with `default_runtime_factory_registry()` and the runtime options below, then calls `run` once. The spec is `native.dci-research@1.0.0`. The operator supplies the `corpus.local-root` option and no managed service. It does not construct `PiChildProcess` itself. The factory context carries no host service. The options pass `cwd` and do not pass `cwd_host_capability`. Readiness stays in the preset. The entry does not load `.env`.

The run id is `native-dci-` plus a unique suffix. The preset prints that same id.

Readiness uses the git repository root:

- Load the repository `.env` without overriding variables already present in the process. Do not print the file or any credential.
- `DCI_PROVIDER` and `DCI_MODEL` are required and non-empty.
- The Pi checkout is `DCI_PI_DIR` when that path is a real directory, is not a symlink, and contains `packages/coding-agent/dist/cli.js` as a regular file that is not a symlink. Otherwise the checkout is the repository `pi/` directory under the same checks.
- The Node executable is the real path of `node`. The path is absolute. No component is a symlink. The final component is a regular executable file. When `node` is missing, or that path fails this check, readiness exits 2.
- The agent directory is `DCI_PI_AGENT_DIR` when that variable is set. Otherwise it is `~/.pi/agent`. It must be a real directory and not a symlink.
- The corpus directory is `$ASTERION_DCI_CORPUS_ROOT/wiki_corpus` when the variable is an absolute path. Otherwise it is `<repository>/corpus/wiki_corpus`. It must be a real directory, contain `wiki_dump.jsonl`, and satisfy the same exact-path rule as `cwd`.
- Readiness creates `<repository>/outputs` when that directory is missing. If it exists, it must be a real directory and not a symlink. The evidence root may be missing. The factory prepares that final directory. The preset does not delete or change the mode of an existing evidence root.
- Any failed check exits 2 with a public reason. The preset does not run `make setup-pi` and does not call the model.

The factory options are:

- `command`: canonical JSON array. The first element is that Node path. The second element is the absolute `dist/cli.js` already checked above.
- `cwd`: the absolute `wiki_corpus` directory. The path is absolute, no component is a symlink, and the final component is an existing directory.
- `environment`: canonical JSON object of the inherited environment after the `.env` load, including `PI_CODING_AGENT_DIR` set to the agent directory. Keys are sorted and separators are compact. The preset does not print this object.
- `evidence_root`: `<repository>/outputs/native-dci-example`.
- `max_turns`: `6`.
- `tools`: `read,grep`.
- `provider` and `model`: the required DCI values.

The question is the existing basic corpus question:

```text
Answer the following question using only wiki_dump.jsonl in the current directory. Do not use web search. Use rg instead of grep for fast searching. Question: In which street did the Great Fire of London originate?
```

The factory still receives tools `read,grep`. The preset does not add `bash` or `rg`. It does not pass a thinking level, because `pi.reference` accepts only its declared options.

Stdout is one body-free JSON object with `application_id`, `run_id`, and `status`. `application_id` is `native.dci-research`. Status is `completed` or `failed`. The model answer and provider payloads stay in the evidence root. A completed run exits 0. A runtime or capability failure exits 1. A readiness failure exits 2.

The preset performs one retrieval. It does not run a Judge, a benchmark, or `native.packages`.

## Verification

Provider-free verification is `tests.test_native_application` plus `tests.test_native_package_host`.

The implementation run executes `make native-dci-example` once after the readiness checks pass. That run is one model call. If readiness fails, the implementation stops and reports the failed check. It does not start the model.

`make dci-preflight` and `asterion-dci run` stay unchanged. Their current package-root and missing-runtime behavior is outside this spec.

## Out of scope

- A second Pi runner or a change to `PiChildProcess`.
- A change to `prepare_prime_application`, IPython, accepted notes, or Prime session ownership.
- A Native CLI, provider discovery, or a central application registry.
- A separate entry, runner, or example script for one package.
- A live run of `native.controlled-code` or `native.packages`.
- Repair of `examples/asterion_dci_basic_example.sh`.
- Changes to the `native.packages` assembly, P7, or the six `prime-*-native` citation packages.
- A benchmark, an official card, or an L9 rerun.
