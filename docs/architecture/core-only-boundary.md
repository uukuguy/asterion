# Core-only Import and Installation Boundary

Asterion's framework must install and import without loading product modules or
requiring product-only Python dependencies. The current milestone keeps one
distribution for compatibility, while making product integration explicit and
optional. Independent product distributions remain a later packaging step.

## Layer ownership

The generic built-in source adapter owns only the source protocol and the
`BuiltinCapabilityRegistration` value. Its constructor requires an explicit,
already snapshotted registration iterable. It does not import or default to a
first-party product table.

The first-party application integration layer owns the controlled-code, DCI,
and Prime package registrations and provider factories. Provider factories
remain lazy: metadata discovery may read exact packaged descriptors, but it
must not import executable provider code. A first-party CLI wrapper injects
this explicit source set into the generic CLI. The generic CLI defaults to the
installed-distribution source only.

```text
first-party console wrapper
  -> generic CLI
  -> explicit first-party built-in source + distribution source

external/core host
  -> generic CLI/API
  -> distribution source or explicitly injected sources
```

Generic benchmark hosts follow the same rule and default to distribution
packages. DCI benchmark integration may inject the first-party built-in source
because that code is product-owned.

## Dependency boundary

The base `asterion` requirement list is empty for W1d. DCI analysis/export and
operator configuration dependencies move to a
`dci` extra; Prime operator configuration dependencies move to a `prime` extra;
the convenience `products` extra contains their union. Development lock state
may still contain these packages, but wheel metadata must not require them for
a base installation.

Application and host-service entry points remain published during this
milestone. Selecting a product without its declared extra may fail at that
selected product boundary. Importing framework packages and using provider-free
core contracts must succeed in a base, dependency-free wheel installation.

## Enforced gate

The core-only gate builds the wheel, installs it with `--no-deps` into an
isolated target, and starts a subprocess whose import path contains only that
target and the standard library. Wheel metadata must contain no unconditional
`Requires-Dist` values.

One checked allowlist covers the complete framework surface: generic top-level
modules plus assembly, benchmarks, capability-package protocol/sources,
capability SDK/catalog/execution, client, control excluding concrete providers,
Pathlight, runner, runtime, services, and workflow evidence. It excludes the
application/product packages, product capability implementations, and concrete
Native/Prime control providers. The isolated subprocess imports every module
in the allowlist, and the static import-boundary check walks that same list.

Static boundary checks reject imports from framework-owned modules into:

- `asterion.applications.controlled_code`, `dci_agent_lite`, or `prime_agent`;
- `asterion.capabilities.controlled_code`, `dci`, or `prime_agent`;
- product control providers or the first-party integration wrapper.

The check covers framework runtime defaults, capability-package sources,
assembly, runner, services, and generic CLI modules. Product-owned modules may
depend on framework modules. The console wrapper may depend on both because it
is an explicit product integration surface.

## Compatibility and follow-on work

`asterion` continues to launch the first-party wrapper so existing controlled,
DCI, and Prime commands retain their source resolution. `asterion.cli:main`
remains the public generic host entry and accepts explicit package sources.
Unscoped `list` remains index-metadata-only and loads no provider. `list
--provider` and `describe` load exactly the explicitly selected provider and
never an adjacent provider; sentinel entry-point tests enforce both boundaries.

W1d closes when the isolated core gate and focused provider-entry-point checks
pass. Moving product modules and resources into separate distributions is
deferred until W2/W3 provide real external wheel consumers and can prove that
split without weakening exact source and entry-point contracts.
