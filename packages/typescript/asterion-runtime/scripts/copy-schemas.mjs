import { cpSync, mkdirSync, rmSync } from "node:fs";
import { fileURLToPath } from "node:url";

const packageRoot = fileURLToPath(new URL("..", import.meta.url));
const source = fileURLToPath(
  new URL("../../../../schemas/agent-runtime/v1", import.meta.url),
);
const packageManifestSource = fileURLToPath(
  new URL(
    "../../../../schemas/packages/v1/package-manifest.schema.json",
    import.meta.url,
  ),
);
const assemblyManifestSource = fileURLToPath(
  new URL("../../../../schemas/assembly/v1/assembly.schema.json", import.meta.url),
);
const destination = `${packageRoot}/dist/schemas`;

rmSync(destination, { force: true, recursive: true });
mkdirSync(destination, { recursive: true });
cpSync(source, destination, { recursive: true });
cpSync(packageManifestSource, `${destination}/package-manifest.schema.json`);
cpSync(assemblyManifestSource, `${destination}/assembly.schema.json`);
