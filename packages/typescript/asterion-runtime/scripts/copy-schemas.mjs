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
const destination = `${packageRoot}/dist/schemas`;

rmSync(destination, { force: true, recursive: true });
mkdirSync(destination, { recursive: true });
cpSync(source, destination, { recursive: true });
cpSync(capabilityManifestSource, `${destination}/capability-manifest.schema.json`);
cpSync(
  assemblyManifestSource,
  `${destination}/application-assembly.schema.json`,
);
