import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, realpath } from "node:fs/promises";
import test from "node:test";

import { loadPrimeClientModule } from "../dist/src/main.js";
import {
  PRIME_CLIENT_ARTIFACT_LOCK_DIGEST,
  PRIME_CLIENT_BUNDLE_DIGEST,
  PRIME_CLIENT_MODULE_LOCK_DIGEST,
} from "../dist/src/gateway.js";

const sourceCommit = "a18809e00ea30638584d87b3afea7285a9d7296c";
const resources = new URL("../resources/", import.meta.url);
const primeRoot = await realpath(new URL("../../../../3th-party/prime-agent", import.meta.url));
const specifications = {
  core: [2, 2], protocols: [2, 2], interactive: [4, 4], "export-share": [1, 1],
};

test("loads only the exact locked Prime client bundle and emits body-free package receipts", async () => {
  const paths = {
    artifactLockPath: await realpath(new URL("prime-artifact-lock.json", resources)),
    bundlePath: await realpath(new URL("prime-client-module.mjs", resources)),
    moduleLockPath: await realpath(new URL("prime-client-module-lock.json", resources)),
  };
  const [artifact, bundle, lock] = await Promise.all([
    readFile(paths.artifactLockPath), readFile(paths.bundlePath), readFile(paths.moduleLockPath),
  ]);
  assert.equal(createHash("sha256").update(artifact).digest("hex"), PRIME_CLIENT_ARTIFACT_LOCK_DIGEST);
  assert.equal(createHash("sha256").update(bundle).digest("hex"), PRIME_CLIENT_BUNDLE_DIGEST);
  assert.equal(createHash("sha256").update(lock).digest("hex"), PRIME_CLIENT_MODULE_LOCK_DIGEST);
  const binding = await loadPrimeClientModule(paths);
  for (const [packageId, [featureCount, scenarioCount]] of Object.entries(specifications)) {
    const receipt = await binding.module.runClientPackage(Object.freeze({
      artifactLockDigest: PRIME_CLIENT_ARTIFACT_LOCK_DIGEST, format: "asterion.prime-client-frame/v1",
      moduleLockDigest: PRIME_CLIENT_MODULE_LOCK_DIGEST, package: packageId, primeRoot, sourceCommit,
    }));
    assert.equal(receipt.featureCount, featureCount);
    assert.equal(receipt.scenarioCount, scenarioCount);
    assert.equal(receipt.providerOperations, 0);
    assert.equal(receipt.credentialReads, 0);
    assert.equal(receipt.retainedProcesses, 0);
    assert.equal(receipt.networkRequests, 0);
    assert.equal(receipt.scenarioEvidence.length, 11);
    assert.equal(receipt.scenarioEvidence.every((item) => /^[0-9a-f]{64}$/u.test(item.digest)), true);
    assert.equal(JSON.stringify(receipt).includes("SENTINEL_PRIVATE_VALUE"), false);
  }
});

test("requires an explicit physical external Prime root instead of a repository-relative import", async () => {
  const paths = {
    artifactLockPath: await realpath(new URL("prime-artifact-lock.json", resources)),
    bundlePath: await realpath(new URL("prime-client-module.mjs", resources)),
    moduleLockPath: await realpath(new URL("prime-client-module-lock.json", resources)),
  };
  const binding = await loadPrimeClientModule(paths);
  await assert.rejects(
    binding.module.runClientPackage(Object.freeze({
      artifactLockDigest: PRIME_CLIENT_ARTIFACT_LOCK_DIGEST, format: "asterion.prime-client-frame/v1",
      moduleLockDigest: PRIME_CLIENT_MODULE_LOCK_DIGEST, package: "core", sourceCommit,
    })),
  );
  const bundle = await readFile(paths.bundlePath, "utf8");
  assert.equal(bundle.includes("../../../../3th-party/prime-agent"), false);
});
