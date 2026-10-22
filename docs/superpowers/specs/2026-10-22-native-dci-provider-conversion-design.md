# Native DCI provider conversion

## Decision

DCI applications live on provider `native` and use `native.dci-*` ids. The capability package stays `dci@1.0.0`. `prepare_native_application` stays the application door. `prepare_prime_application` stays the Prime door.

Provider id `dci-agent-lite` is removed. The Python package `asterion.applications.dci_agent_lite` is removed. Operator code moves to `asterion.applications.dci`. The command name stays `asterion-dci`.

This follows D-2026-10-20-04 and does not add a decision record. It does not close D-2026-07-31-02. It does not authorize a model call or a dataset run.

The one-question example, its managed Judge, and its provider-free preset stay in [the complete example spec](2026-10-22-native-dci-complete-example-design.md). This document owns identity, assembly placement, the Judge factory identity, and the operator command. Where the two documents differ on those points, this document wins.

## Applications

Provider `native` registers these applications, in this order. `native.packages@1.0.0` stays first.

| Application | Resolved runtime order | Replaces |
| --- | --- | --- |
| `native.packages@1.0.0` | `pi.reference` | Unchanged |
| `native.dci-research@1.0.0` | `claude-code.reference`, `pi.reference` | `dci.research-capability@1.0.0` |
| `native.controlled-code@1.0.0` | `pi.reference` | Unchanged |
| `native.dci-complete@1.0.0` | `claude-code.reference`, `pi.reference` | `dci.complete-application@1.0.0` |
| `native.dci-benchmark@1.0.0` | `claude-code.reference`, `pi.reference` | `dci.local-benchmark-application@1.0.0` |

`runtime_ids` is the sorted runtime tuple. Resolved `assemblies` follow that same order, so `assemblies[0]` for the three DCI applications is `claude-code.reference`. The existing Pi research file remains `native-dci-research.json`. Its capabilities stay `dci.research@1.0.0` and `policy.local-corpus@1.0.0`. Its host capability stays `corpus.local-root`. The test that reads research `assemblies[0]` as `pi.reference` is updated with the resolved order.

`native.dci-complete` uses the Pi assembly from the complete example spec. This conversion adds the Claude assembly beside it. Both assemblies carry `dci.analysis`, `dci.benchmark`, `dci.evaluation`, `dci.export`, `dci.research`, and `policy.local-corpus`, all at `1.0.0`. Host capabilities stay `corpus.local-root` and `evaluation.answer-judge`. The `dci.benchmark` capability in this application remains the one-case tally.

`native.dci-benchmark` copies the capability list and host capabilities of `dci.local-benchmark-application`. It is the dataset application. It is not a second copy of the one-question example.

Each moved assembly keeps protocol `asterion.application-assembly/v1`, package `dci@1.0.0`, and empty host policies, events, and artifacts. Only `application_id` and, for the new files, the path change. Pi files use `runtime_id` `pi.reference`. Claude files use `runtime_id` `claude-code.reference`.

New and renamed assembly files:

- `applications/native/assemblies/native-dci-research.json` stays the Pi research assembly.
- `applications/native/assemblies/native-dci-research-claude.json` is the Claude research assembly.
- `applications/native/assemblies/native-dci-complete.json` stays the Pi complete assembly defined by the complete example spec.
- `applications/native/assemblies/native-dci-complete-claude.json` is the Claude complete assembly.
- `applications/native/assemblies/native-dci-benchmark.json` is the Pi benchmark assembly.
- `applications/native/assemblies/native-dci-benchmark-claude.json` is the Claude benchmark assembly.

`src/asterion/applications/native/provider.py` registers the two new applications after `native.controlled-code`. Research, complete, and benchmark each list both runtime ids. The provider does not import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`. There is no new `asterion.application_index` row. The existing `native.packages__1.0.0` row stays.

## Removed identity

Delete these files:

- `applications/dci_agent_lite/assemblies/dci-research-capability.json`
- `applications/dci_agent_lite/assemblies/dci-research-capability-claude.json`
- `applications/dci_agent_lite/assemblies/dci-complete-application-pi.json`
- `applications/dci_agent_lite/assemblies/dci-complete-application-claude.json`
- `applications/dci_agent_lite/assemblies/dci-local-benchmark-application-pi.json`
- `applications/dci_agent_lite/assemblies/dci-local-benchmark-application-claude.json`
- `applications/dci_agent_lite/assemblies/dci-local-research.json`
- `applications/dci_agent_lite/provider.py`

`dci-local-research.json` is the old unbound inventory file. It is not one of the three applications. It is not recreated.

`pyproject.toml` removes the application entry point `dci-agent-lite` and these index rows:

- `dci.complete-application__1.0.0`
- `dci.local-benchmark-application__1.0.0`
- `dci.research-capability__1.0.0`

The script entry becomes:

```text
asterion-dci = "asterion.applications.dci.cli:main"
```

`tools/check_promotion.py` replaces the old assembly paths with the six Native DCI assembly paths above. Each schema stays `asterion.application-assembly/v1`.

The paper ablation matrix keeps runtime id `dci-agent-lite` in `asterion.capabilities.dci.implementation.reproduction.ablation`. That string is a published matrix row, not this provider.

## Operator package

Move the operator modules from `asterion.applications.dci_agent_lite` to `asterion.applications.dci`:

- `acceptance.py`
- `benchmark_authorization.py`
- `benchmark_executor.py`
- `benchmark_host.py`
- `benchmark_instances.py`
- `benchmark_source_lock.py`
- `cli.py`
- `native_small_verification.py`
- `operator_config.py`
- `pathlight_cli.py`
- `pathlight_experiment_cli.py`
- `pathlight_optimization_cli.py`

The new package does not export `create_provider`. `tests/core_module_allowlist.py` lists `asterion.applications.dci` and drops `asterion.applications.dci_agent_lite`.

`acceptance.py` lists the packaged Native assembly paths and no unbound DCI assembly. `create_dci_product` stays the operator product. It is not attached to provider `native`.

Application references move with the assembly they already named:

- `dci.complete-application@1.0.0` becomes `native.dci-complete@1.0.0`.
- `dci.local-benchmark-application@1.0.0` becomes `native.dci-benchmark@1.0.0`.
- `dci.research-capability@1.0.0` becomes `native.dci-research@1.0.0`.

`DCI_PROVIDER_ID` becomes `native`. `DCI_APPLICATION_SELECTOR` becomes `native.dci-complete@1.0.0`.

`asterion-dci list` and `asterion-dci describe` delegate with `--provider native`. `asterion-dci run` delegates with `--provider native`, `--application native.dci-complete@1.0.0`, and the selected runtime. Benchmark and Pathlight commands pass the instance's own application selector, so the local fixture uses `native.dci-benchmark@1.0.0` and the dataset instances use `native.dci-complete@1.0.0`.

`asterion-dci preflight`, `basic`, and `complete` call the DCI product built by `create_dci_product` in the operator package. They do not pass `--provider dci-agent-lite` and they do not attach that product to provider `native`.

## Judge factory

`_open_answer_judge_service` accepts provider `native`, application `native.dci-complete`, version `1.0.0`, capability `evaluation.answer-judge`, and empty options. Any other identity still raises `HostServiceRegistryError("answer judge service is unavailable")`.

`native.dci-benchmark` keeps the host capability in its assembly and does not gain a factory acceptance. The development example in the complete example spec still supplies a managed Judge and does not call this factory.

## Verification

Update tests that encode the old provider id, the old module path, or the old application ids. The native provider tuple is the five applications above. `resolved.applications[0]` stays `native.packages`. For research, complete, and benchmark, `assemblies[0].runtime_id` is `claude-code.reference` and `assemblies[1].runtime_id` is `pi.reference`. The application index contains `native.packages__1.0.0` and does not contain `dci-agent-lite` or the three removed `dci.*__1.0.0` rows.

The promotion path set is:

```bash
uv run python -c "import runpy; runpy.run_path('tools/check_promotion.py', run_name='promotion_path_check')"
```

A missing offline Node executable stays outside this spec. Provider-free tests cover the provider tuple, the factory identity, and one `asterion-dci` delegation for `list` and `run`. This spec does not run `make native-dci-example`, `make native-dci-complete-example`, or a dataset benchmark.

`docs/status/INDEX.md` links this spec and records that implementation has not started and that no model call is authorized.

## Out of scope

- A change to package `dci` implementations, other than the Judge factory identity check.
- A change to `prepare_native_application` or `prepare_prime_application`.
- Attaching `create_dci_product` to provider `native`.
- Rewriting the paper ablation runtime id `dci-agent-lite`.
- A Native copy of Prime P1–P7.
- A dataset run, a 50-case closure, or a model call.
- A decision record, a journal line, or an update to `CURRENT-STATE.md`, `RESUME-NEXT-SESSION.md`, or `MEMORY.md`.
