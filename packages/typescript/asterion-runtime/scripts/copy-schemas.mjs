import { cpSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const source = fileURLToPath(
  new URL("../../../../schemas/agent-runtime/v1", import.meta.url),
);
const capabilityManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/capabilities/v1/capability-manifest.schema.json",
    import.meta.url,
  ),
);
const assemblyManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/application-assembly/v1/application-assembly.schema.json",
    import.meta.url,
  ),
);
const capabilityPackageManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/capability-packages/v1/capability-package.schema.json",
    import.meta.url,
  ),
);
const benchmarkSuiteManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/benchmark-suite/v1/benchmark-suite.schema.json",
    import.meta.url,
  ),
);
const capabilitySourceDeclarationSource = fileURLToPath(
  new URL(
    "../../../../schemas/capability-source/v1/source.schema.json",
    import.meta.url,
  ),
);
const capabilitySourceLockSource = fileURLToPath(
  new URL(
    "../../../../schemas/capability-source/v1/lock.schema.json",
    import.meta.url,
  ),
);
const destination = `${packageRoot}/dist/schemas`;

rmSync(destination, { force: true, recursive: true });
mkdirSync(destination, { recursive: true });
cpSync(source, destination, { recursive: true });
cpSync(
  capabilityManifestSource,
  `${destination}/capability-manifest.schema.json`,
);
cpSync(
  assemblyManifestSource,
  `${destination}/application-assembly.schema.json`,
);
cpSync(
  capabilityPackageManifestSource,
  `${destination}/capability-package.schema.json`,
);
cpSync(
  benchmarkSuiteManifestSource,
  `${destination}/benchmark-suite.schema.json`,
);
cpSync(
  capabilitySourceDeclarationSource,
  `${destination}/capability-source.schema.json`,
);
cpSync(
  capabilitySourceLockSource,
  `${destination}/capability-lock.schema.json`,
);
