# Cross-Package Extension Evidence

> Status: proposed for W3a implementation. Protocol impact: none.

## Purpose

W3a proves that Asterion composes executable capabilities from two separately
built, different-domain extension wheels. The proof runs from installed wheels
outside the repository source tree and uses the same public SDK, source,
assembly, runner, and CLI path established by W2.

The two capability owners are:

| Distribution | Package | Capability | Domain |
|---|---|---|---|
| `asterion-acme-sample-extension` | `acme.sample@1.0.0` | `acme.research@1.0.0` | local synthetic research |
| `asterion-contoso-audit-extension` | `contoso.audit@1.0.0` | `contoso.audit-record@1.0.0` | result audit and observation |

The Contoso wheel is independently built and owns the integration application
`contoso.audited-research@1.0.0`. Its wheel metadata declares both the Asterion
SDK range and the exact Acme extension dependency. Dependency metadata does not
select or install packages at runtime; the test installs exact wheel paths and
Asterion resolves exact package identities.

## Portable Graph

The Acme research capability emits `acme.research.completed` and produces
`application/vnd.acme.research+json`. The Contoso audit capability consumes
both edges, which establishes one portable dependency from Acme to Contoso.
Contoso emits `contoso.audit.completed`, produces
`application/vnd.contoso.audit+json`, and provides `audit.local`.

The Contoso assembly contains sorted, exact references to both package and
capability versions. It declares no host capabilities, policies, events,
artifacts, configuration, command, provider value, or executable path. Static
composition must produce this order regardless of distribution installation or
entry-point enumeration order:

```text
acme.research@1.0.0
  -> contoso.audit-record@1.0.0
```

Both are executable kinds and therefore require exactly one implementation
binding. The Acme factory returns only the Acme binding; the Contoso factory
returns only the Contoso binding. The selected application provider declares
both exact `CapabilityPackageRef` values.

W3a closes one framework ownership gap exposed by this case. A provider's
self-reported catalog roots are not ownership authority. After loading a
selected provider, the host creates a fresh process-local installed-package
snapshot whose owned capability refs come only from the already prepared,
digest-verified portable payload manifest. Provider code cannot set that
authority field through the public constructor.

Composition validates each authoritative ref set against the manifests beneath
that package's catalog roots, then validates the package's implementation tuple
against the same set. Checking a binding against the union of all selected
package manifests is insufficient because it would allow one package to
impersonate another package's implementation. Multi-package composition rejects
unbound raw/injected package values, so direct injection cannot bypass source
preparation. Existing single-package host/test injection remains compatible
because it cannot impersonate another selected package; source-loaded packages
use the stronger check in every cardinality.

A focused negative test assigns both another package's catalog root and binding
to the hostile package. Resolution rejects it before runtime construction or
either implementation executes. The existing complete exact-binding check still
runs after this per-package ownership check. This is a process-local Python
integration value and does not change a portable manifest or v1 wire schema.

## Runtime Boundary

The integration application owns a deterministic provider-free
`contoso.inline` runtime binding. It implements the public
`AgentRuntimeClient` contract, advertises no host capabilities, and emits a
valid started/text/completed lifecycle. It reads no environment values,
runtime options, host services, files, network, or credentials. Its factory
rejects any provider, application, version, runtime, option, or service mismatch
with a fixed `RuntimeFactoryError`.

Acme research remains runtime-neutral: it validates the canonical three-event
completed lifecycle and requires a non-empty `text.delta`, but does not require
an adapter-specific text value. It projects none of that text. This preserves
the W2 `acme.inline` behavior and permits W3b to exercise the same neutral
capability through another declared-compatible adapter.

The Contoso implementation never invokes the runtime again. It receives only
the declared upstream Acme event and artifact from the sequential runner,
checks their exact public shapes, and emits a fixed public audit result. It does
not receive the application input in upstream outputs and does not expose it.

## Wheel Layout and Public Imports

The second fixture lives at
`tests/fixtures/extensions/contoso_audit_distribution/`:

```text
pyproject.toml
payload/
  capability-package.json
  capabilities/audit-record.json
application/
  assembly.json
src/contoso_audit_extension/
  __init__.py
  application.py
  capability.py
  runtime.py
```

Its Python files may import only the standard library, their own package,
`asterion.capability_sdk`, and `asterion.application_sdk`. The wheel publishes
one exact capability-package entry point, one application-provider entry point,
and one exact application-index entry. Resources use the same package-owned
roots as W2.

## Acceptance Evidence

`make test.cross-package-extension` is the W3a acceptance command. It builds
the core, Acme, and Contoso wheels once, then runs the installed console script
in clean virtual environments with repository paths removed:

1. install core, Acme, then Contoso and execute the exact application;
2. install core, Contoso, then Acme and execute the same application;
3. install only core and Contoso and prove execution fails before runtime or
   capability work with the fixed CLI error.

The two successful results must be byte-for-byte identical for a fixed run ID.
They contain exactly two events and two artifacts in Acme-then-Contoso order,
with unique artifact IDs and no input, environment, path, poison, or provider
body. The missing-Acme result has exit code 2, empty stdout, and exactly
`asterion: command failed\n` on stderr. Loading the selected Contoso application
provider and importing its runtime module are expected metadata steps. Guards
inside the runtime factory and selected capability-provider module prove that
the runtime client is never constructed or run and no capability implementation
is loaded or executed on that failure path.

A focused in-process boundary test supplies a package with the other package's
catalog root and implementation. Provider resolution rejects the misowned
binding before runtime construction. This test verifies framework ownership;
the isolated wheel test verifies real distribution and CLI integration.

The test also inspects both extension wheels for exact dependency and
entry-point metadata and parses their Python sources to enforce the public SDK
import boundary. It does not run product tests, Docker, models, benchmarks,
promotion, or broad release regression.

## Compatibility Decision

W3a uses existing `asterion.capability/v1`,
`asterion.capability-package/v1`, `asterion.application-assembly/v1`, and
`asterion.agent-runtime/v1` values unchanged. Event and artifact consumption
already express the required cross-package edge. Any limitation found during
implementation is recorded for W4 rather than added to a closed v1 contract.
