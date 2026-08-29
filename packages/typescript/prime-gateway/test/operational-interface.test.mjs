import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { copyFile, mkdtemp, readFile, realpath, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { loadPrimeOperationalModule } from "../dist/src/main.js";
import {
  PRIME_OPERATIONAL_BUNDLE_DIGEST,
  PRIME_OPERATIONAL_MODULE_LOCK_DIGEST,
} from "../dist/src/gateway.js";

const resources = new URL("../resources/", import.meta.url);

test("operational loader admits only the checked-in locked resource module", async () => {
  const paths = {
    bundlePath: await realpath(new URL("prime-operational-module.mjs", resources)),
    moduleLockPath: await realpath(new URL("prime-operational-module-lock.json", resources)),
  };
  const [bundle, lock] = await Promise.all([readFile(paths.bundlePath), readFile(paths.moduleLockPath)]);
  assert.equal(createHash("sha256").update(bundle).digest("hex"), PRIME_OPERATIONAL_BUNDLE_DIGEST);
  assert.equal(createHash("sha256").update(lock).digest("hex"), PRIME_OPERATIONAL_MODULE_LOCK_DIGEST);
  const binding = await loadPrimeOperationalModule(paths);
  assert.deepEqual(Object.keys(binding.module).sort(), ["runOperationalPackage", "verifyOperationalLocks"]);
  assert.equal(typeof binding.module.runOperationalPackage, "function");
  assert.equal(typeof binding.module.verifyOperationalLocks, "function");
  assert.ok(Object.isFrozen(binding.module));
});

test("operational loader rejects a drifted resource before import", async () => {
  const parent = await mkdtemp(join(tmpdir(), "asterion-prime-operational-lock-"));
  try {
    const paths = { bundlePath: join(parent, "module.mjs"), moduleLockPath: join(parent, "lock.json") };
    await Promise.all([
      writeFile(paths.bundlePath, "export const SENTINEL_PRIVATE_MODULE_DRIFT = true;\n", { mode: 0o600 }),
      copyFile(new URL("prime-operational-module-lock.json", resources), paths.moduleLockPath),
    ]);
    await assert.rejects(loadPrimeOperationalModule(paths), (error) =>
      error.message === "Prime gateway operation failed" &&
      !error.message.includes("SENTINEL_PRIVATE_MODULE_DRIFT") &&
      !error.message.includes(parent),
    );
  } finally {
    await rm(parent, { force: true, recursive: true });
  }
});
