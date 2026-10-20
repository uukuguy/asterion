# Live Session Checkpoint

> Updated: 2026-10-20 20:18. **Session remains active — not a final handoff.**

## TL;DR

- The peer-foundation worklist is the active program. `P-PI-1` and `P-NATIVE-1` are done. Decision D-2026-10-20-04.
- Provider `native` resolves `native.packages@1.0.0` against `pi.reference` with packages `controlled-code@1.0.0` and `dci@1.0.0`. Commit `ef384cd8`.
- `P-CITE-1` is pending and is not started.

## Verified facts

- `tests.test_native_package_host` passed: 2 tests. `resolve_installed_provider` resolves `native.packages@1.0.0` on `pi.reference` with package refs `controlled-code@1.0.0` and `dci@1.0.0`. Resolved implementations are the same objects as the bound package factories, and the two packages' implementation modules are disjoint.
- The same test scans the base runtime, assembly, runner, services, and generic application modules. None import `asterion.capabilities.dci` or `asterion.capabilities.controlled_code`.
- `tests.test_builtin_controlled_code_application` passed. The application entry points are `controlled-code`, `dci-agent-lite`, `native`, and `prime-applications`.
- `tests.test_application_discovery.ApplicationDiscoveryTests.test_builtin_application_index_covers_framework_applications` passed. `native.packages@1.0.0` selects provider `native`.
- `ruff check` passed on the Native provider, its test, the provider inventory test, and the core allowlist.
- No model run was started. `make promotion-check` was not run.

## Open boundary

- `P-CITE-1` is not started. `prime-*-native` packages still execute Prime.
- `tests.test_core_only_install` still reports `asterion.agents.prime.code_summary` missing from `CORE_MODULES`. That gap predates this package.
- A paid run, benchmark, official card, L9 rerun, `make promotion-check`, and a push of `main` stay outside this program.

## Next action

1. `P-CITE-1` is the next pending package and is not started. `prime-*-native` packages cite a Prime receipt: media type, digest, and run identity. They do not contain a second Prime implementation. `prepare_prime_application` remains the Prime execution door.
2. Do not start a paid run from this checkpoint.
