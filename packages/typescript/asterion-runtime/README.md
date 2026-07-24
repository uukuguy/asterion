# `@dci/agent-runtime`

Public TypeScript host contract for DCI Agent Runtime Protocol v1 and portable
DCI Framework Package manifests.

The package exports portable runtime-manifest, run-request, event, and asynchronous
client types. Runtime and package validators use canonical schemas copied from
the repository's `schemas/` directory during the build. Package validation also
enforces canonical sorted edge arrays. It has no Pi, Claude Code, provider, or
transport dependency.

```ts
import {
  validateRuntimeManifest,
  validatePackageManifest,
  type AgentRuntimeClient,
  type PackageManifest,
  type RunRequest,
} from "@dci/agent-runtime";
```

From the repository root, run its complete build and shared-fixture suite with:

```bash
make test-typescript-host
```
