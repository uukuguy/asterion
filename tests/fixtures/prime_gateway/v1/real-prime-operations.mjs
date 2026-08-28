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
  if (!isAbsolute(resourceRoot) || !isAbsolute(sourceRoot) || !["auth", "controlled-update-restart", "doctor", "model-selection", "settings-keybindings", "telemetry-usage"].includes(packageId)) fail();
  return Object.freeze({ packageId, resourceRoot, sourceRoot });
}
const EFFECT_KEYS = Object.freeze(["credential_reads", "network_requests", "provider_operations", "retained_processes", "stdout_writes", "unauthorized_uploads"]);
const COUNTER_KEYS = Object.freeze(["fake_coordinator_calls", "host_service_calls", "injected_sink_calls", "mock_refresh_calls", "reconcile_calls", "scenario_calls"]);
const ASSERTIONS = Object.freeze(["authority-preserved", "feature-reachable", "identity-stable", "public-redacted"]);
const CONTRACTS = Object.freeze({
  auth: Object.freeze({ feature: "operation.auth", scenario: "prime-parity.operation.auth", extra: ["refresh_outcomes"], failures: ["mock-refresh-failure", "restart-after-admission"] }),
  "model-selection": Object.freeze({ feature: "operation.model-selection", scenario: "prime-parity.operation.model-selection", extra: ["model_transition"], failures: ["fixture-catalog-mismatch", "restart-after-admission"] }),
  "settings-keybindings": Object.freeze({ feature: "operation.settings-keybindings", scenario: "prime-parity.operation.settings-keybindings", extra: ["key_chords", "settings"], failures: ["legacy-alias", "restart-after-admission"] }),
  "telemetry-usage": Object.freeze({ feature: "operation.telemetry-usage", scenario: "prime-parity.operation.telemetry-usage", extra: ["usage_observation"], failures: ["injected-sink-failure", "restart-after-admission"] }),
  doctor: Object.freeze({ feature: "operation.doctor", scenario: "prime-parity.operation.doctor", extra: ["diagnostic"], failures: ["diagnostic-inspection-failure", "restart-after-admission"] }),
  "controlled-update-restart": Object.freeze({ feature: "operation.controlled-update-restart", scenario: "prime-parity.operation.controlled-update-restart", extra: ["restart"], failures: ["reconcile-identity-mismatch", "restart-after-admission"] }),
});
function exactKeys(value, expected) {
  if (typeof value !== "object" || value === null || Array.isArray(value) || Object.keys(value).sort().join("\0") !== [...expected].sort().join("\0")) fail();
}
function assertReceipt(receipt, packageId, lock) {
  const contract = CONTRACTS[packageId]; if (!contract) fail();
  exactKeys(receipt, [
    "assertion_ids", "built_anchor_digests", "dependency_lock_sha256", "dependency_tree_digest", "effect_counts", "failure_matrix", "fault_ids", "feature_ids", "format", "module_digest", "node_runtime", "package", "redaction_status", "runtime_digest", "scenario_counts", "scenario_id", "source_anchor_digests", "source_commit", "status", "workspace_digest", ...contract.extra,
  ]);
  if (receipt.format !== "asterion.prime-operational-receipt/v1" || receipt.package !== packageId || receipt.status !== "pass" || receipt.redaction_status !== "pass" || receipt.scenario_id !== contract.scenario || JSON.stringify(receipt.feature_ids) !== JSON.stringify([contract.feature]) || JSON.stringify(receipt.assertion_ids) !== JSON.stringify(ASSERTIONS) || JSON.stringify(receipt.fault_ids) !== JSON.stringify(["restart-after-admission"])) fail();
  exactKeys(receipt.effect_counts, EFFECT_KEYS);
  if (Object.values(receipt.effect_counts).some((value) => !Number.isSafeInteger(value) || value !== 0)) fail();
  exactKeys(receipt.scenario_counts, COUNTER_KEYS);
  for (const key of COUNTER_KEYS) {
    const expected = key === "scenario_calls" || key === "host_service_calls" ||
      (key === "mock_refresh_calls" && packageId === "auth") ||
      (key === "injected_sink_calls" && packageId === "telemetry-usage") ||
      ((key === "fake_coordinator_calls" || key === "reconcile_calls") && packageId === "controlled-update-restart") ? 1 : 0;
    if (receipt.scenario_counts[key] !== expected) fail();
  }
  if (
    receipt.built_anchor_digests === null || canonical(receipt.built_anchor_digests) !== canonical(lock.built_anchor_digests) ||
    receipt.dependency_lock_sha256 !== lock.dependency_lock_sha256 ||
    receipt.dependency_tree_digest !== lock.dependency_tree_digest ||
    receipt.module_digest !== lock.module_digest ||
    receipt.node_runtime !== lock.node_runtime ||
    receipt.runtime_digest !== lock.runtime_digest ||
    receipt.source_anchor_digests === null || canonical(receipt.source_anchor_digests) !== canonical(lock.source_anchor_digests) ||
    receipt.source_commit !== lock.source_commit || receipt.workspace_digest !== lock.workspace_digest
  ) fail();
  if (JSON.stringify(receipt.failure_matrix) !== JSON.stringify(contract.failures.map((case_id) => ({ case_id, status: "rejected" })))) fail();
  if (packageId === "settings-keybindings" && canonical(receipt.key_chords) !== canonical({ "app.input.clear": "Ctrl+L", "app.interrupt": "Ctrl+C", "app.session.new": "Ctrl+N" })) fail();
  if (packageId === "settings-keybindings" && JSON.stringify(receipt.settings) !== JSON.stringify([["global", "theme", "enum"], ["global", "telemetry.enabled", "boolean"], ["global", "app.session.new", "key-chord"], ["global", "app.input.clear", "key-chord"], ["global", "app.interrupt", "key-chord"]])) fail();
  if (packageId === "auth" && JSON.stringify(receipt.refresh_outcomes) !== JSON.stringify(["failure-rejected", "success-redacted"])) fail();
  if (packageId === "model-selection" && JSON.stringify(receipt.model_transition) !== JSON.stringify(["fixture-catalog-1", "1", "fixture.model.small", "low", "standard", "fixture.transport-1"])) fail();
  if (packageId === "telemetry-usage" && JSON.stringify(receipt.usage_observation) !== JSON.stringify(["fixture.source", "agent run completed", 0, 0, "sink-failure-observed"])) fail();
  if (packageId === "doctor" && (!Array.isArray(receipt.diagnostic) || receipt.diagnostic.length !== 4 || receipt.diagnostic[0] !== "resource-loader.theme" || receipt.diagnostic[1] !== "warning" || receipt.diagnostic[2] !== "theme-path-missing" || typeof receipt.diagnostic[3] !== "string" || !/^[0-9a-f]{64}$/u.test(receipt.diagnostic[3]))) fail();
  if (packageId === "controlled-update-restart" && (!Array.isArray(receipt.restart) || receipt.restart.length !== 6 || receipt.restart[0] !== "artifact-prime-1" || receipt.restart[1] !== "prime-daemon-1" || receipt.restart[2] !== "asterion.agent-runtime/v1" || receipt.restart[3] !== "checkpoint-prime-1" || typeof receipt.restart[4] !== "string" || !/^[0-9a-f]{64}$/u.test(receipt.restart[4]) || receipt.restart[5] !== "uncertain-reconciled")) fail();
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
  assertReceipt(receipt, frame.packageId, lock);
  process.stdout.write(`${canonical(receipt)}\n`);
}

main().catch(() => { process.stderr.write("Prime operational fixture failed\n"); process.exitCode = 1; });
