import { copyFileSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

const packageRoot = resolve(fileURLToPath(new URL("..", import.meta.url)));
const built = resolve(packageRoot, "dist/ipython-extension.mjs");
const bundled = resolve(
  packageRoot,
  "../../../src/asterion/applications/prime/resources/ipython-extension.mjs",
);

if (process.argv[2] === "--write") {
  copyFileSync(built, bundled);
  process.stdout.write(`${bundled}\n`);
  process.exit(0);
}

const expected = readFileSync(built);
const actual = readFileSync(bundled);
if (!expected.equals(actual)) {
  console.error("Prime extension resource is stale; run npm run sync-resource.");
  process.exit(1);
}
