import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  fstatSync,
  mkdtempSync,
  openSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

const loaderUrl = new URL(
  "../src/asterion/runtimes/resources/asterion_pi_extension_loader.mjs",
  import.meta.url,
);

test("loader imports the exact bytes held by the source descriptor", async () => {
  const root = mkdtempSync(join(tmpdir(), "asterion-pi-loader-"));
  const sourcePath = join(root, "extension.mjs");
  const original = Buffer.from(
    'export default (pi) => pi.registerTool({ name: "original" });\n',
  );
  writeFileSync(sourcePath, original);
  const descriptor = openSync(sourcePath, "r");
  unlinkSync(sourcePath);
  writeFileSync(
    sourcePath,
    'export default (pi) => pi.registerTool({ name: "replacement" });\n',
  );
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(descriptor);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = createHash("sha256")
    .update(original)
    .digest("hex");
  const names = [];

  try {
    const loader = await import(`${loaderUrl.href}?case=pinned`);
    await loader.default({ registerTool: (tool) => names.push(tool.name) });
  } finally {
    rmSync(root, { recursive: true, force: true });
  }

  assert.deepEqual(names, ["original"]);
  assert.equal(process.env.ASTERION_PI_EXTENSION_SOURCE_FD, undefined);
  assert.equal(process.env.ASTERION_PI_EXTENSION_SOURCE_NAME, undefined);
  assert.equal(process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256, undefined);
});

test("loader closes the source descriptor when metadata is rejected", async () => {
  const root = mkdtempSync(join(tmpdir(), "asterion-pi-loader-"));
  const sourcePath = join(root, "extension.mjs");
  const source = Buffer.from("export default () => {};\n");
  writeFileSync(sourcePath, source);
  const descriptor = openSync(sourcePath, "r");
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(descriptor);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "../extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = createHash("sha256")
    .update(source)
    .digest("hex");

  try {
    const loader = await import(`${loaderUrl.href}?case=metadata`);
    await assert.rejects(loader.default({}), {
      message: "Asterion pinned Pi extension is invalid",
    });
    assert.throws(() => fstatSync(descriptor));
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("loader rejects mismatched pinned-source metadata without echoing it", async () => {
  const root = mkdtempSync(join(tmpdir(), "asterion-pi-loader-"));
  const sourcePath = join(root, "secret-extension.mjs");
  writeFileSync(sourcePath, "export default () => {};\n");
  const descriptor = openSync(sourcePath, "r");
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(descriptor);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "secret-extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = "a".repeat(64);

  try {
    const loader = await import(`${loaderUrl.href}?case=mismatch`);
    await assert.rejects(
      loader.default({}),
      (error) =>
        error instanceof Error &&
        error.message === "Asterion pinned Pi extension is invalid",
    );
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
