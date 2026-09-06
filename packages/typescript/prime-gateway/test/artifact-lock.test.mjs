import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
  lstat,
  mkdir,
  mkdtemp,
  readFile,
  rename,
  rm,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { promisify } from "node:util";
import { execFile as execFileCallback } from "node:child_process";
import test from "node:test";

import {
  PrimeArtifactCompatibilityError,
  loadPrimeArtifactLock,
  verifyPrimeArtifact,
} from "../dist/src/artifact-lock.js";

const execFile = promisify(execFileCallback);
const shippedLockUrl = new URL(
  "../resources/prime-artifact-lock.json",
  import.meta.url,
);
const expectedFiles = Object.freeze({
  "package-lock.json":
    "39ee303bca10c0933cf917275613c8f44099f50de1650a5c356e7cda02b701e8",
  "packages/coding-agent/package.json":
    "4e49f896d35be953c7939c2daaf5fcf884092f3b10370778e1643a54185c4033",
  "packages/coding-agent/src/modes/daemon/daemon-client.ts":
    "5b2dcbd5b65697ccae5a80a6e491592afd8d60cde0f93d6ce0091b02eba03d1d",
  "packages/coding-agent/src/modes/daemon/daemon-protocol.ts":
    "55200bf1fb1b979ef1864391f1ba3b74737bfbaf89de6d0c64721a8faddbe989",
  "packages/coding-agent/dist/modes/daemon/daemon-mode.js":
    "b4624b7682c158a690fb1e1ab42b139b25184f893263bc2bfec2ca92776f0138",
  "packages/coding-agent/dist/index.js":
    "0555400963ce5c9fa3059c3ed571748715d3ddda3830085eb8f12da00708d49b",
  "packages/coding-agent/dist/core/auth-storage.js":
    "fa45c9ed883363475bbca80839ec42d518597c3671d2cda9d320f083f1393c76",
  "packages/coding-agent/dist/core/settings-manager.js":
    "867be3ac28592431d772f9ffdbd3d5a2e24dc2f9932c2de1baa41a4d2d8cfe64",
  "packages/ai/dist/utils/event-stream.js":
    "adbad06bccc10c7a472ac202133754486318a2c557ffe6a198485f122504522d",
  "prime-agent.sh":
    "0ceef94210da44aa2cb232fb18fd215c5a25caf7b652531856c5a90af01df09d",
});

function sha256(value) {
  return createHash("sha256").update(value).digest("hex");
}

async function writeFixtureFile(root, relativePath, value) {
  const target = join(root, relativePath);
  await mkdir(dirname(target), { recursive: true });
  await writeFile(target, value);
}

async function createFixture() {
  const root = await mkdtemp(join(tmpdir(), "asterion-prime-artifact-"));
  const contents = {
    "package-lock.json": JSON.stringify({
      name: "prime-agent",
      version: "0.7.1",
      lockfileVersion: 3,
      packages: {
        "": { name: "prime-agent", version: "0.7.1" },
        "packages/coding-agent": {
          name: "@earendil-works/pi-coding-agent",
          version: "0.7.1",
        },
      },
    }),
    "packages/coding-agent/package.json": JSON.stringify({
      name: "@earendil-works/pi-coding-agent",
      version: "0.7.1",
    }),
    "packages/coding-agent/src/modes/daemon/daemon-client.ts":
      "export const fixtureClient = true;\n",
    "packages/coding-agent/src/modes/daemon/daemon-protocol.ts":
      "export const DAEMON_PROTOCOL_VERSION = 7;\n",
    "prime-agent.sh": "#!/bin/sh\nexit 0\n",
  };
  for (const [relativePath, value] of Object.entries(contents)) {
    await writeFixtureFile(root, relativePath, value);
  }
  await chmod(join(root, "prime-agent.sh"), 0o755);
  const lock = {
    format: "asterion.prime-artifact-lock/v1",
    source_commit: "a18809e00ea30638584d87b3afea7285a9d7296c",
    package_name: "@earendil-works/pi-coding-agent",
    package_version: "0.7.1",
    daemon_protocol: 7,
    daemon_schema_revision: 14,
    daemon_schema_id: "protocol-7-schema-14-816309b1cd50",
    rlm_runtime: {
      entry: "packages/coding-agent/dist/bundle/cli.js",
      binding_chunk: "packages/coding-agent/dist/bundle/cli.js",
      patch_sha256: "0".repeat(64),
      closure: { "packages/coding-agent/dist/bundle/cli.js": "1".repeat(64) },
      derived_closure: { "packages/coding-agent/dist/bundle/cli.js": "2".repeat(64) },
    },
    files: Object.fromEntries(
      Object.entries(contents).map(([name, value]) => [name, sha256(value)]),
    ),
  };
  return {
    root,
    lock,
    async cleanup() {
      await rm(root, { force: true, recursive: true });
    },
  };
}

async function initializeGitFixture(fixture) {
  await writeFile(join(fixture.root, "tracked-metadata.txt"), "clean");
  await execFile("git", ["init", "--quiet"], { cwd: fixture.root });
  await execFile("git", ["config", "user.name", "Asterion Test"], {
    cwd: fixture.root,
  });
  await execFile("git", ["config", "user.email", "asterion@example.invalid"], {
    cwd: fixture.root,
  });
  await execFile("git", ["add", "."], { cwd: fixture.root });
  await execFile("git", ["commit", "--quiet", "-m", "fixture"], {
    cwd: fixture.root,
  });
  const { stdout } = await execFile("git", ["rev-parse", "HEAD"], {
    cwd: fixture.root,
  });
  fixture.lock.source_commit = stdout.trim();
}

async function assertIncompatible(action, forbidden = []) {
  await assert.rejects(action, (error) => {
    assert.ok(error instanceof PrimeArtifactCompatibilityError);
    assert.equal(error.message, "Prime artifact is incompatible");
    for (const value of forbidden) {
      assert.equal(error.message.includes(value), false);
    }
    return true;
  });
}

test("ships the exact pinned Prime source artifact lock", async () => {
  const lock = await loadPrimeArtifactLock(shippedLockUrl);

  assert.equal(lock.format, "asterion.prime-artifact-lock/v1");
  assert.equal(lock.source_commit, "a18809e00ea30638584d87b3afea7285a9d7296c");
  assert.deepEqual(
    Object.fromEntries(Object.entries(lock.files).filter(([key]) => key in expectedFiles)),
    expectedFiles,
  );
  assert.equal(lock.rlm_runtime.entry, "packages/coding-agent/dist/bundle/cli.js");
  assert.ok(Object.isFrozen(lock));
  assert.ok(Object.isFrozen(lock.files));
});

test("accepts only the pinned clean source artifact", async () => {
  const fixture = await createFixture();
  try {
    await initializeGitFixture(fixture);
    const evidence = await verifyPrimeArtifact(fixture.root, fixture.lock);
    assert.deepEqual(evidence, {
      commit: fixture.lock.source_commit,
      packageName: "@earendil-works/pi-coding-agent",
      packageVersion: "0.7.1",
      protocolVersion: 7,
      schemaRevision: 14,
      schemaId: "protocol-7-schema-14-816309b1cd50",
      fileDigests: fixture.lock.files,
    });
    assert.equal(JSON.stringify(evidence).includes(fixture.root), false);

    const sentinel = "SENTINEL_SECRET_CHANGED_SOURCE";
    await writeFile(join(fixture.root, "prime-agent.sh"), sentinel);
    await assertIncompatible(
      () => verifyPrimeArtifact(fixture.root, fixture.lock),
      [fixture.root, sentinel],
    );
  } finally {
    await fixture.cleanup();
  }
});

test("rejects a source export without Git metadata", async () => {
  const fixture = await createFixture();
  try {
    await assertIncompatible(
      () => verifyPrimeArtifact(fixture.root, fixture.lock),
      [fixture.root],
    );
  } finally {
    await fixture.cleanup();
  }
});

test("rejects missing, symlinked, and non-regular locked files without paths", async () => {
  for (const kind of ["missing", "symlink", "directory"]) {
    const fixture = await createFixture();
    const target = join(fixture.root, "prime-agent.sh");
    try {
      await rm(target);
      if (kind === "symlink") {
        await symlink(join(fixture.root, "package-lock.json"), target);
      } else if (kind === "directory") {
        await mkdir(target);
      }
      await assertIncompatible(
        () => verifyPrimeArtifact(fixture.root, fixture.lock),
        [fixture.root, target],
      );
    } finally {
      await fixture.cleanup();
    }
  }
});

test("rejects a locked file reached through a symlinked parent", async () => {
  const fixture = await createFixture();
  const modesRoot = join(
    fixture.root,
    "packages/coding-agent/src/modes",
  );
  try {
    await rename(join(modesRoot, "daemon"), join(modesRoot, "daemon-real"));
    await symlink("daemon-real", join(modesRoot, "daemon"), "dir");
    await assertIncompatible(
      () => verifyPrimeArtifact(fixture.root, fixture.lock),
      [fixture.root, modesRoot],
    );
  } finally {
    await fixture.cleanup();
  }
});

test("rejects package identity and every locked digest mismatch", async () => {
  const fixture = await createFixture();
  try {
    for (const field of ["name", "version"]) {
      const packagePath = join(
        fixture.root,
        "packages/coding-agent/package.json",
      );
      const packageJson = JSON.parse(await readFile(packagePath, "utf8"));
      packageJson[field] = "wrong";
      const changed = JSON.stringify(packageJson);
      await writeFile(packagePath, changed);
      await assertIncompatible(() =>
        verifyPrimeArtifact(fixture.root, {
          ...fixture.lock,
          files: {
            ...fixture.lock.files,
            "packages/coding-agent/package.json": sha256(changed),
          },
        }),
      );
      await writeFixtureFile(
        fixture.root,
        "packages/coding-agent/package.json",
        JSON.stringify({
          name: "@earendil-works/pi-coding-agent",
          version: "0.7.1",
        }),
      );
    }

    const lockPath = join(fixture.root, "package-lock.json");
    const packageLock = JSON.parse(await readFile(lockPath, "utf8"));
    packageLock.packages["packages/coding-agent"].version = "wrong";
    const changedLock = JSON.stringify(packageLock);
    await writeFile(lockPath, changedLock);
    await assertIncompatible(() =>
      verifyPrimeArtifact(fixture.root, {
        ...fixture.lock,
        files: {
          ...fixture.lock.files,
          "package-lock.json": sha256(changedLock),
        },
      }),
    );
    await writeFixtureFile(
      fixture.root,
      "package-lock.json",
      JSON.stringify({
        name: "prime-agent",
        version: "0.7.1",
        lockfileVersion: 3,
        packages: {
          "": { name: "prime-agent", version: "0.7.1" },
          "packages/coding-agent": {
            name: "@earendil-works/pi-coding-agent",
            version: "0.7.1",
          },
        },
      }),
    );

    for (const relativePath of Object.keys(fixture.lock.files)) {
      const original = await readFile(join(fixture.root, relativePath));
      await writeFile(join(fixture.root, relativePath), Buffer.concat([original, Buffer.from("x")]));
      await assertIncompatible(() => verifyPrimeArtifact(fixture.root, fixture.lock));
      await writeFile(join(fixture.root, relativePath), original);
    }
  } finally {
    await fixture.cleanup();
  }
});

test("rejects dirty or wrong-commit git worktrees", async () => {
  const fixture = await createFixture();
  try {
    await initializeGitFixture(fixture);
    await verifyPrimeArtifact(fixture.root, fixture.lock);
    await writeFile(join(fixture.root, "tracked-metadata.txt"), "dirty");
    await assertIncompatible(() => verifyPrimeArtifact(fixture.root, fixture.lock));
    await execFile("git", ["checkout", "--quiet", "--", "tracked-metadata.txt"], {
      cwd: fixture.root,
    });
    await writeFile(join(fixture.root, "untracked-metadata.txt"), "dirty");
    await assertIncompatible(() => verifyPrimeArtifact(fixture.root, fixture.lock));
    await rm(join(fixture.root, "untracked-metadata.txt"));
    await assertIncompatible(() =>
      verifyPrimeArtifact(fixture.root, {
        ...fixture.lock,
        source_commit: "0".repeat(40),
      }),
    );
  } finally {
    await fixture.cleanup();
  }
});

test("rejects malformed locks before touching a source root", async () => {
  const fixture = await createFixture();
  try {
    const badLockUrl = new URL("malformed-lock.json", `file://${fixture.root}/`);
    await writeFile(
      badLockUrl,
      JSON.stringify({ ...fixture.lock, unexpected: "SENTINEL_SECRET" }),
    );
    await assertIncompatible(() => loadPrimeArtifactLock(badLockUrl), [fixture.root]);
    assert.equal((await lstat(fixture.root)).isDirectory(), true);
  } finally {
    await fixture.cleanup();
  }
});
