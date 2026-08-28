import { constants, readFileSync } from "node:fs";
import {
  lstat,
  open,
  readFile,
  realpath,
  rename,
  rm,
  unlink,
} from "node:fs/promises";
import { createHash, randomUUID } from "node:crypto";
import process from "node:process";
import { dirname, isAbsolute, join } from "node:path";
import readline from "node:readline/promises";
import { pathToFileURL } from "node:url";

import {
  validateControlCommand,
  validateControlEvent,
  validateSessionContextCommand,
  validateSessionContextReceipt,
} from "@dci/agent-runtime";
import type {
  ControlCommand,
  ControlEvent,
  SessionContextCommand,
  SessionContextReceipt,
} from "@dci/agent-runtime";

import {
  loadPrimeArtifactLock,
  verifyPrimeArtifact,
} from "./artifact-lock.js";
import {
  PrimeCheckpointManager,
  recoveryFromAttach,
} from "./checkpoint.js";
import {
  PrimeDaemonClient,
} from "./daemon-client.js";
import {
  canonicalJsonBytes,
  ensurePrivateDirectory,
  GatewayDurableStore,
  syncPrivateDirectory,
} from "./durable-store.js";
import {
  PrimeGateway,
  PrimeGatewayError,
} from "./gateway.js";
import type {
  PrimeGatewayPrivateInputs,
} from "./gateway.js";
import {
  PrimeSession,
} from "./prime-session.js";
import {
  PrivateValueStore,
} from "./private-store.js";
import type {
  PrivateResultProjection,
  PrivateContinuationBinding,
} from "./private-store.js";
import type { PrimeClientObservation } from "./client-observation.js";
import type {
  GatewayRlmBinding,
  GatewayRlmMessageBinding,
} from "./durable-store.js";
import {
  PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST,
  PRIME_ECOSYSTEM_BUNDLE_DIGEST,
  PRIME_ECOSYSTEM_LOCK_CONTRACT,
  PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST,
  PrimeEcosystemAdapter,
  validateGatewayEcosystemEffectResult,
  validatePrimeEcosystemFrame,
  validatePrimeEcosystemReceipt,
} from "./ecosystem.js";
import type {
  GatewayEcosystemEffectResult,
  PrimeEcosystemFrame,
  PrimeEcosystemLockContract,
  PrimeEcosystemModule,
  PrimeEcosystemReceipt,
} from "./ecosystem.js";
import {
  AsterionSkillBridge,
  deriveControlActionId,
  generateSkillBridgeToken,
} from "./skill-bridge.js";
import type {
  SkillApplicationTarget,
  SkillBudget,
} from "./skill-bridge.js";
import {
  listenRlmHostBridge,
  RlmHostBridge,
} from "./rlm-host-bridge.js";
import type {
  RlmMessageDelivery,
  RlmMessageProposal,
  RlmSpawnProposal,
} from "./rlm-host-bridge.js";

export const PRIME_GATEWAY_IPC_PROTOCOL = "asterion.prime-gateway-ipc/v1";
export const PRIME_GATEWAY_SKILL_DISCOVERY = "asterion.skill-control-discovery/v1";
export const PRIME_GATEWAY_SKILL_DISCOVERY_FILE = "asterion-control.json";
export const PRIME_GATEWAY_RLM_HOST_DISCOVERY = "asterion.prime-rlm-host-discovery/v1";
export const PRIME_GATEWAY_RLM_HOST_DISCOVERY_FILE = "asterion-rlm-host.json";
export const PRIME_GATEWAY_RLM_HOST_SHIM_FILE = "asterion-rlm-host-shim.mjs";
const MAX_CLIENT_OBSERVATION_RESPONSE_BYTES = 900 * 1024;

type SidecarEnvelopeType =
  | "authority.update"
  | "command.accept"
  | "client_observations"
  | "client_value_read"
  | "events.stream"
  | "ecosystem_activate"
  | "private.read"
  | "rlm.binding.read"
  | "rlm.message.binding.read"
  | "rlm.lifecycle.read"
  | "session-context.cancel"
  | "session-context.execute";

const SIDE_CAR_ENVELOPE_TYPES: ReadonlySet<SidecarEnvelopeType> = new Set([
  "authority.update",
  "command.accept",
  "client_observations",
  "client_value_read",
  "events.stream",
  "ecosystem_activate",
  "private.read",
  "rlm.binding.read",
  "rlm.message.binding.read",
  "rlm.lifecycle.read",
  "session-context.cancel",
  "session-context.execute",
]);

type SessionContextPrivateValues =
  | Readonly<{ readonly kind: "none" }>
  | Readonly<{ readonly kind: "attachment"; readonly body: Uint8Array }>
  | Readonly<{ readonly kind: "instructions"; readonly value: string }>
  | Readonly<{ readonly kind: "label"; readonly value: string }>
  | Readonly<{ readonly kind: "name"; readonly value: string }>;

export interface PrimeGatewaySidecarOptions {
  readonly currentGeneration: number;
  readonly sessionId?: string;
  readonly gateway: {
    accept(command: ControlCommand): Promise<void>;
    updateRemainingBudget(budget: SkillBudget): void;
    eventsAfterCursor(cursor: { readonly generation: number; readonly sequence: number }): readonly ControlEvent[];
    clientObservationsAfterCursor?(cursor: { readonly generation: number; readonly sequence: number }): readonly PrimeClientObservation[];
    executeSessionContext?(
      command: SessionContextCommand,
      preparePrivate: () => Promise<void>,
    ): Promise<SessionContextReceipt>;
    cancelSessionContext?(commandId: string): Promise<void>;
    rlmLifecycle?(): readonly RlmLifecycleObservation[];
    rlmBinding?(actionId: string): GatewayRlmBinding | undefined;
    rlmMessageBinding?(actionId: string): GatewayRlmMessageBinding | undefined;
    activateEcosystem?(frame: PrimeEcosystemFrame): Promise<GatewayEcosystemEffectResult>;
    rlmMessageDelivered?(): readonly string[];
    close(): Promise<void>;
  };
  readonly privateValues: Pick<
    PrivateValueStore,
    | "bindAttachment"
    | "bindInputReference"
    | "bindResultReference"
    | "readInput"
    | "readBoundInputReference"
    | "readBoundResultReference"
    | "describeClientValue"
    | "readClientValue"
  >;
}

interface PrimeSidecarDescriptor {
  readonly agentDir: string;
  readonly artifactLockPath: string;
  readonly authorityId: string;
  readonly authorityRevision: number;
  readonly expectedRuntimeBuildId: string;
  readonly gatewayRoot: string;
  readonly generation: number;
  readonly maxContinuations: number;
  readonly maxControllerTokens: number;
  readonly maxTurns: number;
  readonly model: string;
  readonly portfolio: readonly SkillApplicationTarget[];
  readonly primeSocketPath: string;
  readonly primeSourceRoot: string;
  readonly provider: string;
  readonly probeReady: boolean;
  readonly recoveryReadOnly: boolean;
  readonly rlmMaxChildren: number;
  readonly rlmMaxDepth: 0 | 1;
  readonly remainingBudget: SkillBudget;
  readonly sessionDir: string;
  readonly sessionId: string;
  readonly skillPath: string;
  readonly timeoutMs: number;
  readonly workspace: string;
}

interface SidecarEnvelope {
  readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
  readonly id: string;
  readonly type: SidecarEnvelopeType;
  readonly command?: unknown;
  readonly private?: unknown;
  readonly cursor?: unknown;
  readonly reference?: unknown;
  readonly budget?: unknown;
  readonly command_id?: unknown;
  readonly action_id?: unknown;
  readonly max_bytes?: unknown;
  readonly frame?: unknown;
}

export type RlmLifecycleObservation =
  | Readonly<{
      readonly type: "rlm.child.started";
      readonly child_id: string;
      readonly native_identity_digest: string;
    }>
  | Readonly<{
      readonly type: "rlm.child.terminal";
      readonly child_id: string;
      readonly status: "completed" | "failed" | "cancelled";
    }>
  | Readonly<{ readonly type: "rlm.child.deleted"; readonly child_id: string }>;

type SidecarResponse =
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "authority.accepted";
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "command.accepted";
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "events.batch";
    readonly events: readonly ControlEvent[];
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "client_observations.batch";
    readonly observations: readonly PrimeClientObservation[];
    readonly next_cursor: Readonly<{ readonly generation: number; readonly sequence: number }> | null;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "client_value";
    readonly descriptor: Readonly<{
      readonly reference: string;
      readonly kind: string;
      readonly media_type: string;
      readonly size: number;
      readonly sha256: string;
    }>;
    readonly body_base64: string;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "rlm.lifecycle.batch";
    readonly lifecycle: readonly RlmLifecycleObservation[];
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "rlm.binding.value";
    readonly binding: GatewayRlmBinding;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "rlm.message.binding.value";
    readonly binding: GatewayRlmMessageBinding & Readonly<{ readonly delivered: boolean }>;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "private.value";
    readonly text: string;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "session-context.receipt";
    readonly receipt: SessionContextReceipt;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "session-context.cancel.accepted";
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "ecosystem_receipt";
    readonly receipt: PrimeEcosystemReceipt;
  }
  | {
    readonly protocol: typeof PRIME_GATEWAY_IPC_PROTOCOL;
    readonly id: string;
    readonly type: "error";
    readonly code: "prime-gateway-sidecar-failed";
  };

const REQUEST_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MAX_PRIVATE_TEXT_BYTES = 1024 * 1024;
const MAX_PRIVATE_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MAX_PRIVATE_FRAME_BYTES = 12 * 1024 * 1024;
const IDENTIFIER_PATTERN = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/u;
const VERSION_PATTERN = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/u;
const TOKEN_PATTERN = /^[0-9a-f]{64}$/u;
const MEDIA_TYPE_PATTERN = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;
const BUDGET_KEYS = Object.freeze([
  "aggregate_tokens",
  "application_tokens",
  "child_tokens",
  "controller_tokens",
  "cost_micros",
  "deadline_ms",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sortedExpected = [...expected].sort();
  return (
    actual.length === sortedExpected.length &&
    actual.every((key, index) => key === sortedExpected[index])
  );
}

const PRIME_ECOSYSTEM_MODULE_IDS = Object.freeze([
  "diagnostics",
  "extension-loader",
  "extension-runner",
  "mcp-manager",
  "mcp-oauth",
  "model-registry",
  "package-manager",
  "prompt-templates",
  "resource-loader",
  "skills",
]);
const PRIME_ECOSYSTEM_BUNDLE_EXPORTS = Object.freeze([
  "inspectResources",
  "resolvePackage",
  "runExtensionLifecycle",
  "runMcpFixture",
]);

export interface PrimeEcosystemModuleBinding {
  readonly lock: PrimeEcosystemLockContract;
  readonly module: PrimeEcosystemModule;
}

export interface PrimeEcosystemModuleBindingPaths {
  readonly artifactLockPath: string;
  readonly bundlePath: string;
  readonly moduleLockPath: string;
}

async function readLockedEcosystemFile(path: string): Promise<Buffer> {
  if (!isAbsolute(path)) throw new PrimeGatewayError();
  const metadata = await lstat(path);
  if (
    metadata.isSymbolicLink() ||
    !metadata.isFile() ||
    (metadata.mode & 0o002) !== 0 ||
    await realpath(path) !== path
  ) throw new PrimeGatewayError();
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  try {
    const held = await handle.stat();
    if (
      !held.isFile() ||
      (held.mode & 0o002) !== 0 ||
      held.dev !== metadata.dev ||
      held.ino !== metadata.ino
    ) throw new PrimeGatewayError();
    return await handle.readFile();
  } finally {
    await handle.close().catch(() => undefined);
  }
}

function validateEcosystemModuleLock(value: unknown): string {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "artifact_lock_sha256",
      "bundle_sha256",
      "format",
      "modules",
      "source_commit",
    ]) ||
    value.format !== "asterion.prime-ecosystem-module-lock/v1" ||
    value.source_commit !== "a18809e00ea30638584d87b3afea7285a9d7296c" ||
    value.artifact_lock_sha256 !== PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST ||
    value.bundle_sha256 !== PRIME_ECOSYSTEM_BUNDLE_DIGEST ||
    !Array.isArray(value.modules) ||
    value.modules.length !== PRIME_ECOSYSTEM_MODULE_IDS.length
  ) throw new PrimeGatewayError();
  value.modules.forEach((item, index) => {
    if (
      !isRecord(item) ||
      !hasExactKeys(item, ["built_path", "module_id", "sha256", "source_path"]) ||
      item.module_id !== PRIME_ECOSYSTEM_MODULE_IDS[index] ||
      typeof item.built_path !== "string" ||
      typeof item.source_path !== "string" ||
      typeof item.sha256 !== "string" ||
      !/^[0-9a-f]{64}$/u.test(item.sha256)
    ) throw new PrimeGatewayError();
  });
  return value.bundle_sha256;
}

export async function loadPrimeEcosystemModule(
  paths: PrimeEcosystemModuleBindingPaths,
): Promise<PrimeEcosystemModuleBinding> {
  try {
    if (
      !isRecord(paths) ||
      !hasExactKeys(paths, ["artifactLockPath", "bundlePath", "moduleLockPath"]) ||
      ![paths.artifactLockPath, paths.bundlePath, paths.moduleLockPath]
        .every((path) => typeof path === "string" && isAbsolute(path))
    ) throw new PrimeGatewayError();
    const [artifactLock, moduleLock, bundle] = await Promise.all([
      readLockedEcosystemFile(paths.artifactLockPath as string),
      readLockedEcosystemFile(paths.moduleLockPath as string),
      readLockedEcosystemFile(paths.bundlePath as string),
    ]);
    if (
      createHash("sha256").update(artifactLock).digest("hex") !==
        PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST ||
      createHash("sha256").update(moduleLock).digest("hex") !==
        PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST
    ) throw new PrimeGatewayError();
    const bundleDigest = validateEcosystemModuleLock(
      JSON.parse(moduleLock.toString("utf8")),
    );
    if (createHash("sha256").update(bundle).digest("hex") !== bundleDigest) {
      throw new PrimeGatewayError();
    }
    const loaded = await import(
      `${pathToFileURL(paths.bundlePath as string).href}?sha256=${bundleDigest}`
    ) as unknown;
    if (
      !isRecord(loaded) ||
      Object.keys(loaded).sort().join("\0") !==
        PRIME_ECOSYSTEM_BUNDLE_EXPORTS.join("\0") ||
      PRIME_ECOSYSTEM_BUNDLE_EXPORTS.some(
        (name) => typeof loaded[name] !== "function",
      )
    ) throw new PrimeGatewayError();
    const inspectResources = loaded.inspectResources as (
      frame: PrimeEcosystemFrame,
    ) => Promise<unknown>;
    const module: PrimeEcosystemModule = Object.freeze({
      async activate(frame: PrimeEcosystemFrame): Promise<unknown> {
        await inspectResources(frame);
        return Object.freeze({
          authorityDigest: frame.authorityDigest,
          featureIds: frame.features,
          lifecycleCount: frame.resources.filter(({ kind }) => kind === "extension").length,
          mcpCount: frame.resources.filter(({ kind }) => kind === "mcp-server").length,
          modelCredentialReads: 0,
          ownedProcessCount: 0,
          packageCount: frame.resources.filter(({ kind }) => kind === "package").length,
          portfolioDigest: frame.portfolioDigest,
          providerOperations: 0,
          registrationCount: frame.registrations.length,
          resourceCount: frame.resources.length,
          status: "succeeded",
        });
      },
    });
    return Object.freeze({ lock: PRIME_ECOSYSTEM_LOCK_CONTRACT, module });
  } catch {
    throw new PrimeGatewayError();
  }
}

function validPrivateText(value: unknown): value is string {
  return (
    typeof value === "string" &&
    Buffer.byteLength(value, "utf8") <= MAX_PRIVATE_TEXT_BYTES
  );
}

function validText(value: unknown): value is string {
  return typeof value === "string" && value.length > 0;
}

function positiveInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function nonNegativeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function validateBudget(value: unknown, allowZeroDeadline = false): SkillBudget {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, BUDGET_KEYS) ||
    !nonNegativeInteger(value.aggregate_tokens) ||
    !nonNegativeInteger(value.application_tokens) ||
    !nonNegativeInteger(value.child_tokens) ||
    !nonNegativeInteger(value.controller_tokens) ||
    !nonNegativeInteger(value.cost_micros) ||
    !(
      allowZeroDeadline
        ? nonNegativeInteger(value.deadline_ms)
        : positiveInteger(value.deadline_ms)
    )
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    aggregate_tokens: value.aggregate_tokens,
    application_tokens: value.application_tokens,
    child_tokens: value.child_tokens,
    controller_tokens: value.controller_tokens,
    cost_micros: value.cost_micros,
    deadline_ms: Number(value.deadline_ms),
  });
}

function validateTarget(value: unknown): SkillApplicationTarget {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "application_id",
      "kind",
      "provider_id",
      "runtime_id",
      "version",
    ]) ||
    value.kind !== "application" ||
    typeof value.application_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.application_id) ||
    typeof value.provider_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.provider_id) ||
    typeof value.runtime_id !== "string" ||
    !IDENTIFIER_PATTERN.test(value.runtime_id) ||
    typeof value.version !== "string" ||
    !VERSION_PATTERN.test(value.version)
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    application_id: value.application_id,
    kind: "application",
    provider_id: value.provider_id,
    runtime_id: value.runtime_id,
    version: value.version,
  });
}

function validatePortfolio(value: unknown): readonly SkillApplicationTarget[] {
  if (!Array.isArray(value)) {
    throw new PrimeGatewayError();
  }
  const targets = value.map(validateTarget);
  if (targets.length === 0) {
    throw new PrimeGatewayError();
  }
  let previousKey: string | undefined;
  for (const target of targets) {
    const key = [
      target.kind,
      target.provider_id,
      target.application_id,
      target.version,
      target.runtime_id,
    ].join("\u0000");
    if (previousKey !== undefined && previousKey >= key) {
      throw new PrimeGatewayError();
    }
    previousKey = key;
  }
  return Object.freeze(targets);
}

function validateDescriptor(value: unknown): PrimeSidecarDescriptor {
  if (
    !isRecord(value) ||
    !(hasExactKeys(value, [
      "agentDir",
      "artifactLockPath",
      "authorityId",
      "authorityRevision",
      "expectedRuntimeBuildId",
      "gatewayRoot",
      "generation",
      "maxContinuations",
      "maxControllerTokens",
      "maxTurns",
      "model",
      "portfolio",
      "primeSocketPath",
      "primeSourceRoot",
      "provider",
      "probeReady",
      "recoveryReadOnly",
      "rlmMaxChildren",
      "rlmMaxDepth",
      "remainingBudget",
      "sessionDir",
      "sessionId",
      "skillPath",
      "timeoutMs",
      "workspace",
    ]) || hasExactKeys(value, [
      "agentDir", "artifactLockPath", "authorityId", "authorityRevision",
      "expectedRuntimeBuildId", "gatewayRoot", "generation", "maxContinuations",
      "maxControllerTokens", "maxTurns", "model", "portfolio", "primeSocketPath",
      "primeSourceRoot", "provider", "probeReady", "rlmMaxChildren", "rlmMaxDepth",
      "remainingBudget", "sessionDir", "sessionId", "skillPath", "timeoutMs", "workspace",
    ])) ||
    ![
      value.agentDir,
      value.artifactLockPath,
      value.authorityId,
      value.expectedRuntimeBuildId,
      value.gatewayRoot,
      value.model,
      value.primeSocketPath,
      value.primeSourceRoot,
      value.provider,
      value.sessionDir,
      value.sessionId,
      value.skillPath,
      value.workspace,
    ].every(validText) ||
    (value.recoveryReadOnly !== undefined && typeof value.recoveryReadOnly !== "boolean") ||
    !positiveInteger(value.generation) ||
    !positiveInteger(value.authorityRevision) ||
    !positiveInteger(value.maxContinuations) ||
    !positiveInteger(value.maxControllerTokens) ||
    !positiveInteger(value.maxTurns) ||
    !nonNegativeInteger(value.rlmMaxChildren) ||
    (value.rlmMaxDepth !== 0 && value.rlmMaxDepth !== 1) ||
    !positiveInteger(value.timeoutMs)
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    ...(value as unknown as PrimeSidecarDescriptor),
    authorityRevision: Number(value.authorityRevision),
    generation: Number(value.generation),
    maxContinuations: Number(value.maxContinuations),
    maxControllerTokens: Number(value.maxControllerTokens),
    maxTurns: Number(value.maxTurns),
    rlmMaxChildren: Number(value.rlmMaxChildren),
    rlmMaxDepth: value.rlmMaxDepth as 0 | 1,
    recoveryReadOnly: value.recoveryReadOnly === true,
    probeReady: value.probeReady === true,
    portfolio: validatePortfolio(value.portfolio),
    remainingBudget: validateBudget(value.remainingBudget),
    timeoutMs: Number(value.timeoutMs),
  });
}

function validateEnvelope(value: unknown): SidecarEnvelope {
  if (
    !isRecord(value) ||
    value.protocol !== PRIME_GATEWAY_IPC_PROTOCOL ||
    typeof value.id !== "string" ||
    !REQUEST_ID.test(value.id) ||
    (
      value.type !== "command.accept" &&
      value.type !== "client_observations" &&
      value.type !== "client_value_read" &&
      value.type !== "events.stream" &&
      value.type !== "ecosystem_activate" &&
      value.type !== "private.read" &&
      value.type !== "rlm.binding.read" &&
      value.type !== "rlm.message.binding.read" &&
      value.type !== "rlm.lifecycle.read" &&
      value.type !== "authority.update" &&
      value.type !== "session-context.cancel" &&
      value.type !== "session-context.execute"
    )
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "client_observations" &&
    !hasExactKeys(value, ["protocol", "id", "type", "cursor"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "client_value_read" &&
    (!hasExactKeys(value, ["protocol", "id", "type", "reference", "max_bytes"]) ||
      typeof value.reference !== "string" ||
      !Number.isSafeInteger(value.max_bytes) || Number(value.max_bytes) < 1 || Number(value.max_bytes) > MAX_PRIVATE_ATTACHMENT_BYTES)
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "ecosystem_activate" &&
    !hasExactKeys(value, ["protocol", "id", "type", "frame"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "authority.update" &&
    !hasExactKeys(value, ["protocol", "id", "type", "budget"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "command.accept" &&
    !hasExactKeys(value, ["protocol", "id", "type", "command", "private"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "events.stream" &&
    !hasExactKeys(value, ["protocol", "id", "type", "cursor"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    (value.type === "rlm.binding.read" || value.type === "rlm.message.binding.read") &&
    (!hasExactKeys(value, ["protocol", "id", "type", "action_id"]) ||
      typeof value.action_id !== "string" ||
      !REQUEST_ID.test(value.action_id))
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "rlm.lifecycle.read" &&
    !hasExactKeys(value, ["protocol", "id", "type"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "private.read" &&
    !hasExactKeys(value, ["protocol", "id", "type", "reference"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "session-context.execute" &&
    !hasExactKeys(value, ["protocol", "id", "type", "command", "private"])
  ) {
    throw new PrimeGatewayError();
  }
  if (
    value.type === "session-context.cancel" &&
    !hasExactKeys(value, ["protocol", "id", "type", "command_id"])
  ) {
    throw new PrimeGatewayError();
  }
  return value as unknown as SidecarEnvelope;
}

function validateRlmLifecycle(value: unknown): readonly RlmLifecycleObservation[] {
  if (!Array.isArray(value) || value.length > 1024) {
    throw new PrimeGatewayError();
  }
  const seen = new Set<string>();
  const result: RlmLifecycleObservation[] = [];
  for (const item of value) {
    if (!isRecord(item) || typeof item.type !== "string" || typeof item.child_id !== "string" || !REQUEST_ID.test(item.child_id)) {
      throw new PrimeGatewayError();
    }
    if (item.type === "rlm.child.started" && hasExactKeys(item, ["type", "child_id", "native_identity_digest"]) && typeof item.native_identity_digest === "string" && /^[0-9a-f]{64}$/u.test(item.native_identity_digest)) {
      if (seen.has(item.child_id)) throw new PrimeGatewayError();
      seen.add(item.child_id);
      result.push(Object.freeze({ type: item.type, child_id: item.child_id, native_identity_digest: item.native_identity_digest }));
      continue;
    }
    if (item.type === "rlm.child.terminal" && hasExactKeys(item, ["type", "child_id", "status"]) && typeof item.status === "string" && ["completed", "failed", "cancelled"].includes(item.status)) {
      if (!seen.has(item.child_id)) throw new PrimeGatewayError();
      seen.delete(item.child_id);
      result.push(Object.freeze({ type: item.type, child_id: item.child_id, status: item.status as "completed" | "failed" | "cancelled" }));
      continue;
    }
    if (item.type === "rlm.child.deleted" && hasExactKeys(item, ["type", "child_id"]) && !seen.has(item.child_id)) {
      result.push(Object.freeze({ type: item.type, child_id: item.child_id }));
      continue;
    }
    throw new PrimeGatewayError();
  }
  return Object.freeze(result);
}

function validateSessionContextPrivateValues(
  command: SessionContextCommand,
  value: unknown,
): SessionContextPrivateValues {
  if (!isRecord(value)) {
    throw new PrimeGatewayError();
  }
  if (command.operation === "session.attachment.bind") {
    if (
      !hasExactKeys(value, ["body_base64"]) ||
      typeof value.body_base64 !== "string" ||
      value.body_base64.length > Math.ceil(MAX_PRIVATE_ATTACHMENT_BYTES / 3) * 4
    ) {
      throw new PrimeGatewayError();
    }
    const body = Buffer.from(value.body_base64, "base64");
    if (
      body.toString("base64") !== value.body_base64 ||
      body.byteLength !== command.payload.size ||
      body.byteLength > MAX_PRIVATE_ATTACHMENT_BYTES ||
      createHash("sha256").update(body).digest("hex") !== command.payload.sha256
    ) {
      throw new PrimeGatewayError();
    }
    return Object.freeze({ kind: "attachment", body: Uint8Array.from(body) });
  }
  const privateText = (
    field: "instructions" | "label" | "name",
  ): SessionContextPrivateValues => {
    if (!hasExactKeys(value, [field]) || !validPrivateText(value[field])) {
      throw new PrimeGatewayError();
    }
    return Object.freeze({
      kind: field,
      value: value[field],
    }) as SessionContextPrivateValues;
  };
  if (command.operation === "session.name.set") {
    return privateText("name");
  }
  if (command.operation === "session.label.set" && command.payload.label_ref !== null) {
    return privateText("label");
  }
  if (
    (command.operation === "session.branch.summarize" ||
      command.operation === "session.compact") &&
    command.payload.instructions_ref !== null
  ) {
    return privateText("instructions");
  }
  if (!hasExactKeys(value, [])) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({ kind: "none" });
}

function sortedUniqueStrings(
  value: unknown,
  pattern: RegExp,
): readonly string[] {
  if (
    !Array.isArray(value) ||
    value.some((item) => typeof item !== "string" || !pattern.test(item)) ||
    value.some((item, index) => index > 0 && String(value[index - 1]) >= item)
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze([...(value as string[])]);
}

function validateResultProjection(
  value: unknown,
  sourceReceiptRef: string,
): PrivateResultProjection {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["artifact_ids", "media_types", "receipt_ref"]) ||
    value.receipt_ref !== sourceReceiptRef
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    receiptRef: sourceReceiptRef,
    artifactIds: sortedUniqueStrings(value.artifact_ids, REQUEST_ID),
    mediaTypes: sortedUniqueStrings(value.media_types, MEDIA_TYPE_PATTERN),
  });
}

function validateCursor(value: unknown): Readonly<{ generation: number; sequence: number }> | null {
  if (value === null) {
    return null;
  }
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["generation", "sequence"]) ||
    !Number.isSafeInteger(value.generation) ||
    Number(value.generation) < 1 ||
    !Number.isSafeInteger(value.sequence) ||
    Number(value.sequence) < 0
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    generation: Number(value.generation),
    sequence: Number(value.sequence),
  });
}

export class PrimeGatewaySidecar {
  constructor(private readonly options: PrimeGatewaySidecarOptions) {}

  async handleEnvelope(value: unknown): Promise<SidecarResponse> {
    let envelope: SidecarEnvelope;
    try {
      envelope = validateEnvelope(value);
      if (envelope.type === "authority.update") {
        this.options.gateway.updateRemainingBudget(
          validateBudget(envelope.budget, true),
        );
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "authority.accepted",
        });
      }
      if (envelope.type === "ecosystem_activate") {
        const activate = this.options.gateway.activateEcosystem;
        if (activate === undefined) throw new PrimeGatewayError();
        const frame = validatePrimeEcosystemFrame(envelope.frame);
        const result = validateGatewayEcosystemEffectResult(
          await activate.call(this.options.gateway, frame),
        );
        const receipt = validatePrimeEcosystemReceipt({
          authorityDigest: result.authorityDigest,
          featureIds: result.featureIds,
          lifecycleCount: result.lifecycleCount,
          mcpCount: result.mcpCount,
          modelCredentialReads: result.modelCredentialReads,
          ownedProcessCount: result.ownedProcessCount,
          packageCount: result.packageCount,
          portfolioDigest: result.portfolioDigest,
          providerOperations: result.providerOperations,
          registrationCount: result.registrationCount,
          resourceCount: result.resourceCount,
          status: result.status,
        }, frame);
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "ecosystem_receipt",
          receipt,
        });
      }
      if (envelope.type === "command.accept") {
        await this.accept(envelope);
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "command.accepted",
        });
      }
      if (envelope.type === "client_observations") {
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "client_observations.batch",
          ...this.clientObservations(envelope),
        });
      }
      if (envelope.type === "client_value_read") {
        const value = await this.readClientValue(envelope);
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "client_value",
          descriptor: value.descriptor,
          body_base64: value.body_base64,
        });
      }
      if (envelope.type === "private.read") {
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "private.value",
          text: await this.readPrivate(envelope),
        });
      }
      if (envelope.type === "rlm.lifecycle.read") {
        const lifecycle = this.options.gateway.rlmLifecycle;
        if (lifecycle === undefined) {
          throw new PrimeGatewayError();
        }
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "rlm.lifecycle.batch",
          lifecycle: validateRlmLifecycle(lifecycle.call(this.options.gateway)),
        });
      }
      if (envelope.type === "rlm.binding.read") {
        const readBinding = this.options.gateway.rlmBinding;
        if (readBinding === undefined) {
          throw new PrimeGatewayError();
        }
        const binding = readBinding.call(this.options.gateway, envelope.action_id as string);
        if (binding === undefined) {
          throw new PrimeGatewayError();
        }
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "rlm.binding.value",
          binding,
        });
      }
      if (envelope.type === "rlm.message.binding.read") {
        const readBinding = this.options.gateway.rlmMessageBinding;
        const readDelivered = this.options.gateway.rlmMessageDelivered;
        if (readBinding === undefined || readDelivered === undefined) {
          throw new PrimeGatewayError();
        }
        const binding = readBinding.call(this.options.gateway, envelope.action_id as string);
        if (binding === undefined) {
          throw new PrimeGatewayError();
        }
        const delivered = readDelivered.call(this.options.gateway).includes(binding.message_id);
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "rlm.message.binding.value",
          binding: Object.freeze({ ...binding, delivered }),
        });
      }
      if (envelope.type === "session-context.execute") {
        const command = validateSessionContextCommand(envelope.command);
        const execute = this.options.gateway.executeSessionContext;
        if (execute === undefined) {
          throw new PrimeGatewayError();
        }
        const privateValues = validateSessionContextPrivateValues(
          command,
          envelope.private,
        );
        const receipt = validateSessionContextReceipt(
          await execute.call(
            this.options.gateway,
            command,
            () => this.bindSessionContextPrivateValues(command, privateValues),
          ),
        );
        if (
          receipt.command_id !== command.command_id ||
          receipt.session_id !== command.session_id ||
          receipt.generation !== command.generation ||
          receipt.operation !== command.operation
        ) {
          throw new PrimeGatewayError();
        }
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "session-context.receipt",
          receipt,
        });
      }
      if (envelope.type === "session-context.cancel") {
        const commandId = envelope.command_id;
        const cancel = this.options.gateway.cancelSessionContext;
        if (
          typeof commandId !== "string" ||
          !REQUEST_ID.test(commandId) ||
          cancel === undefined
        ) {
          throw new PrimeGatewayError();
        }
        await cancel.call(this.options.gateway, commandId);
        return Object.freeze({
          protocol: PRIME_GATEWAY_IPC_PROTOCOL,
          id: envelope.id,
          type: "session-context.cancel.accepted",
        });
      }
      return Object.freeze({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: envelope.id,
        type: "events.batch",
        events: this.events(envelope),
      });
    } catch {
      privateDiagnosticEnvelopeFailure(value);
      const id = isRecord(value) && typeof value.id === "string" && REQUEST_ID.test(value.id)
        ? value.id
        : "request-invalid";
      return Object.freeze({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id,
        type: "error",
        code: "prime-gateway-sidecar-failed",
      });
    }
  }

  async close(): Promise<void> {
    await this.options.gateway.close();
  }

  private async accept(envelope: SidecarEnvelope): Promise<void> {
    let command = validateControlCommand(envelope.command);
    const privateValues = envelope.private;
    if (!isRecord(privateValues)) {
      throw new PrimeGatewayError();
    }
    if (command.type === "session.create") {
      if (!hasExactKeys(privateValues, ["goal"]) || !validPrivateText(privateValues.goal)) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindInputReference(
        command.command_id,
        command.payload.goal_ref,
        privateValues.goal,
      );
    } else if (command.type === "input.submit") {
      if (!hasExactKeys(privateValues, ["content"]) || !validPrivateText(privateValues.content)) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindInputReference(
        command.command_id,
        command.payload.content_ref,
        privateValues.content,
      );
    } else if (
      command.type === "action.resolve" &&
      command.payload.resolution === "succeeded"
    ) {
      if (!hasExactKeys(privateValues, ["result"])) {
        throw new PrimeGatewayError();
      }
      const sourceReceiptRef = command.payload.receipt_ref;
      const actionId = command.payload.action_id;
      if (
        typeof sourceReceiptRef !== "string" ||
        !REQUEST_ID.test(sourceReceiptRef) ||
        typeof actionId !== "string" ||
        !REQUEST_ID.test(actionId)
      ) {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindResultReference(
        command.command_id,
        actionId,
        sourceReceiptRef,
        validateResultProjection(privateValues.result, sourceReceiptRef),
      );
    } else if (!hasExactKeys(privateValues, [])) {
      throw new PrimeGatewayError();
    }
    await this.options.gateway.accept(command);
  }

  private events(envelope: SidecarEnvelope): readonly ControlEvent[] {
    const cursor = validateCursor(envelope.cursor);
    const replayCursor = cursor ?? {
      generation: this.options.currentGeneration,
      sequence: 0,
    };
    const events = this.options.gateway.eventsAfterCursor(
      replayCursor,
    ).map((event) => {
      const validated = validateControlEvent(event);
      if (validated.generation !== replayCursor.generation) {
        throw new PrimeGatewayError();
      }
      return validated;
    });
    return Object.freeze(events);
  }

  private clientObservations(envelope: SidecarEnvelope): Readonly<{
    observations: readonly PrimeClientObservation[];
    next_cursor: Readonly<{ readonly generation: number; readonly sequence: number }> | null;
  }> {
    const cursor = validateCursor(envelope.cursor);
    const replayCursor = cursor ?? { generation: this.options.currentGeneration, sequence: 0 };
    const observations = this.options.gateway.clientObservationsAfterCursor;
    if (observations === undefined) throw new PrimeGatewayError();
    const batch = observations.call(this.options.gateway, replayCursor);
    let expected = replayCursor.sequence + 1;
    const selected: PrimeClientObservation[] = [];
    for (const [index, observation] of batch.entries()) {
      if (
        observation.active_session_id !== this.options.sessionId ||
        observation.generation !== replayCursor.generation ||
        observation.source_sequence !== expected ||
        JSON.stringify(observation).includes("SENTINEL_BODY")
      ) throw new PrimeGatewayError();
      expected += 1;
      const next_cursor = index + 1 === batch.length ? null : Object.freeze({
        generation: replayCursor.generation,
        sequence: observation.source_sequence,
      });
      const candidate = [...selected, observation];
      if (Buffer.byteLength(JSON.stringify({
        protocol: PRIME_GATEWAY_IPC_PROTOCOL,
        id: envelope.id,
        type: "client_observations.batch",
        observations: candidate,
        next_cursor,
      }), "utf8") > MAX_CLIENT_OBSERVATION_RESPONSE_BYTES) {
        if (selected.length === 0) throw new PrimeGatewayError();
        return Object.freeze({
          observations: Object.freeze(selected),
          next_cursor: Object.freeze({
            generation: replayCursor.generation,
            sequence: selected.at(-1)!.source_sequence,
          }),
        });
      }
      selected.push(observation);
    }
    return Object.freeze({ observations: Object.freeze(selected), next_cursor: null });
  }

  private async readClientValue(envelope: SidecarEnvelope): Promise<Readonly<{
    descriptor: Readonly<{ reference: string; kind: string; media_type: string; size: number; sha256: string }>;
    body_base64: string;
  }>> {
    if (typeof envelope.reference !== "string" || !Number.isSafeInteger(envelope.max_bytes)) throw new PrimeGatewayError();
    const descriptor = await this.options.privateValues.describeClientValue(envelope.reference, this.options.sessionId);
    const body = await this.options.privateValues.readClientValue(envelope.reference, Number(envelope.max_bytes), this.options.sessionId);
    if (
      body.byteLength !== descriptor.size ||
      createHash("sha256").update(body).digest("hex") !== descriptor.sha256
    ) throw new PrimeGatewayError();
    return Object.freeze({
      descriptor: Object.freeze({ reference: descriptor.reference, kind: descriptor.kind, media_type: descriptor.mediaType, size: descriptor.size, sha256: descriptor.sha256 }),
      body_base64: body.toString("base64"),
    });
  }

  private async readPrivate(envelope: SidecarEnvelope): Promise<string> {
    const reference = envelope.reference;
    if (
      typeof reference !== "string" ||
      !/^private:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u
        .test(reference)
    ) {
      throw new PrimeGatewayError();
    }
    return this.options.privateValues.readInput(reference as `private:${string}`);
  }

  private async bindSessionContextPrivateValues(
    command: SessionContextCommand,
    privateValues: SessionContextPrivateValues,
  ): Promise<void> {
    if (privateValues.kind === "attachment") {
      if (command.operation !== "session.attachment.bind") {
        throw new PrimeGatewayError();
      }
      await this.options.privateValues.bindAttachment(
        {
          sessionId: command.session_id,
          inputId: command.payload.input_id,
          attachmentId: command.payload.attachment_id,
          mediaType: command.payload.media_type,
          sha256: command.payload.sha256,
          size: command.payload.size,
        },
        privateValues.body,
      );
      return;
    }
    if (privateValues.kind === "none") {
      return;
    }
    let reference: string | null;
    if (privateValues.kind === "name" && command.operation === "session.name.set") {
      reference = command.payload.name_ref;
    } else if (
      privateValues.kind === "label" &&
      command.operation === "session.label.set"
    ) {
      reference = command.payload.label_ref;
    } else if (
      privateValues.kind === "instructions" &&
      (command.operation === "session.branch.summarize" ||
        command.operation === "session.compact")
    ) {
      reference = command.payload.instructions_ref;
    } else {
      throw new PrimeGatewayError();
    }
    if (reference === null) {
      throw new PrimeGatewayError();
    }
    await this.options.privateValues.bindInputReference(
      command.command_id,
      reference,
      privateValues.value,
    );
  }
}

function privateDiagnosticEnvelopeFailure(value: unknown): void {
  if (process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS !== "1") {
    return;
  }
  const type = isRecord(value) && typeof value.type === "string"
    && SIDE_CAR_ENVELOPE_TYPES.has(value.type as SidecarEnvelopeType)
    ? value.type
    : "invalid";
  const commandType = type === "command.accept" && isRecord(value)
    && isRecord(value.command) && typeof value.command.type === "string"
    && new Set(["session.create", "input.submit", "action.resolve", "session.cancel"])
      .has(value.command.type)
    ? value.command.type.replace(".", "-")
    : undefined;
  process.stderr.write(
    `asterion-prime-sidecar-failed:${commandType ?? type}\n`,
  );
}

function privateDiagnosticProbeCreateFailure(
  descriptor: PrimeSidecarDescriptor,
  stage: "skill-bridge" | "native-session",
): void {
  if (
    !descriptor.probeReady ||
    process.env.ASTERION_PRIME_PRIVATE_DIAGNOSTICS !== "1"
  ) {
    return;
  }
  process.stderr.write(`asterion-prime-probe-create:${stage}\n`);
}

export class PrimeBoundPrivateInputs implements PrimeGatewayPrivateInputs {
  constructor(private readonly privateValues: PrivateValueStore) {}

  async readInput(reference: string): Promise<string> {
    return this.privateValues.readBoundInputReference(reference);
  }

  readBoundAttachment(
    sessionId: string,
    inputId: string,
    attachmentId: string,
  ): ReturnType<PrivateValueStore["readBoundAttachment"]> {
    return this.privateValues.readBoundAttachment(
      sessionId,
      inputId,
      attachmentId,
    );
  }

  readBoundAttachments(
    sessionId: string,
    inputId: string,
    expected: Parameters<PrivateValueStore["readBoundAttachments"]>[2],
  ): ReturnType<PrivateValueStore["readBoundAttachments"]> {
    return this.privateValues.readBoundAttachments(sessionId, inputId, expected);
  }

  putContinuationLocator(
    locator: Parameters<PrivateValueStore["putContinuationLocator"]>[0],
  ): ReturnType<PrivateValueStore["putContinuationLocator"]> {
    return this.privateValues.putContinuationLocator(locator);
  }

  readContinuationLocator(
    binding: import("./durable-store.js").GatewayContextBinding,
  ): ReturnType<PrivateValueStore["readContinuationLocator"]> {
    return this.privateValues.readContinuationLocator(
      binding as PrivateContinuationBinding,
    );
  }

  ensurePreparedContinuationLocator(
    binding: import("./durable-store.js").GatewayContextBinding,
  ): ReturnType<PrivateValueStore["ensurePreparedContinuationLocator"]> {
    return this.privateValues.ensurePreparedContinuationLocator(
      binding as PrivateContinuationBinding,
    );
  }

  readPreparedContinuationLocator(
    binding: import("./durable-store.js").GatewayContextBinding,
    allowMissing: boolean,
  ): ReturnType<PrivateValueStore["readPreparedContinuationLocator"]> {
    return this.privateValues.readPreparedContinuationLocator(
      binding as PrivateContinuationBinding,
      allowMissing,
    );
  }
}

function encodeResponse(value: SidecarResponse): string {
  return `${JSON.stringify(value)}\n`;
}

export async function servePrimeGatewaySidecar(
  sidecar: PrimeGatewaySidecar,
  lines: AsyncIterable<string>,
  write: (frame: string) => Promise<void>,
): Promise<void> {
  const pending = new Set<Promise<void>>();
  let writeQueue: Promise<void> = Promise.resolve();
  for await (const line of lines) {
    let parsed: unknown;
    try {
      parsed = Buffer.byteLength(line, "utf8") > MAX_PRIVATE_FRAME_BYTES
        ? {}
        : JSON.parse(line);
    } catch {
      parsed = {};
    }
    const response = sidecar.handleEnvelope(parsed);
    let operation: Promise<void>;
    operation = response
      .then((value) => {
        writeQueue = writeQueue.then(() => write(encodeResponse(value)));
        return writeQueue;
      })
      .finally(() => {
        pending.delete(operation);
      });
    pending.add(operation);
  }
  await Promise.all(pending);
  await writeQueue;
}

function readPrivateDescriptor(): PrimeSidecarDescriptor {
  const fd = Number(process.env.ASTERION_PRIME_PRIVATE_FD);
  if (!Number.isSafeInteger(fd) || fd < 3) {
    throw new PrimeGatewayError();
  }
  try {
    return validateDescriptor(JSON.parse(readFileSync(fd, { encoding: "utf8" })));
  } catch {
    throw new PrimeGatewayError();
  }
}

async function writeSkillDiscovery(
  descriptor: PrimeSidecarDescriptor,
  bridge: AsterionSkillBridge,
  token: string,
): Promise<void> {
  if (!TOKEN_PATTERN.test(token)) {
    throw new PrimeGatewayError();
  }
  await ensurePrivateDirectory(descriptor.agentDir);
  const record = {
    protocol: PRIME_GATEWAY_SKILL_DISCOVERY,
    socket_path: bridge.socketPath,
    token,
    session_id: descriptor.sessionId,
  };
  await atomicReplacePrivateFile(
    descriptor.agentDir,
    PRIME_GATEWAY_SKILL_DISCOVERY_FILE,
    Buffer.concat([canonicalJsonBytes(record), Buffer.from("\n")]),
  );
}

async function writeRlmHostDiscovery(
  descriptor: PrimeSidecarDescriptor,
  socketPath: string,
  token: string,
  budget: SkillBudget,
): Promise<void> {
  if (!TOKEN_PATTERN.test(token)) {
    throw new PrimeGatewayError();
  }
  await ensurePrivateDirectory(descriptor.agentDir);
  await atomicReplacePrivateFile(
    descriptor.agentDir,
    PRIME_GATEWAY_RLM_HOST_DISCOVERY_FILE,
    Buffer.concat([canonicalJsonBytes({
      protocol: PRIME_GATEWAY_RLM_HOST_DISCOVERY,
      socket_path: socketPath,
      token,
      session_id: descriptor.sessionId,
      budget,
    }), Buffer.from("\n")]),
  );
}

async function writeRlmHostShim(descriptor: PrimeSidecarDescriptor): Promise<void> {
  let shim: Buffer;
  try {
    shim = await readFile(new URL("../../resources/rlm-host-shim.mjs", import.meta.url));
  } catch {
    throw new PrimeGatewayError();
  }
  await ensurePrivateDirectory(descriptor.agentDir);
  await atomicReplacePrivateFile(
    descriptor.agentDir,
    PRIME_GATEWAY_RLM_HOST_SHIM_FILE,
    shim,
  );
}

async function atomicReplacePrivateFile(
  directory: string,
  targetName: string,
  bytes: Uint8Array,
): Promise<void> {
  if (!/^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$/u.test(targetName)) {
    throw new PrimeGatewayError();
  }
  const temporary = join(directory, `.asterion-${randomUUID()}.tmp`);
  const descriptor = await open(
    temporary,
    constants.O_CREAT | constants.O_EXCL | constants.O_WRONLY | constants.O_NOFOLLOW,
    0o600,
  );
  let closed = false;
  let renamed = false;
  try {
    await descriptor.chmod(0o600);
    await descriptor.writeFile(bytes);
    await descriptor.datasync();
    await descriptor.close();
    closed = true;
    await rename(temporary, join(directory, targetName));
    renamed = true;
    await syncPrivateDirectory(directory);
  } finally {
    if (!closed) {
      await descriptor.close().catch(() => undefined);
    }
    if (!renamed) {
      await unlink(temporary).catch(() => undefined);
    }
  }
}

async function removeSkillDiscovery(descriptor: PrimeSidecarDescriptor): Promise<void> {
  await unlink(join(descriptor.agentDir, PRIME_GATEWAY_SKILL_DISCOVERY_FILE))
    .catch(() => undefined);
  await syncPrivateDirectory(descriptor.agentDir).catch(() => undefined);
}

async function removeRlmHostDiscovery(descriptor: PrimeSidecarDescriptor): Promise<void> {
  try {
    await Promise.all([
      unlink(join(descriptor.agentDir, PRIME_GATEWAY_RLM_HOST_DISCOVERY_FILE)),
      unlink(join(descriptor.agentDir, PRIME_GATEWAY_RLM_HOST_SHIM_FILE)),
    ]);
    await syncPrivateDirectory(descriptor.agentDir);
  } catch {
    // Nothing was published, or cleanup is already in progress.
  }
}

function restoredBridgeContext(
  store: GatewayDurableStore,
  generation: number,
  descriptor: PrimeSidecarDescriptor,
): Readonly<{
  goalId: string;
  authorityRevision: number;
  causalParentIds: readonly string[];
}> | undefined {
  let created:
    | Extract<ControlEvent, { readonly type: "session.created" }>
    | undefined;
  let terminal = false;
  for (const receipt of store.eventsAfter(0)) {
    const event = receipt.event;
    if (event.generation !== generation) {
      continue;
    }
    if (event.type === "session.created") {
      created = event;
    }
    if ([
      "session.budget-limited",
      "session.cancelled",
      "session.completed",
      "session.failed",
    ].includes(event.type)) {
      terminal = true;
    }
  }
  if (created === undefined || terminal || store.snapshot().primeIdentity === undefined) {
    return undefined;
  }
  if (
    created.payload.authority_id !== descriptor.authorityId ||
    created.payload.authority_revision !== descriptor.authorityRevision
  ) {
    throw new PrimeGatewayError();
  }
  return Object.freeze({
    goalId: created.payload.goal_id,
    authorityRevision: created.payload.authority_revision,
    causalParentIds: Object.freeze([created.payload.goal_id]),
  });
}

async function createSidecarFromDescriptor(
  descriptor: PrimeSidecarDescriptor,
): Promise<PrimeGatewaySidecar> {
  const transport = new PrimeDaemonClient({
    clientId: `asterion-${descriptor.sessionId}`,
    connectTimeoutMs: descriptor.timeoutMs,
    requestTimeoutMs: descriptor.timeoutMs,
    expectedRuntimeBuildId: descriptor.expectedRuntimeBuildId,
  });
  await transport.connect(descriptor.primeSocketPath);
  const store = await GatewayDurableStore.open(
    descriptor.gatewayRoot,
    descriptor.sessionId,
  );
  store.registerEventGeneration(descriptor.generation);
  await ensurePrivateDirectory(descriptor.sessionDir);
  const privateValues = await PrivateValueStore.open(descriptor.gatewayRoot, {
    continuationRoot: descriptor.sessionDir,
  });
  const boundPrivateInputs = new PrimeBoundPrivateInputs(privateValues);
  let artifactEvidence: Awaited<ReturnType<typeof verifyPrimeArtifact>>;
  try {
    const lock = await loadPrimeArtifactLock(pathToFileURL(descriptor.artifactLockPath));
    artifactEvidence = await verifyPrimeArtifact(descriptor.primeSourceRoot, lock);
  } catch (error) {
    transport.close();
    throw error;
  }
  let checkpointManager: PrimeCheckpointManager | undefined;
  let ecosystemAdapterPromise: Promise<PrimeEcosystemAdapter> | undefined;
  const ecosystem = Object.freeze({
    async activate(frame: PrimeEcosystemFrame): Promise<GatewayEcosystemEffectResult> {
      ecosystemAdapterPromise ??= loadPrimeEcosystemModule({
        artifactLockPath: descriptor.artifactLockPath,
        bundlePath: join(
          dirname(descriptor.artifactLockPath),
          "prime-ecosystem-module.mjs",
        ),
        moduleLockPath: join(
          dirname(descriptor.artifactLockPath),
          "prime-ecosystem-module-lock.json",
        ),
      }).then(({ lock, module }) => new PrimeEcosystemAdapter({
        lock,
        module,
        store,
      }));
      return (await ecosystemAdapterPromise).activate(frame);
    },
  });
  let gateway: PrimeGateway;
  let skillBridge: AsterionSkillBridge | undefined;
  let skillBridgeRoot: string | undefined;
  let nativeRootSession: PrimeSession | undefined;
  let rlmHostClose: (() => Promise<void>) | undefined;
  let sessionReady: (() => void) | undefined;
  let currentRemainingBudget = descriptor.remainingBudget;
  const nativeRlmChildReapers = new Map<string, Promise<void>>();

  const reapNativeRlmChild = async (actionId: string, childId: string) => {
    const root = nativeRootSession;
    if (root === undefined) {
      throw new PrimeGatewayError();
    }
    let status: "completed" | "failed" = "completed";
    try {
      await root.waitForNativeRlmChild(`wait-${actionId}`, childId);
    } catch {
      status = "failed";
    }
    try {
      await root.terminateNativeRlmChild(`reap-${actionId}`, childId);
    } catch {
      status = "failed";
    }
    await store.recordRlmLifecycle({
      type: "rlm.child.terminal",
      child_id: childId,
      status,
    });
    if (status === "completed") {
      await store.recordRlmLifecycle({ type: "rlm.child.deleted", child_id: childId });
    }
  };

  const closeRlmHostBridge = async () => {
    const close = rlmHostClose;
    rlmHostClose = undefined;
    if (close !== undefined) {
      await close();
    }
    await removeRlmHostDiscovery(descriptor);
  };

  const closeSkillBridge = async () => {
    await closeRlmHostBridge();
    const reapers = [...nativeRlmChildReapers.values()];
    await Promise.allSettled(reapers);
    const current = skillBridge;
    skillBridge = undefined;
    if (current !== undefined) {
      await current.close();
    }
    if (skillBridgeRoot !== undefined) {
      await rm(skillBridgeRoot, { force: true, recursive: true }).catch(() => undefined);
      skillBridgeRoot = undefined;
    }
    await removeSkillDiscovery(descriptor);
  };

  const startRlmHostBridge = async (
    context: Readonly<{
      goalId: string;
      authorityRevision: number;
      causalParentIds: readonly string[];
    }>,
    ready: Promise<void>,
  ) => {
    const token = generateSkillBridgeToken();
    await ensurePrivateDirectory(descriptor.agentDir);
    await writeRlmHostShim(descriptor);
    const socketPath = join(descriptor.agentDir, "r.sock");
    const bridge = new RlmHostBridge({
      sessionId: descriptor.sessionId,
      maxSpawnCount: descriptor.rlmMaxChildren,
      admitSpawn: async (proposal: RlmSpawnProposal) => {
        try {
          await ready;
          const inputRef = await privateValues.putInput(proposal.goalText);
          const identity = gateway.nextEventIdentity();
          const actionId = deriveControlActionId(
            descriptor.sessionId,
            proposal.idempotencyKey,
          );
          await store.recordRlmBinding({
            action_id: actionId,
            child_id: proposal.childId,
            authority_revision: context.authorityRevision,
            depth: proposal.rlmDepth,
            model_selector_digest: proposal.modelSelectorDigest,
          });
          const event = validateControlEvent({
            protocol: "asterion.agent-control/v1",
            event_id: identity.eventId,
            session_id: descriptor.sessionId,
            generation: descriptor.generation,
            sequence: identity.sequence,
            emitted_at: identity.emittedAt,
            type: "action.proposed",
            payload: {
              action_id: actionId,
              authority_revision: context.authorityRevision,
              idempotency_key: proposal.idempotencyKey,
              kind: "child.spawn",
              target: { kind: "child", child_id: proposal.childId },
              input_ref: inputRef,
              expected_artifacts: [],
              budget: proposal.budget,
              causal_parent_ids: context.causalParentIds,
            },
          });
          await gateway.emitActionProposal(event);
          const admission = await gateway.waitForAdmission(actionId);
          return Object.freeze({
            resolution: admission.resolution,
            childId: proposal.childId,
          });
        } catch {
          return Object.freeze({ resolution: "uncertain" as const, childId: proposal.childId });
        }
      },
      admitMessage: async (proposal: RlmMessageProposal) => {
        try {
          await ready;
          const inputRef = await privateValues.putInput(proposal.bodyText);
          const identity = gateway.nextEventIdentity();
          const actionId = deriveControlActionId(
            descriptor.sessionId,
            proposal.requestId,
          );
          await store.recordRlmMessageBinding({
            action_id: actionId,
            message_id: proposal.messageId,
            sender_id: proposal.senderId,
            recipient_id: proposal.recipientId,
            authority_revision: context.authorityRevision,
            body_digest: createHash("sha256").update(proposal.bodyText).digest("hex"),
          });
          const event = validateControlEvent({
            protocol: "asterion.agent-control/v1",
            event_id: identity.eventId,
            session_id: descriptor.sessionId,
            generation: descriptor.generation,
            sequence: identity.sequence,
            emitted_at: identity.emittedAt,
            type: "action.proposed",
            payload: {
              action_id: actionId,
              authority_revision: context.authorityRevision,
              idempotency_key: proposal.requestId,
              kind: "child.message",
              target: { kind: "child", child_id: proposal.recipientId },
              input_ref: inputRef,
              expected_artifacts: [],
              budget: {
                ...currentRemainingBudget,
              },
              causal_parent_ids: context.causalParentIds,
            },
          });
          await gateway.emitActionProposal(event);
          const admission = await gateway.waitForAdmission(actionId);
          return Object.freeze({
            resolution: admission.resolution,
            messageId: proposal.messageId,
          });
        } catch {
          return Object.freeze({ resolution: "uncertain" as const, messageId: proposal.messageId });
        }
      },
      admitDelete: async (proposal) => {
        try {
          await ready;
          const identity = gateway.nextEventIdentity();
          const actionId = deriveControlActionId(descriptor.sessionId, proposal.requestId);
          const event = validateControlEvent({
            protocol: "asterion.agent-control/v1", event_id: identity.eventId, session_id: descriptor.sessionId,
            generation: descriptor.generation, sequence: identity.sequence, emitted_at: identity.emittedAt,
            type: "action.proposed", payload: {
              action_id: actionId, authority_revision: context.authorityRevision, idempotency_key: proposal.requestId,
              kind: "child.cancel", target: { kind: "child", child_id: proposal.childId },
              expected_artifacts: [], budget: { ...currentRemainingBudget }, causal_parent_ids: context.causalParentIds,
            },
          });
          await gateway.emitActionProposal(event);
          const admission = await gateway.waitForAdmission(actionId);
          return Object.freeze({ resolution: admission.resolution, childId: proposal.childId });
        } catch { return Object.freeze({ resolution: "uncertain" as const, childId: proposal.childId }); }
      },
      recordMessageDelivered: async (event: RlmMessageDelivery) => {
        await store.recordRlmMessageDelivered(event.messageId);
      },
      recordLifecycle: async (event) => {
        if (event.type === "rlm.child.started") {
          await store.recordRlmLifecycle({
            type: event.type,
            child_id: event.childId,
            native_identity_digest: event.nativeIdentityDigest,
          });
          return;
        }
        if (event.type === "rlm.child.deleted") {
          await store.recordRlmLifecycle({ type: event.type, child_id: event.childId });
          return;
        }
        await store.recordRlmLifecycle({
          type: event.type,
          child_id: event.childId,
          status: event.status,
        });
      },
    });
    const listener = await listenRlmHostBridge(
      socketPath,
      descriptor.sessionId,
      token,
      bridge,
    );
    rlmHostClose = listener.close;
    try {
      const childDeadlineMs = Math.min(currentRemainingBudget.deadline_ms, 30_000);
      if (childDeadlineMs <= 0) {
        throw new PrimeGatewayError();
      }
      await writeRlmHostDiscovery(descriptor, socketPath, token, {
        controller_tokens: Math.floor(currentRemainingBudget.controller_tokens / 2),
        application_tokens: Math.floor(currentRemainingBudget.application_tokens / 2),
        child_tokens: Math.floor(currentRemainingBudget.child_tokens / 2),
        aggregate_tokens: Math.floor(currentRemainingBudget.aggregate_tokens / 2),
        cost_micros: Math.floor(currentRemainingBudget.cost_micros / 2),
        deadline_ms: childDeadlineMs,
      });
    } catch (error) {
      await closeRlmHostBridge();
      throw error;
    }
  };

  const startSkillBridge = async (
    context: Readonly<{
      goalId: string;
      authorityRevision: number;
      causalParentIds: readonly string[];
    }>,
    ready: Promise<void>,
  ) => {
    await closeSkillBridge();
    const token = generateSkillBridgeToken();
    skillBridgeRoot = join(
      descriptor.agentDir,
      `b${process.pid}-${randomUUID().slice(0, 8)}`,
    );
    skillBridge = await AsterionSkillBridge.listen({
      root: skillBridgeRoot,
      sessionId: descriptor.sessionId,
      authorityRevision: context.authorityRevision,
      generation: descriptor.generation,
      goalId: context.goalId,
      causalParentIds: context.causalParentIds,
      token,
      portfolio: descriptor.portfolio,
      remainingBudget: currentRemainingBudget,
      privateValues,
      beforeEffect: () => ready,
      nextEventIdentity: () => gateway.nextEventIdentity(),
      emitActionProposal: async (event) => {
        await ready;
        if (
          descriptor.rlmMaxDepth === 1 &&
          event.type === "action.proposed" &&
          event.payload.kind === "child.spawn"
        ) {
          const actionId = event.payload.action_id;
          const target = event.payload.target;
          if (target.kind !== "child") {
            throw new PrimeGatewayError();
          }
          await store.recordRlmBinding({
            action_id: actionId,
            child_id: target.child_id,
            authority_revision: event.payload.authority_revision,
            depth: 1,
            model_selector_digest: createHash("sha256")
              .update(descriptor.model, "utf8")
              .digest("hex"),
          });
        } else if (
          descriptor.rlmMaxDepth === 1 &&
          event.type === "action.proposed" &&
          event.payload.kind === "child.message"
        ) {
          const target = event.payload.target;
          if (target.kind !== "child") throw new PrimeGatewayError();
          const body = await privateValues.readInput(
            event.payload.input_ref as `private:${string}`,
          );
          await store.recordRlmMessageBinding({
            action_id: event.payload.action_id,
            message_id: event.payload.action_id,
            sender_id: descriptor.sessionId,
            recipient_id: target.child_id,
            authority_revision: event.payload.authority_revision,
            body_digest: createHash("sha256").update(body, "utf8").digest("hex"),
          });
        }
        await gateway.emitActionProposal(event);
      },
      waitForAdmission: (actionId) => gateway.waitForAdmission(actionId),
      afterAdmission: async (event) => {
        if (descriptor.rlmMaxDepth !== 1 || event.type !== "action.proposed") return;
        if (event.payload.kind === "child.message") {
          const root = nativeRootSession;
          const target = event.payload.target;
          if (root === undefined || target.kind !== "child") {
            throw new PrimeGatewayError();
          }
          const body = await privateValues.readInput(
            event.payload.input_ref as `private:${string}`,
          );
          await root.sendNativeRlmChildMessage(String(event.payload.action_id), target.child_id, body);
          await store.recordRlmMessageDelivered(String(event.payload.action_id));
          return;
        }
        if (event.payload.kind !== "child.spawn") return;
        const root = nativeRootSession;
        const target = event.payload.target;
        if (root === undefined || target.kind !== "child") {
          throw new PrimeGatewayError();
        }
        const goal = await privateValues.readInput(
          event.payload.input_ref as `private:${string}`,
        );
        const child = await root.spawnNativeRlmChild(
          String(event.payload.action_id),
          target.child_id,
          goal,
        );
        await store.recordRlmLifecycle({
          type: "rlm.child.started",
          child_id: target.child_id,
          native_identity_digest: createHash("sha256")
            .update(`${child.activeSessionId}:${child.transcriptSessionId}`, "utf8")
            .digest("hex"),
        });
        const actionId = String(event.payload.action_id);
        const reaper = reapNativeRlmChild(actionId, target.child_id).finally(() => {
          nativeRlmChildReapers.delete(target.child_id);
        });
        nativeRlmChildReapers.set(target.child_id, reaper);
      },
      waitForTerminal: (actionId) => gateway.waitForTerminal(actionId),
      actionStatus: (actionId) => gateway.actionStatus(actionId),
    });
    await writeSkillDiscovery(descriptor, skillBridge, token);
    try {
      await startRlmHostBridge(context, ready);
    } catch (error) {
      await closeSkillBridge();
      throw error;
    }
  };

  gateway = await PrimeGateway.open({
    sessionId: descriptor.sessionId,
    generation: descriptor.generation,
    authorityId: descriptor.authorityId,
    ecosystem,
    restoreExistingSession: !descriptor.recoveryReadOnly,
    store,
    clientObservationValues: privateValues,
    privateValues: boundPrivateInputs,
    privateResults: privateValues,
    async createSession(goal, bindIdentity, context) {
      const ready = new Promise<void>((resolve) => {
        sessionReady = resolve;
      });
      try {
        await startSkillBridge(context, ready);
      } catch (error) {
        privateDiagnosticProbeCreateFailure(descriptor, "skill-bridge");
        throw error;
      }
      try {
        const session = await PrimeSession.create({
          transport,
          sessionId: descriptor.sessionId,
          privateConfig: {
            workspace: descriptor.workspace,
            agentDir: descriptor.agentDir,
            sessionDir: descriptor.sessionDir,
            provider: descriptor.provider,
            model: descriptor.model,
            skillPath: descriptor.skillPath,
            goal,
            maxContinuations: descriptor.maxContinuations,
            maxTurns: descriptor.maxTurns,
            maxControllerTokens: descriptor.maxControllerTokens,
            timeoutMs: descriptor.timeoutMs,
            rlmMaxDepth: descriptor.rlmMaxDepth,
          },
          bindIdentity,
        });
        nativeRootSession = session;
        if (descriptor.probeReady) {
          sessionReady?.();
          sessionReady = undefined;
        }
        return session;
      } catch (error) {
        privateDiagnosticProbeCreateFailure(descriptor, "native-session");
        sessionReady = undefined;
        await closeSkillBridge();
        throw error;
      }
    },
    restoreSession(identity, onRecovered) {
      const session = PrimeSession.restore({
        transport,
        sessionId: descriptor.sessionId,
        activeSessionId: identity.activeSessionId,
        transcriptSessionId: identity.transcriptSessionId,
        continuationId: identity.continuationId,
        sessionPath: identity.sessionPath,
      });
      nativeRootSession = session;
      return (async () => {
        await session.ensureManualCompactionOnly("restore-policy");
        const cursor = store.snapshot().primeCursor;
        if (cursor === undefined) {
          throw new PrimeGatewayError();
        }
        if (identity.pendingResume !== undefined) {
          const resumed = await session.resumeContinuation(
            identity.pendingResume.commandId,
            identity.pendingResume.target,
          );
          session.adoptContinuation(resumed.locator);
        } else if (identity.pendingForkClone !== undefined) {
          const replacement = identity.pendingForkClone.operation === "session.fork"
            ? await session.forkContext(
                identity.pendingForkClone.commandId,
                identity.continuationId,
                identity.pendingForkClone.selectedEntryId,
                identity.pendingForkClone.position,
              )
            : await session.cloneContext(
                identity.pendingForkClone.commandId,
                identity.continuationId,
                identity.pendingForkClone.selectedEntryId,
              );
          session.adoptContinuation(replacement.locator);
        }
        const attachResponse = await session.attach("restore-attach", cursor);
        const recovery = recoveryFromAttach(
          attachResponse,
          session.activeSessionId,
          session.transcriptSessionId,
          cursor,
        );
        await onRecovered({
          transport,
          primeCursor: recovery.primeCursor,
          transcriptSessionId: session.transcriptSessionId,
          supervisorGeneration: transport.hello?.supervisorGeneration ?? identity.supervisorGeneration,
          sessionStatus: recovery.sessionStatus,
        });
        return session;
      })();
    },
    async createCheckpoint(checkpointId, coveredSequence, onRecovered) {
      const identity = store.snapshot().primeIdentity;
      const cursor = store.snapshot().primeCursor;
      if (identity === undefined || cursor === undefined) {
        throw new PrimeGatewayError();
      }
      checkpointManager ??= await PrimeCheckpointManager.open({
        sessionId: descriptor.sessionId,
        asterionGeneration: descriptor.generation,
        activeSessionId: identity.activeSessionId,
        transcriptSessionId: identity.transcriptSessionId,
        artifactEvidence,
        expectedRuntimeBuildId: descriptor.expectedRuntimeBuildId,
        privateValues,
        transport,
        runtime: {
          async stop() {
            transport.close();
          },
          async relaunch() {
            const relaunched = new PrimeDaemonClient({
              clientId: `asterion-${descriptor.sessionId}-checkpoint`,
              connectTimeoutMs: descriptor.timeoutMs,
              requestTimeoutMs: descriptor.timeoutMs,
              expectedRuntimeBuildId: descriptor.expectedRuntimeBuildId,
            });
            await relaunched.connect(descriptor.primeSocketPath);
            return relaunched;
          },
        },
        primeCursor: cursor,
      });
      return checkpointManager.create(checkpointId, coveredSequence, onRecovered);
    },
    onSessionReady() {
      sessionReady?.();
      sessionReady = undefined;
    },
  });
  const recoveredContext = restoredBridgeContext(store, descriptor.generation, descriptor);
  if (recoveredContext !== undefined && !descriptor.recoveryReadOnly) {
    await startSkillBridge(recoveredContext, Promise.resolve());
  }

  return new PrimeGatewaySidecar({
    currentGeneration: descriptor.generation,
    sessionId: descriptor.sessionId,
    privateValues,
    gateway: {
      accept: (command) => gateway.accept(command),
      updateRemainingBudget: (budget) => {
        currentRemainingBudget = budget;
        skillBridge?.updateRemainingBudget(budget);
      },
      eventsAfterCursor: (cursor) =>
        store.eventsAfterCursor(cursor).map((receipt) => receipt.event),
      clientObservationsAfterCursor: (cursor) =>
        gateway.clientObservationsAfterCursor(cursor),
      rlmLifecycle: () => store.rlmLifecycle(),
      rlmBinding: (actionId) => store.rlmBinding(actionId),
      rlmMessageBinding: (actionId) => store.rlmMessageBinding(actionId),
      rlmMessageDelivered: () => store.rlmMessageDelivered(),
      activateEcosystem: (frame) => gateway.activateEcosystem(frame),
      executeSessionContext: (command, preparePrivate) =>
        gateway.executeSessionContext(command, preparePrivate),
      cancelSessionContext: (commandId) => gateway.cancelSessionContext(commandId),
      close: async () => {
        let failed = false;
        try {
          await closeSkillBridge();
        } catch {
          failed = true;
        }
        try {
          await gateway.detach();
        } catch {
          failed = true;
        }
        try {
          await gateway.close();
        } catch {
          failed = true;
        }
        try {
          transport.close();
        } catch {
          failed = true;
        }
        if (failed) {
          throw new PrimeGatewayError();
        }
      },
    },
  });
}

async function run(): Promise<void> {
  let stage = "descriptor";
  let sidecar: Awaited<ReturnType<typeof createSidecarFromDescriptor>> | undefined;
  try {
    const descriptor = readPrivateDescriptor();
    stage = "sidecar";
    sidecar = await createSidecarFromDescriptor(descriptor);
    const rl = readline.createInterface({
      input: process.stdin,
      crlfDelay: Infinity,
    });
    stage = "serve";
    await servePrimeGatewaySidecar(sidecar, rl, async (frame) => {
      if (!process.stdout.write(frame)) {
        await new Promise<void>((resolve) => process.stdout.once("drain", resolve));
      }
    });
  } catch {
    process.stderr.write(`asterion-prime-sidecar-stage:${stage}\n`);
    throw new PrimeGatewayError();
  } finally {
    if (sidecar !== undefined) {
      stage = "close";
      try {
        await sidecar.close();
      } catch {
        process.stderr.write(`asterion-prime-sidecar-stage:${stage}\n`);
        throw new PrimeGatewayError();
      }
    }
  }
}

if (import.meta.url === `file://${process.argv[1]}`) {
  run()
    .catch(() => {
      process.exitCode = 1;
    });
}
