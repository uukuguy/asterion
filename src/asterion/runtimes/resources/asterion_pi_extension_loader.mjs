import { createHash } from "node:crypto";
import { closeSync, fstatSync, readFileSync, readSync, realpathSync, statSync } from "node:fs";

const SOURCE_FD = "ASTERION_PI_EXTENSION_SOURCE_FD";
const SOURCE_NAME = "ASTERION_PI_EXTENSION_SOURCE_NAME";
const SOURCE_SHA256 = "ASTERION_PI_EXTENSION_SOURCE_SHA256";
const DEPENDENCIES = "ASTERION_PI_EXTENSION_DEPENDENCIES";
const MAX_SOURCE_BYTES = 4 * 1024 * 1024;

const invalid = () => { throw new Error("Asterion pinned Pi extension is invalid"); };
const exactKeys = (object, keys) => object !== null && typeof object === "object"
  && !Array.isArray(object) && JSON.stringify(Object.keys(object).sort()) === JSON.stringify([...keys].sort());
const validFd = (fd) => Number.isSafeInteger(fd) && fd >= 3;

function closeDependencyDescriptors(raw) {
  try {
    const metadata = JSON.parse(raw);
    for (const key of ["provider", "closureLock", "artifactLock", "sourceRoot"]) {
      const fd = metadata?.[key]?.fd;
      if (validFd(fd)) { try {closeSync(fd);} catch {} }
    }
  } catch {}
}

function readPinned(resource) {
  if (!exactKeys(resource, ["fd", "digest"]) || !validFd(resource.fd)
      || !/^[a-f0-9]{64}$/.test(resource.digest)) invalid();
  const details = fstatSync(resource.fd);
  if (!details.isFile() || details.size <= 0 || details.size > MAX_SOURCE_BYTES) invalid();
  const source = Buffer.alloc(details.size);
  try {
    let offset = 0;
    while (offset < source.length) {
      const count = readSync(resource.fd, source, offset, source.length - offset, offset);
      if (count === 0) invalid();
      offset += count;
    }
    if (createHash("sha256").update(source).digest("hex") !== resource.digest) invalid();
    return source;
  } catch { source.fill(0); invalid(); }
}

async function openDependencies(raw) {
  const held = new Set();
  const buffers = [];
  let handle;
  let closed = false;
  const close = async () => {
    if (closed) return;
    closed = true;
    try { if (handle && typeof handle.close === "function") await handle.close(); }
    finally {
      for (const bytes of buffers) bytes.fill(0);
      for (const fd of held) { try { closeSync(fd); } catch {} }
    }
  };
  try {
    const metadata = JSON.parse(raw);
    for (const key of ["provider", "closureLock", "artifactLock", "sourceRoot"]) {
      const fd = metadata?.[key]?.fd;
      if (validFd(fd)) held.add(fd);
    }
    if (!exactKeys(metadata, ["provider", "closureLock", "artifactLock", "sourceRoot", "exports"])
        || held.size !== 4) invalid();
    const root = metadata.sourceRoot;
    if (!exactKeys(root, ["path", "fd", "dev", "ino"]) || typeof root.path !== "string"
        || realpathSync(root.path) !== root.path || !/^\d+$/.test(root.dev) || !/^\d+$/.test(root.ino)) invalid();
    const heldRoot = fstatSync(root.fd, {bigint: true});
    const currentRoot = statSync(root.path, {bigint: true});
    if (!heldRoot.isDirectory() || !currentRoot.isDirectory()
        || String(heldRoot.dev) !== root.dev || String(heldRoot.ino) !== root.ino
        || heldRoot.dev !== currentRoot.dev || heldRoot.ino !== currentRoot.ino) invalid();
    const expected = metadata.exports;
    if (expected === null || typeof expected !== "object" || Array.isArray(expected)
        || Object.keys(expected).length === 0 || Object.entries(expected).some(([name, kind]) =>
          !/^[A-Za-z_$][A-Za-z0-9_$]*$/.test(name) || !["function", "string"].includes(kind))) invalid();
    for (const key of ["provider", "closureLock", "artifactLock"]) buffers.push(readPinned(metadata[key]));
    const provider = await import(`data:text/javascript;base64,${buffers[0].toString("base64")}`);
    if (typeof provider.verifyDependencies !== "function" || typeof provider.createDependencies !== "function") invalid();
    const context = Object.freeze({sourceRoot: root.path,
      lockBytes: buffers[1], artifactLockBytes: buffers[2]});
    await provider.verifyDependencies(context);
    return {close, async create() {
      handle = await provider.createDependencies(context);
      if (!exactKeys(handle, ["dependencies", "close"]) || typeof handle.close !== "function"
          || !exactKeys(handle.dependencies, Object.keys(expected))) invalid();
      const dependencies = Object.create(null);
      for (const [name, kind] of Object.entries(expected)) {
        const descriptor = Object.getOwnPropertyDescriptor(handle.dependencies, name);
        if (!descriptor || !("value" in descriptor) || typeof descriptor.value !== kind) invalid();
        dependencies[name] = descriptor.value;
      }
      return Object.freeze(dependencies);
    }};
  } catch {
    try { await close(); } catch {}
    invalid();
  }
}

/** Pre-launch verification only; no dependency factory or external module loads. */
export async function verifyPinnedDependencies(raw) {
  const resources = await openDependencies(raw);
  await resources.close();
}

export default async function loadPinnedAsterionExtension(pi) {
  const rawDescriptor = process.env[SOURCE_FD];
  const sourceName = process.env[SOURCE_NAME];
  const expectedDigest = process.env[SOURCE_SHA256];
  const dependencyMetadata = process.env[DEPENDENCIES];
  delete process.env[SOURCE_FD];
  delete process.env[SOURCE_NAME];
  delete process.env[SOURCE_SHA256];
  delete process.env[DEPENDENCIES];

  let descriptor;
  let dependencies;
  let source;
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
    source = readFileSync(descriptor);
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
    if (dependencyMetadata !== undefined) {
      dependencies = await openDependencies(dependencyMetadata);
      const mapping = await dependencies.create();
      if (typeof pi.on !== "function") invalid();
      const resources = dependencies;
      pi.on("session_shutdown", async () => {
        try { await resources.close(); } catch { invalid(); }
      });
      return await loaded.default(pi, mapping);
    }
    return await loaded.default(pi);
  } catch {
    if (dependencies) { try { await dependencies.close(); } catch {} }
    else if (dependencyMetadata !== undefined) closeDependencyDescriptors(dependencyMetadata);
    throw new Error("Asterion pinned Pi extension is invalid");
  } finally {
    source?.fill(0);
    if (descriptor !== undefined) {
      try {
        closeSync(descriptor);
      } catch {
        // The generic error above is the only public failure surface.
      }
    }
  }
}
