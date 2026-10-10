import { copyFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const artifacts = ["ipython-extension.mjs", "p7-research-extension.mjs", "p7-legacy-extension.mjs"];
for (const artifact of artifacts) {
  const built = resolve(packageRoot, "dist", artifact);
  const bundled = resolve(packageRoot, "../../../src/asterion/applications/prime/resources", artifact);
  if (process.argv[2] === "--write") {
    copyFileSync(built, bundled);
    process.stdout.write(`${bundled}\n`);
  } else if (!readFileSync(built).equals(readFileSync(bundled))) {
    console.error("Prime extension resource is stale; run npm run sync-resource.");
    process.exit(1);
  }
}
