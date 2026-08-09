import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  chmod,
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
