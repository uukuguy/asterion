import { createHash } from "node:crypto";
import { constants } from "node:fs";
import { lstat, mkdir, readFile, rename, rm, writeFile } from "node:fs/promises";
import { fileURLToPath } from "node:url";
import { basename, dirname } from "node:path";

const checkOnly = process.argv.slice(2).includes("--check");
if (process.argv.length > (checkOnly ? 3 : 2)) {
  throw new Error("usage: sync-runtime-resource.mjs [--check]");
}

const resources = [
  {
    source: fileURLToPath(new URL("../src/dci-context-extension.ts", import.meta.url)),
    destination: fileURLToPath(new URL(
      "../../../../src/asterion/capabilities/dci/resources/pi/dci-context-extension.ts",
      import.meta.url,
    )),
    manifestPath: fileURLToPath(new URL(
      "../../../../src/asterion/capabilities/dci/resources/pi/context-extension-manifest.json",
      import.meta.url,
    )),
    manifest(sourceText, sourceBytes) {
      const extensionVersion = sourceText.match(
        /EXTENSION_VERSION\s*=\s*"([^"]+)"/,
      )?.[1];
      const contractVersion = sourceText.match(
        /PROFILE_CONTRACT_VERSION\s*=\s*"([^"]+)"/,
      )?.[1];
      if (!extensionVersion || !contractVersion) {
        throw new Error("context extension source identity is missing");
      }
      return {
        schema: "dci.context-extension-manifest/v1",
        extension_version: extensionVersion,
        contract_version: contractVersion,
        resource: "dci-context-extension.ts",
        byte_length: sourceBytes.length,
        sha256: createHash("sha256").update(sourceBytes).digest("hex"),
      };
    },
  },
  {
    source: fileURLToPath(new URL("../src/dci-pathlight-observation.ts", import.meta.url)),
    destination: fileURLToPath(new URL(
      "../../../../src/asterion/capabilities/dci/resources/pi/dci-pathlight-observation.ts",
      import.meta.url,
    )),
    manifestPath: fileURLToPath(new URL(
      "../../../../src/asterion/capabilities/dci/resources/pi/pathlight-observation-manifest.json",
      import.meta.url,
    )),
    manifest(sourceText, sourceBytes) {
      const captureContractVersion = sourceText.match(
        /CAPTURE_CONTRACT_VERSION\s*=\s*"([^"]+)"/,
      )?.[1];
      const privateRecordSchema = sourceText.match(
        /PRIVATE_RECORD_SCHEMA\s*=\s*"([^"]+)"/,
      )?.[1];
      const safeObservationSchema = sourceText.match(
        /SAFE_OBSERVATION_SCHEMA\s*=\s*"([^"]+)"/,
      )?.[1];
      if (!captureContractVersion || !privateRecordSchema || !safeObservationSchema) {
        throw new Error("Pathlight observation source identity is missing");
      }
      return {
        schema: "dci.pathlight-observation-extension-manifest/v1",
        extension_version: "0.3.0",
        contract_version: captureContractVersion,
        resource: "dci-pathlight-observation.ts",
        byte_length: sourceBytes.length,
        sha256: createHash("sha256").update(sourceBytes).digest("hex"),
      };
    },
  },
];

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

const synchronized = [];
for (const resource of resources) {
  await regularFile(resource.source);
  const sourceBytes = await readFile(resource.source);
  const sourceText = sourceBytes.toString("utf8");
  const manifest = `${JSON.stringify(resource.manifest(sourceText, sourceBytes), null, 2)}\n`;
  synchronized.push({ resource, sourceBytes, manifest });
}

if (checkOnly) {
  for (const { resource, sourceBytes, manifest } of synchronized) {
    const mirrored = await existingBytes(resource.destination);
    const recordedManifest = await existingBytes(resource.manifestPath);
    if (
      mirrored === undefined ||
      !mirrored.equals(sourceBytes) ||
      recordedManifest === undefined ||
      recordedManifest.toString("utf8") !== manifest
    ) {
      throw new Error("context extension runtime resource is out of sync");
    }
  }
} else {
  // Validate every source and construct every manifest before mutating any mirror.
  for (const { resource, sourceBytes, manifest } of synchronized) {
    await atomicWrite(resource.destination, sourceBytes);
    await atomicWrite(resource.manifestPath, manifest);
  }
}
