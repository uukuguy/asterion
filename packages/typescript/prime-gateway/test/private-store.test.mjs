import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
  mkdir,
  mkdtemp,
  readFile,
  readdir,
  rm,
  stat,
  symlink,
  writeFile,
} from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  PrivateValueInvalidError,
  PrivateValueStore,
  PrivateValueWriteError,
} from "../dist/src/index.js";

async function temporaryStoreRoot() {
  const parent = await mkdtemp(join(tmpdir(), "asterion-private-store-"));
  return {
    parent,
    root: join(parent, "gateway"),
    async cleanup() {
      await rm(parent, { force: true, recursive: true });
    },
  };
}

function valuePath(root, reference) {
  return join(
    root,
    "private",
    "values",
    `${reference.slice("private:".length)}.value`,
  );
}

function bindingsPath(root) {
  return join(root, "private", "input-bindings");
}

test("private values use opaque references and exact kind projections", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const sentinel = "SENTINEL_SECRET_INPUT";
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    const inputRef = await values.putInput(sentinel);
    const digest = createHash("sha256").update(sentinel).digest("hex");
    assert.match(inputRef, /^private:[0-9a-f-]{36}$/);
    assert.equal(inputRef.includes(digest), false);
    assert.equal(await values.readInput(inputRef), sentinel);

    const projection = {
      receiptRef: "receipt-1",
      artifactIds: ["artifact-1"],
      mediaTypes: ["text/plain"],
    };
    const resultRef = await values.putResult(projection);
    const restoredProjection = await values.readResult(resultRef);
    assert.deepEqual(restoredProjection, projection);
    assert.ok(Object.isFrozen(restoredProjection));
    assert.ok(Object.isFrozen(restoredProjection.artifactIds));

    const capsule = Buffer.from("SENTINEL_PRIVATE_CAPSULE");
    const capsuleRef = await values.putCapsule(capsule);
    assert.deepEqual(await values.readCapsule(capsuleRef), capsule);

    assert.equal(String(values).includes(sentinel), false);
    assert.equal((await stat(fixtureRoot.root)).mode & 0o777, 0o700);
    for (const reference of [inputRef, resultRef, capsuleRef]) {
      assert.equal((await stat(valuePath(fixtureRoot.root, reference))).mode & 0o777, 0o600);
    }
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values bind public input references durably and reject conflicts", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    const first = await values.bindInputReference(
      "command-1",
      "goal-ref-1",
      "SENTINEL_PRIVATE_GOAL",
    );
    const replay = await values.bindInputReference(
      "command-1",
      "goal-ref-1",
      "SENTINEL_PRIVATE_GOAL",
    );
    assert.equal(replay, first);
    assert.equal(await values.readBoundInputReference("goal-ref-1"), "SENTINEL_PRIVATE_GOAL");

    const reopened = await PrivateValueStore.open(fixtureRoot.root);
    assert.equal(
      await reopened.bindInputReference(
        "command-1",
        "goal-ref-1",
        "SENTINEL_PRIVATE_GOAL",
      ),
      first,
    );
    assert.equal(await reopened.readBoundInputReference("goal-ref-1"), "SENTINEL_PRIVATE_GOAL");

    await assert.rejects(
      reopened.bindInputReference(
        "command-1",
        "goal-ref-1",
        "SENTINEL_DIFFERENT_GOAL",
      ),
      (error) => {
        assert.ok(error instanceof PrivateValueInvalidError);
        assert.equal(error.message.includes("SENTINEL"), false);
        return true;
      },
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values fail closed when the binding root is replaced by a symlink", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    await values.bindInputReference(
      "command-1",
      "goal-ref-1",
      "SENTINEL_PRIVATE_GOAL",
    );
    const external = join(fixtureRoot.parent, "external-bindings");
    await mkdir(external, { mode: 0o700 });
    await rm(bindingsPath(fixtureRoot.root), { force: true, recursive: true });
    await symlink(external, bindingsPath(fixtureRoot.root));

    await assert.rejects(
      values.readBoundInputReference("goal-ref-1"),
      PrivateValueInvalidError,
    );
    await assert.rejects(
      values.bindInputReference(
        "command-2",
        "goal-ref-2",
        "SENTINEL_PRIVATE_GOAL_2",
      ),
      PrivateValueInvalidError,
    );
    assert.deepEqual(await readdir(external), []);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values fail closed when binding root permissions drift", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    await values.bindInputReference(
      "command-1",
      "goal-ref-1",
      "SENTINEL_PRIVATE_GOAL",
    );
    await chmod(bindingsPath(fixtureRoot.root), 0o755);

    await assert.rejects(
      values.readBoundInputReference("goal-ref-1"),
      PrivateValueInvalidError,
    );
    await assert.rejects(
      values.bindInputReference(
        "command-2",
        "goal-ref-2",
        "SENTINEL_PRIVATE_GOAL_2",
      ),
      PrivateValueInvalidError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values fail closed when binding root is replaced during a write", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    await PrivateValueStore.open(fixtureRoot.root);
    const external = join(fixtureRoot.parent, "external-race-bindings");
    let beforeRenameCount = 0;
    const faulted = await PrivateValueStore.open(fixtureRoot.root, {
      async faultInjector(stage) {
        if (stage === "before_rename") {
          beforeRenameCount += 1;
          if (beforeRenameCount === 2) {
            await mkdir(external, { mode: 0o700 });
            await rm(bindingsPath(fixtureRoot.root), { force: true, recursive: true });
            await symlink(external, bindingsPath(fixtureRoot.root));
          }
        }
      },
    });

    await assert.rejects(
      faulted.bindInputReference(
        "command-1",
        "goal-ref-1",
        "SENTINEL_PRIVATE_GOAL",
      ),
      PrivateValueWriteError,
    );
    assert.deepEqual(await readdir(external), []);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values reject public binding faults before acknowledging", async () => {
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "before_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      await PrivateValueStore.open(fixtureRoot.root);
      let matchingStageCount = 0;
      const faulted = await PrivateValueStore.open(fixtureRoot.root, {
        faultInjector(stage) {
          if (stage === faultStage) {
            matchingStageCount += 1;
            if (matchingStageCount === 2) {
              throw new Error(`SENTINEL_${faultStage}`);
            }
          }
        },
      });

      await assert.rejects(
        faulted.bindInputReference(
          "command-1",
          `goal-ref-${faultStage}`,
          "SENTINEL_PRIVATE_GOAL",
        ),
        (error) => {
          assert.ok(error instanceof PrivateValueWriteError);
          assert.equal(error.message.includes("SENTINEL"), false);
          return true;
        },
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("private values reject command binding faults before acknowledging", async () => {
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "before_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const values = await PrivateValueStore.open(fixtureRoot.root);
      await values.bindInputReference(
        "command-1",
        `goal-ref-${faultStage}`,
        "SENTINEL_PRIVATE_GOAL",
      );
      const faulted = await PrivateValueStore.open(fixtureRoot.root, {
        faultInjector(stage) {
          if (stage === faultStage) {
            throw new Error(`SENTINEL_${faultStage}`);
          }
        },
      });

      await assert.rejects(
        faulted.bindInputReference(
          "command-2",
          `goal-ref-${faultStage}`,
          "SENTINEL_PRIVATE_GOAL",
        ),
        (error) => {
          assert.ok(error instanceof PrivateValueWriteError);
          assert.equal(error.message.includes("SENTINEL"), false);
          return true;
        },
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("private values resync a recovered public binding before retry acknowledgement", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    await PrivateValueStore.open(fixtureRoot.root);
    let firstAttemptDirectorySyncs = 0;
    const faulted = await PrivateValueStore.open(fixtureRoot.root, {
      faultInjector(stage) {
        if (stage === "before_directory_fsync") {
          firstAttemptDirectorySyncs += 1;
          if (firstAttemptDirectorySyncs === 2) {
            throw new Error("SENTINEL_PUBLIC_BINDING_FSYNC");
          }
        }
      },
    });
    await assert.rejects(
      faulted.bindInputReference(
        "command-1",
        "goal-ref-retry",
        "SENTINEL_PRIVATE_GOAL",
      ),
      PrivateValueWriteError,
    );

    let retryDirectorySyncs = 0;
    const retry = await PrivateValueStore.open(fixtureRoot.root, {
      faultInjector(stage) {
        if (stage === "before_directory_fsync") {
          retryDirectorySyncs += 1;
        }
      },
    });

    await retry.bindInputReference(
      "command-1",
      "goal-ref-retry",
      "SENTINEL_PRIVATE_GOAL",
    );

    assert.equal(retryDirectorySyncs, 2);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values resync a recovered command binding before retry acknowledgement", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    await values.bindInputReference(
      "command-1",
      "goal-ref-retry",
      "SENTINEL_PRIVATE_GOAL",
    );
    const faulted = await PrivateValueStore.open(fixtureRoot.root, {
      faultInjector(stage) {
        if (stage === "before_directory_fsync") {
          throw new Error("SENTINEL_COMMAND_BINDING_FSYNC");
        }
      },
    });
    await assert.rejects(
      faulted.bindInputReference(
        "command-2",
        "goal-ref-retry",
        "SENTINEL_PRIVATE_GOAL",
      ),
      PrivateValueWriteError,
    );

    const retryFails = await PrivateValueStore.open(fixtureRoot.root, {
      faultInjector(stage) {
        if (stage === "before_directory_fsync") {
          throw new Error("SENTINEL_RETRY_FSYNC");
        }
      },
    });
    await assert.rejects(
      retryFails.bindInputReference(
        "command-2",
        "goal-ref-retry",
        "SENTINEL_PRIVATE_GOAL",
      ),
      PrivateValueWriteError,
    );

    let retryDirectorySyncs = 0;
    const retry = await PrivateValueStore.open(fixtureRoot.root, {
      faultInjector(stage) {
        if (stage === "before_directory_fsync") {
          retryDirectorySyncs += 1;
        }
      },
    });
    await retry.bindInputReference(
      "command-2",
      "goal-ref-retry",
      "SENTINEL_PRIVATE_GOAL",
    );

    assert.equal(retryDirectorySyncs, 2);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values reject symlink replacement and redact bodies", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const sentinel = "SENTINEL_SECRET_INPUT";
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    const reference = await values.putInput(sentinel);
    const path = valuePath(fixtureRoot.root, reference);
    const target = join(fixtureRoot.parent, "sentinel-target");
    await writeFile(target, sentinel);
    await rm(path);
    await symlink(target, path);

    await assert.rejects(values.readInput(reference), (error) => {
      assert.ok(error instanceof PrivateValueInvalidError);
      assert.equal(error.message, "Prime private value is invalid");
      assert.equal(error.message.includes(sentinel), false);
      assert.equal(error.message.includes(path), false);
      return true;
    });
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values enforce input result and capsule byte limits", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    await assert.rejects(
      values.putInput("x".repeat(1024 * 1024 + 1)),
      PrivateValueInvalidError,
    );
    await assert.rejects(
      values.putResult({
        receiptRef: "receipt-1",
        artifactIds: [`artifact-${"x".repeat(64 * 1024)}`],
        mediaTypes: ["text/plain"],
      }),
      PrivateValueInvalidError,
    );
    await assert.rejects(
      values.putCapsule(Buffer.alloc(8 * 1024 * 1024 + 1)),
      PrivateValueInvalidError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values recover only complete atomic files after injected faults", async () => {
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "before_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      await PrivateValueStore.open(fixtureRoot.root);
      const faulted = await PrivateValueStore.open(fixtureRoot.root, {
        faultInjector(stage) {
          if (stage === faultStage) {
            throw new Error(`SENTINEL_${faultStage}`);
          }
        },
      });
      await assert.rejects(faulted.putInput("private"), (error) => {
        assert.ok(error instanceof PrivateValueWriteError);
        assert.equal(error.message, "Prime private value write failed");
        assert.equal(error.message.includes("SENTINEL"), false);
        return true;
      });

      const reopened = await PrivateValueStore.open(fixtureRoot.root);
      const names = await readdir(join(fixtureRoot.root, "private", "values"));
      for (const name of names.filter((value) => value.endsWith(".value"))) {
        const reference = `private:${name.slice(0, -".value".length)}`;
        assert.equal(await reopened.readInput(reference), "private");
      }
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("private values reject digest corruption wrong modes kinds and headers", async () => {
  for (const mutation of ["digest", "mode", "kind", "header"]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      const values = await PrivateValueStore.open(fixtureRoot.root);
      const reference = await values.putInput("SENTINEL_PRIVATE_BODY");
      const path = valuePath(fixtureRoot.root, reference);
      if (mutation === "digest") {
        const bytes = await readFile(path);
        bytes[bytes.length - 1] ^= 1;
        await writeFile(path, bytes);
        await chmod(path, 0o600);
      } else if (mutation === "mode") {
        await chmod(path, 0o644);
      } else if (mutation === "header") {
        const bytes = await readFile(path);
        const newline = bytes.indexOf(0x0a);
        await writeFile(
          path,
          Buffer.concat([
            bytes.subarray(0, newline),
            Buffer.from(" \n"),
            bytes.subarray(newline + 1),
          ]),
        );
      }
      await assert.rejects(
        mutation === "kind"
          ? values.readCapsule(reference)
          : values.readInput(reference),
        (error) => {
          assert.ok(error instanceof PrivateValueInvalidError);
          assert.equal(error.message, "Prime private value is invalid");
          assert.equal(error.message.includes("SENTINEL"), false);
          return true;
        },
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});
