import { createHash } from "node:crypto";
import { lstat, readFile, realpath } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import process from "node:process";
import { pathToFileURL } from "node:url";

function fail() { throw new Error("Prime operational fixture rejected its arguments"); }
function canonical(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value !== "object") fail();
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}
function canonicalLock(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") return value;
  if (Array.isArray(value)) return value.map(canonicalLock);
  if (typeof value !== "object") fail();
  return Object.fromEntries(Object.keys(value).sort().map((key) => [key, canonicalLock(value[key])]));
}
function argumentsFrame(values) {
  if (values.length !== 6 || values[0] !== "--resource-root" || values[2] !== "--source-root" || values[4] !== "--package") fail();
  const [, resourceRoot, , sourceRoot, , packageId] = values;
  if (!isAbsolute(resourceRoot) || !isAbsolute(sourceRoot) || !["auth", "doctor", "model-selection", "settings-keybindings", "telemetry", "update-restart"].includes(packageId)) fail();
  return Object.freeze({ packageId, resourceRoot, sourceRoot });
}

async function main() {
  const frame = argumentsFrame(process.argv.slice(2));
  const [resourceStat, sourceStat] = await Promise.all([lstat(frame.resourceRoot), lstat(frame.sourceRoot)]);
  if (!resourceStat.isDirectory() || resourceStat.isSymbolicLink() || !sourceStat.isDirectory() || sourceStat.isSymbolicLink()) fail();
  const resourceRoot = await realpath(frame.resourceRoot);
  const moduleFile = join(resourceRoot, "prime-operational-module.mjs");
  const lockFile = join(resourceRoot, "prime-operational-module-lock.json");
  const [moduleStat, lockStat] = await Promise.all([lstat(moduleFile), lstat(lockFile)]);
  if (moduleStat.isSymbolicLink() || lockStat.isSymbolicLink() || !moduleStat.isFile() || !lockStat.isFile()) fail();
  const [moduleBytes, lockBytes] = await Promise.all([readFile(moduleFile), readFile(lockFile)]);
  let lock; try {
    const rawLock = lockBytes.toString("utf8");
    lock = JSON.parse(rawLock);
    if (`${JSON.stringify(canonicalLock(lock), null, 2)}\n` !== rawLock) fail();
  } catch { fail(); }
  if (
    typeof lock !== "object" || lock === null || Array.isArray(lock) ||
    lock.format !== "asterion.prime-operational-module-lock/v1" ||
    lock.source_commit !== "a18809e00ea30638584d87b3afea7285a9d7296c" ||
    lock.module_digest !== createHash("sha256").update(moduleBytes).digest("hex")
  ) fail();
  const modulePath = new URL("prime-operational-module.mjs", pathToFileURL(`${resourceRoot}/`));
  const loaded = await import(`${modulePath.href}?resource=locked`);
  if (Object.keys(loaded).sort().join("\0") !== "runOperationalPackage\0verifyOperationalLocks") fail();
  const receipt = await loaded.runOperationalPackage(Object.freeze({
    failureCase: null,
    package: frame.packageId,
    resourceRoot,
    sourceRoot: await realpath(frame.sourceRoot),
  }));
  if (
    receipt.format !== "asterion.prime-operational-infrastructure-receipt/v1" ||
    receipt.package !== frame.packageId || receipt.status !== "infrastructure-ready" ||
    Object.values(receipt.effect_counts).some((value) => value !== 0) ||
    receipt.scenario_counters.scenario_calls !== 1
  ) fail();
  process.stdout.write(`${canonical(receipt)}\n`);
}

main().catch(() => { process.stderr.write("Prime operational fixture failed\n"); process.exitCode = 1; });
