# Native DCI research example

## Decision

Native keeps `native.packages@1.0.0` as the multi-package host. That application assembles `controlled-code@1.0.0` and `dci@1.0.0` together. One run of it executes every executable capability in the assembly, so it is not a DCI retrieval example.

The Native provider gains a second application, `native.dci-research@1.0.0`. It assembles only the DCI retrieval graph.

Native also gains a direct library entry, `prepare_native_application`. It is the Native peer of `prepare_prime_application`. An application supplies its id and version. The operator supplies the runtime factory and host-service options. Preparation validates that material and does not start Pi. One later `run` executes the selected assembly through the existing composed runner.

The repository example and the live preset both call this entry. They do not resolve an assembly themselves.

This follows decision D-2026-10-20-04. Prime remains the product-independent harness, and `prepare_prime_application` remains the Prime door. DCI remains the retrieval package. The Native entry does not import DCI implementation modules. The base does not gain a second runner.

## Standard entry

Add the package `asterion.agents.native` and `src/asterion/agents/native/application.py`.

`NativeApplicationSpec` carries `application_id` and `application_version`.

`NativeOperatorContext` carries three values:

- A runtime factory registry.
- The string options for the selected runtime.
- Host-service options, keyed by host capability id.

`prepare_native_application(spec, operator)` returns a `NativeApplication`. It calls `create_provider()` in `asterion.applications.native.provider` directly. It does not scan providers. It resolves that provider with `resolve_installed_provider`, the operator's runtime registry, and the builtin packages named by the provider's registered applications. It then selects the application whose id and version match the spec. An unknown id or version fails during preparation. A missing assembly runtime fails during preparation. It checks that the operator's host-service keys are exactly the selected assembly's host capabilities. It does not spawn a process, read `.env`, or import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`. Resolving the sibling `native.packages` closure does not execute it.

`NativeApplication.run` takes the input text, a run id, and an optional cancellation signal. It executes the selected assembly once. It opens each declared host service through the registered `asterion.host_services` entry point, then creates the runtime from the operator's registry. The factory context uses provider id `native`, the selected application identity, and an empty host-service map. Opened host services are passed only to the composed runner. After `run` returns or fails, a second `run` fails. The entry does not keep a Pi process after the composed run finishes.

The entry accepts every application the Native provider registers. This spec's example, test, and preset use `native.dci-research@1.0.0`. The composed run of that application executes `dci.research` only. `policy.local-corpus` stays declarative.

## Application

Add `src/asterion/applications/native/assemblies/native-dci-research.json`.

- Protocol `asterion.application-assembly/v1`.
- Application `native.dci-research` at version `1.0.0`.
- Runtime `pi.reference`.
- Package `dci@1.0.0` only.
- Capabilities `dci.research@1.0.0` and `policy.local-corpus@1.0.0`.
- Host capability `corpus.local-root` only.
- Empty host policies, host events, and host artifacts.

`src/asterion/applications/native/provider.py` registers this application beside `native.packages`. Both applications use provider id `native`. Implementations come from the installed DCI package factory through the existing provider resolution. The provider source does not import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`.

`native.packages` and its assembly stay unchanged.

## Development example

Add `examples/applications/native_dci.py`.

The file builds a `NativeApplicationSpec` for `native.dci-research` at version `1.0.0`. It builds a `NativeOperatorContext` with the caller's runtime factory registry, the caller's runtime options, and one host-service option: `corpus.local-root` with `root` set to the absolute corpus path. It calls `prepare_native_application`, then `run`, and passes the question as the input text. It does not select a provider application by list position, resolve an assembly, or open a host service itself.

The caller owns the registry. The example does not spawn Pi and does not read `.env`.

`examples/README.md` states that this file runs the Native DCI retrieval application through `prepare_native_application`. `examples/applications/dci_research.py` and `examples/applications/controlled_code.py` stay as they are.

## Provider-free test

Add `tests/test_native_dci_example.py`.

The test calls `prepare_native_application` and `run`. Its operator registry binds `pi.reference` to a factory that returns a fixture runtime. The fixture manifest includes `filesystem.read`. A successful run yields `run.started`, one `artifact.created` event whose artifact kind is `answer` and whose uri is non-empty, then `run.completed`. The test checks all of the following:

- Preparation does not call the runtime factory.
- The application id is `native.dci-research` and the version is `1.0.0`.
- The resolved packages contain `dci@1.0.0` and do not contain `controlled-code`.
- The corpus service receives the absolute root given by the test.
- The fixture runtime receives the question as its request input text, and the requested capability is `filesystem.read`.
- The composed result contains event `research.completed` and artifact media type `application/vnd.dci.research+json`.
- A relative corpus path and a missing directory fail while opening the corpus service, before the fixture factory is called.
- An already cancelled signal fails before the host service opens and before the fixture factory is called.
- A second `run` on the same owner fails.
- The test does not read `.env` and does not start a process.

The existing `tests.test_native_package_host` remains the proof for `native.packages`.

## Live preset

Add `examples/native_dci_example.sh` and the Make target `native-dci-example`.

The preset calls `prepare_native_application` with `default_runtime_factory_registry()` and the runtime options below, then calls `run` once. It does not construct `PiChildProcess` itself. The factory context carries no host service. The options pass `cwd` and do not pass `cwd_host_capability`. The corpus service stays inside the Native entry. Readiness stays in the preset. The entry does not load `.env`.

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

Provider-free verification is the new example test plus `tests.test_native_package_host`.

The implementation run executes `make native-dci-example` once after the readiness checks pass. That run is one model call. If readiness fails, the implementation stops and reports the failed check. It does not start the model.

`make dci-preflight` and `asterion-dci run` stay unchanged. Their current package-root and missing-runtime behavior is outside this spec.

## Out of scope

- A second Pi runner or a change to `PiChildProcess`.
- A change to `prepare_prime_application`, IPython, accepted notes, or Prime session ownership.
- A Native CLI, provider discovery, or a central application registry.
- Repair of `examples/asterion_dci_basic_example.sh`.
- Changes to the `native.packages` assembly, P7, or the six `prime-*-native` citation packages.
- A benchmark, an official card, or an L9 rerun.
