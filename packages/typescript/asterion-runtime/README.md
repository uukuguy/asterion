# `@dci/agent-runtime`

Public TypeScript host contract for the Asterion protocol family. The npm
package name is retained as a distribution coordinate; it is not a wire
protocol namespace or a compatibility alias.

The package exports portable runtime, capability, capability-package,
application-assembly, benchmark-suite, capability-source, and capability-lock
types and validators. Their exact v1 identities are:

- `asterion.agent-runtime/v1`
- `asterion.capability/v1`
- `asterion.capability-package/v1`
- `asterion.application-assembly/v1`
- `asterion.benchmark-suite/v1`
- `asterion.capability-source/v1`
- `asterion.capability-lock/v1`

Builds copy the canonical repository schemas into `dist/schemas/` as:

- `runtime-manifest.schema.json`
- `run-request.schema.json`
- `event.schema.json`
- `capability-manifest.schema.json`
- `capability-package.schema.json`
- `application-assembly.schema.json`
- `benchmark-suite.schema.json`
- `capability-source.schema.json`
- `capability-lock.schema.json`

The validators enforce closed shapes and canonical sorted, unique arrays. The
package has no Pi, Claude Code, provider, source adapter, transport, or
execution dependency.

```ts
import {
  validateRuntimeManifest,
  validateCapabilityManifest,
  validateCapabilityPackageManifest,
  validateAssemblyManifest,
  type AgentRuntimeClient,
  type CapabilityManifest,
  type CapabilityPackageManifest,
  type RunRequest,
} from "@dci/agent-runtime";
```

From the repository root, run its complete build and shared-fixture suite with:

```bash
make test-typescript
```
