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

function attachmentMetadata(body) {
  return {
    sessionId: "session-1",
    inputId: "input-1",
    attachmentId: "attachment-1",
    mediaType: "image/png",
    sha256: createHash("sha256").update(body).digest("hex"),
    size: body.byteLength,
  };
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

test("private values bind result projections by command and source receipt", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    const projection = {
      receiptRef: "receipt-1",
      artifactIds: ["artifact-1"],
      mediaTypes: ["text/plain"],
    };
    const first = await values.bindResultReference(
      "terminal-action-1",
      "action-1",
      "receipt-1",
      projection,
    );
    const replay = await values.bindResultReference(
      "terminal-action-1",
      "action-1",
      "receipt-1",
      projection,
    );

    assert.equal(replay, first);
    assert.deepEqual(await values.readResult(first), projection);

    const reopened = await PrivateValueStore.open(fixtureRoot.root);
    assert.equal(
      await reopened.bindResultReference(
        "terminal-action-1",
        "action-1",
        "receipt-1",
        projection,
      ),
      first,
    );
    await assert.rejects(
      reopened.bindResultReference(
        "terminal-action-1",
        "action-1",
        "receipt-1",
        {
          receiptRef: "receipt-1",
          artifactIds: ["artifact-2"],
          mediaTypes: ["text/plain"],
        },
      ),
      PrivateValueInvalidError,
    );
    assert.equal(
      await reopened.readBoundResultReference(
        "terminal-action-1",
        "action-1",
        "receipt-1",
      ),
      first,
    );
    await rm(valuePath(fixtureRoot.root, first), { force: true });
    await assert.rejects(
      reopened.readBoundResultReference(
        "terminal-action-1",
        "action-1",
        "receipt-1",
      ),
      PrivateValueInvalidError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private attachment bindings are exact durable and body-free", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const body = Buffer.from("SENTINEL_PRIVATE_ATTACHMENT", "utf8");
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    const metadata = attachmentMetadata(body);
    const first = await values.bindAttachment(metadata, body);
    const replay = await values.bindAttachment(metadata, Buffer.from(body));
    assert.equal(replay, first);
    assert.deepEqual(await values.readBoundAttachment(
      metadata.sessionId,
      metadata.inputId,
      metadata.attachmentId,
    ), {
      ...metadata,
      privateRef: first,
      body,
    });

    const reopened = await PrivateValueStore.open(fixtureRoot.root);
    assert.equal(await reopened.bindAttachment(metadata, body), first);
    await assert.rejects(
      reopened.bindAttachment(
        { ...metadata, mediaType: "image/jpeg" },
        body,
      ),
      PrivateValueInvalidError,
    );
    const bindingFiles = (await readdir(bindingsPath(fixtureRoot.root)))
      .filter((name) => name.startsWith("attachment-") && name.endsWith(".json"));
    assert.equal(bindingFiles.length, 1);
    const bindingText = await readFile(
      join(bindingsPath(fixtureRoot.root), bindingFiles[0]),
      "utf8",
    );
    assert.equal(bindingText.includes("SENTINEL_PRIVATE_ATTACHMENT"), false);
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private bindings coalesce concurrent exact replays", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const body = Buffer.from("concurrent-private-attachment", "utf8");
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    const inputResults = await Promise.allSettled(
      Array.from({ length: 8 }, (_, index) =>
        values.bindInputReference(
          `command-${index + 1}`,
          "shared-name-ref",
          "SENTINEL_SHARED_PRIVATE_NAME",
        ),
      ),
    );
    assert.equal(inputResults.every((result) => result.status === "fulfilled"), true);
    const inputRefs = inputResults.map((result) => result.value);
    assert.equal(new Set(inputRefs).size, 1);

    const metadata = attachmentMetadata(body);
    const attachmentResults = await Promise.allSettled(
      Array.from({ length: 8 }, () =>
        values.bindAttachment(metadata, Buffer.from(body)),
      ),
    );
    assert.equal(
      attachmentResults.every((result) => result.status === "fulfilled"),
      true,
    );
    const attachmentRefs = attachmentResults.map((result) => result.value);
    assert.equal(new Set(attachmentRefs).size, 1);
    assert.deepEqual(
      (await values.readBoundAttachment(
        metadata.sessionId,
        metadata.inputId,
        metadata.attachmentId,
      )).body,
      body,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private attachment recovery selects one exact binding across all faults", async () => {
  const body = Buffer.from("private-attachment", "utf8");
  for (const faultStage of [
    "before_write",
    "after_write",
    "before_rename",
    "after_rename",
    "before_directory_fsync",
    "after_directory_fsync",
  ]) {
    const fixtureRoot = await temporaryStoreRoot();
    try {
      await PrivateValueStore.open(fixtureRoot.root);
      const metadata = attachmentMetadata(body);
      const faulted = await PrivateValueStore.open(fixtureRoot.root, {
        faultInjector(stage) {
          if (stage === faultStage) {
            throw new Error(`SENTINEL_${faultStage}`);
          }
        },
      });
      await assert.rejects(
        faulted.bindAttachment(metadata, body),
        PrivateValueWriteError,
      );

      const reopened = await PrivateValueStore.open(fixtureRoot.root);
      await reopened.bindAttachment(metadata, body);
      const bindingFiles = (await readdir(bindingsPath(fixtureRoot.root)))
        .filter((name) => name.startsWith("attachment-") && name.endsWith(".json"));
      assert.equal(bindingFiles.length, 1);
      assert.deepEqual(
        (await reopened.readBoundAttachment(
          metadata.sessionId,
          metadata.inputId,
          metadata.attachmentId,
        )).body,
        body,
      );
    } finally {
      await fixtureRoot.cleanup();
    }
  }
});

test("private continuation locators bind an exact no-follow transcript", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  const sessionRoot = join(fixtureRoot.parent, "sessions");
  const sessionPath = join(sessionRoot, "transcript-1.jsonl");
  try {
    await mkdir(sessionRoot, { mode: 0o700 });
    await writeFile(sessionPath, "private transcript\n", { mode: 0o600 });
    const values = await PrivateValueStore.open(fixtureRoot.root, {
      continuationRoot: sessionRoot,
    });
    const locator = {
      continuationId: "continuation-1",
      activeSessionId: "prime-active-1",
      transcriptSessionId: "prime-transcript-1",
      supervisorGeneration: "supervisor-generation-1",
      sessionPath,
    };
    const binding = await values.putContinuationLocator(locator);
    assert.deepEqual(
      await values.readContinuationLocator(binding),
      locator,
    );
    assert.equal(JSON.stringify(binding).includes(sessionPath), false);

    await rm(sessionRoot, { recursive: true });
    const replacementRoot = join(fixtureRoot.parent, "replacement-sessions");
    await mkdir(replacementRoot, { mode: 0o700 });
    await writeFile(
      join(replacementRoot, "transcript-1.jsonl"),
      "private transcript\n",
      { mode: 0o600 },
    );
    await symlink(replacementRoot, sessionRoot, "dir");
    await assert.rejects(
      values.readContinuationLocator(binding),
      PrivateValueInvalidError,
    );

    await rm(sessionRoot);
    await mkdir(sessionRoot, { mode: 0o700 });
    const external = join(fixtureRoot.parent, "external-session.jsonl");
    await writeFile(external, "private transcript\n", { mode: 0o600 });
    await symlink(external, sessionPath);
    await assert.rejects(
      values.readContinuationLocator(binding),
      PrivateValueInvalidError,
    );
  } finally {
    await fixtureRoot.cleanup();
  }
});

test("private values fail closed when a bound result blob is tampered", async () => {
  const fixtureRoot = await temporaryStoreRoot();
  try {
    const values = await PrivateValueStore.open(fixtureRoot.root);
    const first = await values.bindResultReference(
      "terminal-action-1",
      "action-1",
      "receipt-1",
      {
        receiptRef: "receipt-1",
        artifactIds: ["artifact-1"],
        mediaTypes: ["text/plain"],
      },
    );
    await writeFile(
      valuePath(fixtureRoot.root, first),
      `${JSON.stringify({
        format: "asterion.prime-private-value/v1",
        reference: first,
        kind: "result",
        size: 2,
        digest: "0".repeat(64),
      })}\n{}\n`,
    );
    await chmod(valuePath(fixtureRoot.root, first), 0o600);

    await assert.rejects(
      values.readBoundResultReference(
        "terminal-action-1",
        "action-1",
        "receipt-1",
      ),
      PrivateValueInvalidError,
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
