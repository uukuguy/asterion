import { createHash } from "node:crypto";
import { closeSync, fstatSync, readFileSync } from "node:fs";

const SOURCE_FD = "ASTERION_PI_EXTENSION_SOURCE_FD";
const SOURCE_NAME = "ASTERION_PI_EXTENSION_SOURCE_NAME";
const SOURCE_SHA256 = "ASTERION_PI_EXTENSION_SOURCE_SHA256";
const MAX_SOURCE_BYTES = 4 * 1024 * 1024;

export default async function loadPinnedAsterionExtension(pi) {
  const rawDescriptor = process.env[SOURCE_FD];
  const sourceName = process.env[SOURCE_NAME];
  const expectedDigest = process.env[SOURCE_SHA256];
  delete process.env[SOURCE_FD];
  delete process.env[SOURCE_NAME];
  delete process.env[SOURCE_SHA256];

  let descriptor;
  try {
    if (!/^[1-9][0-9]*$/.test(rawDescriptor ?? "")) {
      throw new Error();
    }
    descriptor = Number(rawDescriptor);
    if (!Number.isSafeInteger(descriptor) || descriptor < 3) {
      throw new Error();
    }
    if (
      !/^[A-Za-z0-9][A-Za-z0-9._-]*\.mjs$/.test(sourceName ?? "") ||
      !/^[a-f0-9]{64}$/.test(expectedDigest ?? "")
    ) {
      throw new Error();
    }
    const details = fstatSync(descriptor);
    if (!details.isFile() || details.size <= 0 || details.size > MAX_SOURCE_BYTES) {
      throw new Error();
    }
    const source = readFileSync(descriptor);
    closeSync(descriptor);
    descriptor = undefined;
    if (
      source.byteLength !== details.size ||
      createHash("sha256").update(source).digest("hex") !== expectedDigest
    ) {
      throw new Error();
    }
    const encoded = source.toString("base64");
    const loaded = await import(`data:text/javascript;base64,${encoded}`);
    if (typeof loaded.default !== "function") {
      throw new Error();
    }
    return await loaded.default(pi);
  } catch {
    throw new Error("Asterion pinned Pi extension is invalid");
  } finally {
    if (descriptor !== undefined) {
      try {
        closeSync(descriptor);
      } catch {
        // The generic error above is the only public failure surface.
      }
    }
  }
}
