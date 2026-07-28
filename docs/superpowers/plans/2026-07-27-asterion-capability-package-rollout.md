# Asterion Capability Package Rollout Plan

> **Superseded by Plan 4 Task 5:** Retired global DCI launcher/orchestrator references in this historical document are replaced by the generic benchmark host and package-owned benchmark bindings.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the approved source-neutral Asterion capability-package architecture without retaining obsolete DCI-named generic protocols or global DCI benchmark machinery.

**Architecture:** This rollout is split into four independently reviewable plans. Each plan leaves the repository provider-free, buildable, and testable. Later plans consume only the public interfaces produced by earlier plans.

**Tech Stack:** Python 3.10+, `unittest`, JSON Schema Draft 2020-12, TypeScript, `importlib.metadata`, Hatchling, shell-free Python orchestration.

## Global Constraints

- There is no compatibility layer for `dci.agent-runtime/v1`, `dci.package/v1`, or `dci.assembly/v1`.
- Built-in, installed-distribution, and local-directory forms resolve to the same immutable `InstalledCapabilityPackage`.
- Portable manifests contain no executable paths, commands, prompts, credentials, provider configuration, environment values, private paths, or mutable state.
- Package, capability, suite, implementation, and resource versions are exact; arrays are sorted and unique.
- Multiple sources never use hidden precedence; an exact source lock is required to resolve ambiguity.
- Listing and metadata description do not import provider factories.
- Generic framework modules import and name no DCI concept.
- Provider-backed benchmarks, downloads, setup, and full datasets are prohibited during implementation verification.

---

## Plan dependency graph

```text
Plan 1: protocol foundation
    -> Plan 2: package sources and public SDK
        -> Plan 3: generic benchmark subsystem
            -> Plan 4: DCI external-first/builtin migration
```

## Executable plans

1. [Protocol foundation](2026-07-27-asterion-capability-protocol-foundation.md)
   - Hard-renames the generic runtime, capability, and assembly protocols.
   - Adds capability-package, benchmark-suite, source, and lock contracts.
   - Migrates canonical schemas, Python, TypeScript, fixtures, manifests, and assemblies together.

2. [Capability package sources and SDK](2026-07-27-asterion-capability-package-sources.md)
   - Implements portable payload identity and source-neutral installed-package values.
   - Adds built-in, installed-distribution, and explicit-local-directory adapters.
   - Adds exact source locking, metadata-only discovery, public SDK, and author conformance tools.

3. [Generic benchmark subsystem](2026-07-27-asterion-generic-benchmark-subsystem.md)
   - Extracts domain-neutral planning, execution, cancellation, evidence, progress, and resume.
   - Resolves suite manifests to exact task bindings.
   - Adds the generic `asterion benchmark` host surface.

4. [DCI capability package migration](2026-07-27-dci-capability-package-migration.md)
   - Builds DCI as a complete external-form-compatible payload.
   - Materializes the same payload as built-in.
   - Removes `asterion.dci`, root DCI benchmark tools, and launchers.
   - Proves external and built-in form identity and behavior equivalence.

## Deferred work with a fresh design gate

Archive and registry forms are not hidden in any current task. After Plans 1-4
pass, create separate security-reviewed specifications for:

- archive canonicalization and traversal protection;
- content-addressed cache lifecycle;
- registry namespaces and publisher signatures;
- offline and revocation behavior.

The source interfaces in Plan 2 reserve these forms without implementing
network access.

## Rollout completion gate

Run from the merged result:

```bash
uv run python -m unittest discover -s tests -v
make check
make promotion-check
```

Expected:

- all commands exit `0`;
- provider operations are `0`;
- full dataset is `no`;
- `rg -n 'dci\.(agent-runtime|package|assembly)/v1' schemas src packages tests` returns no matches;
- `test ! -d src/asterion/dci`;
- `test ! -e tools/dci_benchmark_orchestrator.py`;
- `test ! -e tools/run_dci_benchmarks.py`;
- `test ! -e scripts/run_dci_benchmarks.sh`;
- no DCI benchmark launcher remains below root `scripts/`.
