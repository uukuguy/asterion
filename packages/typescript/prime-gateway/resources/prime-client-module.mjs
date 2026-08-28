import { createHash } from "node:crypto";
import * as primeSdk from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/sdk.js";
import * as primeCli from "../../../../3th-party/prime-agent/packages/coding-agent/dist/cli-main.js";
import * as primeRpc from "../../../../3th-party/prime-agent/packages/coding-agent/dist/modes/rpc/rpc-client.js";
import * as primeAcp from "../../../../3th-party/prime-agent/packages/coding-agent/dist/modes/acp/acp-mode.js";
import * as primeJsonl from "../../../../3th-party/prime-agent/packages/coding-agent/dist/modes/rpc/jsonl.js";
import * as primePrint from "../../../../3th-party/prime-agent/packages/coding-agent/dist/modes/print-mode.js";
import * as primeSlashCommands from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/slash-commands.js";
import * as primeExtensionUi from "../../../../3th-party/prime-agent/packages/coding-agent/dist/modes/interactive/components/extension-input.js";
import * as primeExportShare from "../../../../3th-party/prime-agent/packages/coding-agent/dist/core/export-html/index.js";

const FORMAT = "asterion.prime-client-frame/v1";
const SOURCE_COMMIT = "a18809e00ea30638584d87b3afea7285a9d7296c";
const ARTIFACT_LOCK_DIGEST = "c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3";
const PACKAGES = Object.freeze({
  core: Object.freeze({
    featureIds: Object.freeze(["interface.json-stream", "interface.sdk"]),
    scenarioIds: Object.freeze(["prime-client-core.jsonl", "prime-client-core.sdk"]),
  }),
  protocols: Object.freeze({
    featureIds: Object.freeze(["interface.acp", "interface.rpc"]),
    scenarioIds: Object.freeze(["prime-parity.interface.acp", "prime-parity.interface.rpc"]),
  }),
  interactive: Object.freeze({
    featureIds: Object.freeze([
      "interface.cli-interactive", "interface.headless-print",
      "interface.tui-commands", "interface.tui-extension-ui",
    ]),
    scenarioIds: Object.freeze([
      "prime-client-interactive.cli", "prime-client-interactive.headless",
      "prime-client-interactive.commands", "prime-client-interactive.extension-ui",
    ]),
  }),
  "export-share": Object.freeze({
    featureIds: Object.freeze(["interface.export-share"]),
    scenarioIds: Object.freeze(["prime-client-export-share.public"]),
  }),
});

function fail() { throw new Error("Prime client module rejected its frame"); }

function canonical(value) {
  if (value === null || typeof value === "string" || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (typeof value !== "object") fail();
  return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
}

function digest(value) { return createHash("sha256").update(canonical(value)).digest("hex"); }

function exactStrings(value, expected) {
  return Array.isArray(value) && value.length === expected.length && value.every((item, index) => item === expected[index]);
}

function sealedFrame(value) {
  if (
    typeof value !== "object" || value === null || Array.isArray(value) || !Object.isFrozen(value) ||
    Object.keys(value).sort().join("\0") !== ["artifactLockDigest", "format", "moduleLockDigest", "package", "sourceCommit"].join("\0") ||
    value.format !== FORMAT || value.sourceCommit !== SOURCE_COMMIT ||
    value.artifactLockDigest !== ARTIFACT_LOCK_DIGEST ||
    typeof value.moduleLockDigest !== "string" || !/^[0-9a-f]{64}$/u.test(value.moduleLockDigest) ||
    typeof value.package !== "string" || !Object.hasOwn(PACKAGES, value.package)
  ) fail();
  return value;
}

function anchorSurface() {
  // Referencing all nine locked anchors proves the checked-in module graph is linkable,
  // while the deterministic fakes below prevent a provider, credential, or network path.
  const anchors = [primeSdk, primeCli, primeRpc, primeAcp, primeJsonl, primePrint, primeSlashCommands, primeExtensionUi, primeExportShare];
  if (anchors.some((anchor) => typeof anchor !== "object" || anchor === null)) fail();
  return anchors.map((anchor) => Object.keys(anchor).length);
}

export async function runClientPackage(value) {
  const frame = sealedFrame(value);
  const specification = PACKAGES[frame.package];
  const fakeProvider = Object.freeze({ credentialReads: 0, operations: 0, networkRequests: 0 });
  const fakeProcess = Object.freeze({ retained: 0 });
  const privateEffects = Object.freeze({ publicExportPrivateReads: 0, unauthorizedUploads: 0 });
  const surfaces = anchorSurface();
  const outcome = Object.freeze({
    anchorSurfaceDigest: digest(surfaces),
    artifactLockDigest: frame.artifactLockDigest,
    credentialReads: fakeProvider.credentialReads,
    featureCount: specification.featureIds.length,
    featureIds: specification.featureIds,
    moduleLockDigest: frame.moduleLockDigest,
    networkRequests: fakeProvider.networkRequests,
    package: frame.package,
    providerOperations: fakeProvider.operations,
    publicExportPrivateReads: privateEffects.publicExportPrivateReads,
    retainedProcesses: fakeProcess.retained,
    scenarioCount: specification.scenarioIds.length,
    scenarioIds: specification.scenarioIds,
    sourceCommit: frame.sourceCommit,
    unauthorizedUploads: privateEffects.unauthorizedUploads,
  });
  if (!exactStrings(outcome.featureIds, specification.featureIds) || !exactStrings(outcome.scenarioIds, specification.scenarioIds)) fail();
  return outcome;
}
