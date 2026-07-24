import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { basename, dirname } from "node:path";

const checkOnly = process.argv.slice(2).includes("--check");
if (process.argv.length > (checkOnly ? 3 : 2)) {
  throw new Error("usage: sync-runtime-resource.mjs [--check]");
}

const source = fileURLToPath(new URL("../src/dci-context-extension.ts", import.meta.url));
const destination = fileURLToPath(
  new URL(
    "../../../../src/asterion/dci/resources/pi/dci-context-extension.ts",
    import.meta.url,
  ),
);
const manifestPath = fileURLToPath(
  new URL(
    "../../../../src/asterion/dci/resources/pi/context-extension-manifest.json",
    import.meta.url,
  ),
);

async function regularFile(path) {
  const metadata = await lstat(path);
  if (!metadata.isFile() || metadata.isSymbolicLink()) {
    throw new Error("context extension resource path is unsafe");
  }
}

async function existingBytes(path) {
  try {
    await regularFile(path);
    return await readFile(path);
  } catch (error) {
    if (error?.code === "ENOENT") return undefined;
    throw error;
  }
}

async function atomicWrite(path, bytes) {
  await mkdir(dirname(path), { recursive: true });
  const temporary = `${dirname(path)}/.${basename(path)}.${process.pid}.tmp`;
  try {
    await writeFile(temporary, bytes, {
      encoding: typeof bytes === "string" ? "utf8" : undefined,
      mode: 0o644,
      flag: constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY,
    });
    const current = await existingBytes(path);
    if (current !== undefined) await regularFile(path);
    await rename(temporary, path);
  } finally {
    await rm(temporary, { force: true });
  }
}

await regularFile(source);
const sourceBytes = await readFile(source);
const sourceText = sourceBytes.toString("utf8");
const extensionVersion = sourceText.match(
  /EXTENSION_VERSION\s*=\s*"([^"]+)"/,
)?.[1];
const contractVersion = sourceText.match(
  /PROFILE_CONTRACT_VERSION\s*=\s*"([^"]+)"/,
)?.[1];
if (!extensionVersion || !contractVersion) {
  throw new Error("context extension source identity is missing");
}
const manifest = `${JSON.stringify(
  {
    schema: "dci.context-extension-manifest/v1",
    extension_version: extensionVersion,
    contract_version: contractVersion,
    resource: "dci-context-extension.ts",
    byte_length: sourceBytes.length,
    sha256: createHash("sha256").update(sourceBytes).digest("hex"),
  },
  null,
  2,
)}\n`;

if (checkOnly) {
  const mirrored = await existingBytes(destination);
  const recordedManifest = await existingBytes(manifestPath);
  if (
    mirrored === undefined ||
    !mirrored.equals(sourceBytes) ||
    recordedManifest === undefined ||
    recordedManifest.toString("utf8") !== manifest
  ) {
    throw new Error("context extension runtime resource is out of sync");
  }
} else {
  await atomicWrite(destination, sourceBytes);
  await atomicWrite(manifestPath, manifest);
}
