import assert from "node:assert/strict";
import { mkdir, mkdtemp, readFile, rename, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";


test("mid-publication failure restores all four preexisting outputs", async () => {
  const module = await import("../scripts/sync-runtime-resource.mjs");
  assert.equal(typeof module.publishAtomically, "function");

  const root = await mkdtemp(join(tmpdir(), "asterion-sync-rollback-"));
  try {
    const outputs = ["context.ts", "context.json", "pathlight.ts", "pathlight.json"];
    const originals = new Map();
    const writes = [];
    await mkdir(root, { recursive: true });
    for (const [index, name] of outputs.entries()) {
      const path = join(root, name);
      const original = Buffer.from(`original-${index}`);
      originals.set(path, original);
      await writeFile(path, original);
      writes.push({ path, bytes: Buffer.from(`replacement-${index}`) });
    }

    let renameCalls = 0;
    const failMidPublication = async (source, destination) => {
      renameCalls += 1;
      if (renameCalls === 5) throw new Error("SENTINEL_INJECTED_RENAME_FAILURE");
      await rename(source, destination);
    };

    await assert.rejects(
      module.publishAtomically(writes, { renameFile: failMidPublication }),
      /^Error: extension resource publication failed$/,
    );
    assert.equal(renameCalls >= 5, true);
    for (const [path, original] of originals) {
      assert.deepEqual(await readFile(path), original, path);
    }
  } finally {
    await rm(root, { recursive: true, force: true });
  }
});
