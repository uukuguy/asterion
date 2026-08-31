# Repository Guidelines

## Scope and Authority

Asterion is a composable, multi-runtime agent application framework. The wheel defined by root `pyproject.toml` and implemented in `src/asterion/` is authoritative. DCI is the reference product, not a dependency generic framework code may assume. Pi, data, credentials, generated evidence, and the parent DCI baseline remain external.

Python owns orchestration, composition, assembly, and execution; TypeScript validates shared contracts and Node integration; Rust owns controlled execution. Do not duplicate composers or runners across languages without approval.

## Architecture and Dependency Direction

Preserve this direction:

```text
CLI/host → selected provider → assembly → catalog/composer
         → exact implementations → runner → runtime/host services
```

Framework modules (`runtime/`, `packages/`, `assembly/`, `runner/`, `services/`) must remain domain-neutral. Products may depend on them; they must not import DCI implementations, tests, or adjacent source trees. Runtime adapters only translate native commands/events into the public protocol.

## Protocol and Composition Invariants

`asterion.agent-runtime/v1`, `asterion.capability/v1`, `asterion.capability-package/v1`, and `asterion.application-assembly/v1` are closed contracts. Schemas under `schemas/`, Python validators, and TypeScript validation must agree. IDs are canonical, versions exact, and arrays sorted and unique.

Manifests describe compatibility, not authority. Never place prompts, credentials, commands, executable paths, environment values, provider configuration, or mutable state in them. Catalogs use explicit local roots, direct JSON children, and exact `package_id@version`; do not add source scanning, ranges, registries, hidden precedence, or symlink traversal.

Composition must be deterministic and fail closed on ambiguity, missing edges, or cycles. Executable kinds require exactly one implementation binding; policies remain declarative. Inputs/results stay immutable, and emitted events, artifact media types, and artifact IDs must satisfy the manifest.

## Runtime, Provider, and Host Boundaries

Runtime streams require one run ID, contiguous sequences, matched tool calls/results, and one terminal event. `asterion list` remains metadata-only; loading imports one selected entry point. Provider resources stay under their root, and all identities must agree exactly.

Runners receive a resolved plan, runtime, implementations, cancellation signal, and read-only host services. They do not discover, authorize, retry, persist, schedule, start services, or choose runtimes. Execution stays sequential and stops on failure/cancellation.

Host services are operator-owned and explicitly injected. `executor.controlled` does not itself authorize commands. The Rust executor applies trusted policy, direct invocation, cleared environments, deadlines, output caps, and cancellation; it is not an OS sandbox.

The repository `.env` already contains operator-owned backend LLM configuration. Application or operator integration may resolve that configuration and inject an exact host service; framework modules must never read `.env`, credentials, or provider settings directly. A user-facing “small verification” is one preset action: it must not ask the user for provider, model, cost, or deadline knobs. The integration enforces finite controls internally and exposes only public-safe status. Missing Native host wiring is an application-integration task, not a request for the user to budget or configure a backend.

## Route Changes by Intent

- **Runtime:** add `src/asterion/runtimes/<name>.py`, an exact factory binding, capability mapping, and tests. Do not fork capability manifests by runtime.
- **Capability/package:** add manifests and implementations under `src/asterion/capabilities/`, composition/output tests, then exact assembly/provider bindings.
- **Application:** add exact refs under `src/asterion/applications/<provider>/assemblies/`, allowed runtimes, and provider exposure. Keep executable paths out of JSON.
- **Protocol:** update canonical schema, Python validator/types, TypeScript types/validation, and `valid-*` plus `invalid-*` fixtures under `tests/fixtures/<protocol>/v1/`.
- **Host service:** define a narrow protocol, declare the assembly capability, inject it only after host preflight, and test missing-service/redaction paths.

## Security, Privacy, and Cost

Trust-boundary failures must fail closed. Public surfaces must not expose prompts, answers, credentials, provider payloads, corpus text, raw output, host-service values, or private paths. Assert redaction with sentinel secrets.

`list`, `describe`, `acceptance`, `make test`, and `make check` are provider-free; `preflight` checks readiness only. `basic`/`complete` may perform bounded Agent/Judge work. Full benchmarks and paper reproduction require separate authorization and a finite budget. Configuration, caches, and prior evidence never grant execution authority.

## Verification and Evidence

Use `unittest` (`test_<surface>.py`, `Test...`, `test_<behavior>`) and `subTest` matrices. Cover success, failure, immutability, identity, determinism, cancellation, and redaction.

```bash
uv run python -m unittest -v tests.test_package_execution
make test
make lint
make docs-check
make check
```

Run `make promotion-check` for packaged resources, entry points, schemas, or distribution assumptions. **Implemented** means code and an entry point exist; **Verified** requires a named passing command in its stated boundary. **External-limited** and **Not rerun** must never be promoted to PASS.

## Review Checklist

Before review, confirm ownership, dependency direction, identities, schema/fixture updates, pre-execution rejection, redaction, and boundary tests. PRs must state the architectural surface, verification commands, cost class, and compatibility impact. Keep commits focused.
