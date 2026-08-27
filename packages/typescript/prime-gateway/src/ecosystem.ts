import { createHash } from "node:crypto";
import {
  lstatSync,
  readFileSync,
  readdirSync,
  realpathSync,
} from "node:fs";
import type { Stats } from "node:fs";
import { basename, isAbsolute, join, normalize } from "node:path";

export const PRIME_ECOSYSTEM_FRAME = "asterion.prime-ecosystem-frame/v1";
export const PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST =
  "c64aecdec9ddff21fb7ed493cc1837eb68bf428fc94803a65e6c185aca0fbba3";
export const PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST =
  "b02188c15e551cc41f3b93044417556db2e4c50cbf158cb768ac0f25962a3aab";
export const PRIME_ECOSYSTEM_BUNDLE_DIGEST =
  "4cf832dbc246daf6fbb90b791caed72f8513477541fad9516a333a03dfe3ca3a";
export const MAX_ECOSYSTEM_BYTES = 8 * 1024 * 1024;
export const MAX_ECOSYSTEM_ENTRIES = 4096;
export const MAX_ECOSYSTEM_PROCESSES = 1;
export const MAX_ECOSYSTEM_DEADLINE_MS = 30_000;

const DIGEST = /^[0-9a-f]{64}$/u;
const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const EFFECT_ID = /^ecosystem:[A-Za-z0-9][A-Za-z0-9._:-]{0,127}:[0-9a-f]{32}$/u;
const VERSION = /^(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)\.(?:0|[1-9][0-9]*)$/u;
const RESOURCE_KINDS = new Set([
  "context-file",
  "extension",
  "markdown-skill",
  "mcp-server",
  "package",
  "prompt-template",
  "python-skill",
]);
const REGISTRATION_KINDS = new Set(["command", "provider-model", "tool"]);
const SOURCE_KINDS = new Set(["installed-distribution", "local-child"]);
const SCOPES = new Set(["global", "project", "session"]);
const TERMINAL_STATUSES = new Set([
  "cancelled",
  "failed",
  "succeeded",
  "uncertain",
]);
const RESOURCE_FEATURES: Readonly<Record<string, readonly string[]>> = {
  "context-file": [
    "ecosystem.collision-diagnostics",
    "ecosystem.context-files",
  ],
  extension: ["ecosystem.extensions-lifecycle"],
  "markdown-skill": ["ecosystem.skills"],
  "mcp-server": ["ecosystem.mcp"],
  package: ["ecosystem.packages"],
  "prompt-template": ["ecosystem.prompt-templates"],
  "python-skill": ["ecosystem.skills"],
};
const REGISTRATION_FEATURES: Readonly<Record<string, string>> = {
  command: "ecosystem.extension-state-commands",
  "provider-model": "ecosystem.custom-providers-models",
  tool: "ecosystem.tools",
};

export interface PrimeEcosystemSource {
  readonly contentDigest: string;
  readonly kind: "local-child" | "installed-distribution";
  readonly sourceId: string;
  readonly version: string;
}

export interface PrimeEcosystemResource {
  readonly contentDigest: string;
  readonly kind:
    | "context-file"
    | "prompt-template"
    | "markdown-skill"
    | "python-skill"
    | "extension"
    | "package"
    | "mcp-server";
  readonly projectionPath: string;
  readonly resourceId: string;
  readonly scope: "session" | "project" | "global";
  readonly source: PrimeEcosystemSource;
  readonly version: string;
}

export interface PrimeEcosystemRegistration {
  readonly extensionId: string;
  readonly kind: "command" | "tool" | "provider-model";
  readonly registrationId: string;
  readonly version: string;
}

export interface PrimeEcosystemLimits {
  readonly deadlineMs: number;
  readonly maxBytes: number;
  readonly maxEntries: number;
  readonly maxProcesses: number;
}

export interface PrimeEcosystemFrame {
  readonly format: typeof PRIME_ECOSYSTEM_FRAME;
  readonly effectId: string;
  readonly authorityDigest: string;
  readonly portfolioDigest: string;
  readonly features: readonly string[];
  readonly resources: readonly PrimeEcosystemResource[];
  readonly registrations: readonly PrimeEcosystemRegistration[];
  readonly projectionRoot: string;
  readonly artifactLockDigest: string;
  readonly moduleLockDigest: string;
  readonly mcpCredentialLeaseId: string;
  readonly limits: PrimeEcosystemLimits;
}

export interface PrimeEcosystemReceipt {
  readonly authorityDigest: string;
  readonly featureIds: readonly string[];
  readonly lifecycleCount: number;
  readonly mcpCount: number;
  readonly modelCredentialReads: number;
  readonly ownedProcessCount: number;
  readonly packageCount: number;
  readonly portfolioDigest: string;
  readonly providerOperations: number;
  readonly registrationCount: number;
  readonly resourceCount: number;
  readonly status: "succeeded" | "failed" | "cancelled" | "uncertain";
}

export interface GatewayEcosystemEffectBinding {
  readonly effectId: string;
  readonly frameDigest: string;
  readonly authorityDigest: string;
  readonly portfolioDigest: string;
  readonly artifactLockDigest: string;
  readonly moduleLockDigest: string;
  readonly featureIds: readonly string[];
  readonly lifecycleCount: number;
  readonly mcpCount: number;
  readonly packageCount: number;
  readonly registrationCount: number;
  readonly resourceCount: number;
}

export interface GatewayEcosystemEffectBindResult {
  readonly binding: GatewayEcosystemEffectBinding;
  readonly disposition: "created" | "preexisting";
}

export interface GatewayEcosystemEffectResult
  extends GatewayEcosystemEffectBinding, PrimeEcosystemReceipt {}

export interface PrimeEcosystemModule {
  activate(frame: PrimeEcosystemFrame): Promise<unknown>;
}

interface PrimeEcosystemStore {
  bindEcosystemEffect(frame: unknown): Promise<GatewayEcosystemEffectBindResult>;
  commitEcosystemEffectResult(
    effectId: string,
    receipt: unknown,
  ): Promise<GatewayEcosystemEffectResult>;
  ecosystemEffectBinding(effectId: string): GatewayEcosystemEffectBinding | undefined;
  ecosystemEffectResult(effectId: string): GatewayEcosystemEffectResult | undefined;
}

export interface PrimeEcosystemAdapterOptions {
  readonly store: PrimeEcosystemStore;
  readonly module: PrimeEcosystemModule;
  readonly lock: PrimeEcosystemLockContract;
}

export interface PrimeEcosystemLockContract {
  readonly artifactLockDigest: string;
  readonly bundleDigest: string;
  readonly moduleLockDigest: string;
}

export const PRIME_ECOSYSTEM_LOCK_CONTRACT: PrimeEcosystemLockContract =
  Object.freeze({
    artifactLockDigest: PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST,
    bundleDigest: PRIME_ECOSYSTEM_BUNDLE_DIGEST,
    moduleLockDigest: PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST,
  });

export class PrimeEcosystemError extends Error {
  constructor(message = "Prime ecosystem operation failed") {
    super(message);
    this.name = "PrimeEcosystemError";
  }
}

function invalidFrame(): never {
  throw new PrimeEcosystemError("Prime ecosystem frame is invalid");
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  const canonical = [...expected].sort();
  return actual.length === canonical.length &&
    actual.every((key, index) => key === canonical[index]);
}

function positiveSafeInteger(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isFinite(value)) {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (isRecord(value)) {
    return `{${Object.keys(value).sort().map((key) =>
      `${JSON.stringify(key)}:${canonicalJson(value[key])}`
    ).join(",")}}`;
  }
  invalidFrame();
}

function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function deepFreeze<T>(value: T): T {
  if ((Array.isArray(value) || isRecord(value)) && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

function compareUnicodeCodePoints(left: string, right: string): number {
  const leftPoints = Array.from(left);
  const rightPoints = Array.from(right);
  const length = Math.min(leftPoints.length, rightPoints.length);
  for (let index = 0; index < length; index += 1) {
    const difference = leftPoints[index]!.codePointAt(0)! -
      rightPoints[index]!.codePointAt(0)!;
    if (difference !== 0) return difference;
  }
  return leftPoints.length - rightPoints.length;
}

function compareTuples(left: readonly string[], right: readonly string[]): number {
  for (let index = 0; index < left.length; index += 1) {
    const leftValue = left[index];
    const rightValue = right[index];
    if (leftValue === undefined || rightValue === undefined) break;
    const difference = compareUnicodeCodePoints(leftValue, rightValue);
    if (difference !== 0) return difference;
  }
  return left.length - right.length;
}

function resourceKey(resource: PrimeEcosystemResource): readonly string[] {
  return [
    resource.kind,
    resource.scope,
    resource.resourceId,
    resource.version,
    resource.source.sourceId,
    resource.source.kind,
    resource.source.version,
    resource.source.contentDigest,
    resource.contentDigest,
  ];
}

function registrationKey(
  registration: PrimeEcosystemRegistration,
): readonly string[] {
  return [
    registration.kind,
    registration.registrationId,
    registration.extensionId,
    registration.version,
  ];
}

function hasPrivateOwnership(metadata: Stats): boolean {
  return typeof process.getuid !== "function" || metadata.uid === process.getuid();
}

function requireDirectory(path: string): void {
  const metadata = lstatSync(path);
  if (
    metadata.isSymbolicLink() ||
    !metadata.isDirectory() ||
    (metadata.mode & 0o7777) !== 0o700 ||
    !hasPrivateOwnership(metadata) ||
    realpathSync(path) !== path
  ) invalidFrame();
}

interface ProjectionFile {
  readonly relative_path: string;
  readonly sha256: string;
  readonly size_bytes: number;
}

function inspectResourceProjection(
  resourceRoot: string,
  maxBytes: number,
  maxEntries: number,
): Readonly<{ files: readonly ProjectionFile[]; bytes: number; entries: number }> {
  const files: ProjectionFile[] = [];
  let bytes = 0;
  let entries = 0;
  const visit = (directory: string, prefix: string): void => {
    for (const name of readdirSync(directory).sort(compareUnicodeCodePoints)) {
      const path = join(directory, name);
      const relativePath = prefix === "" ? name : `${prefix}/${name}`;
      const metadata = lstatSync(path);
      entries += 1;
      if (entries > maxEntries) invalidFrame();
      if (metadata.isSymbolicLink() || !hasPrivateOwnership(metadata)) invalidFrame();
      if (metadata.isDirectory()) {
        if ((metadata.mode & 0o7777) !== 0o700 || realpathSync(path) !== path) {
          invalidFrame();
        }
        visit(path, relativePath);
      } else if (metadata.isFile()) {
        if ((metadata.mode & 0o7777) !== 0o600 || realpathSync(path) !== path) {
          invalidFrame();
        }
        if (!Number.isSafeInteger(metadata.size) || metadata.size > maxBytes - bytes) {
          invalidFrame();
        }
        const body = readFileSync(path);
        if (body.byteLength !== metadata.size) invalidFrame();
        bytes += body.byteLength;
        files.push(Object.freeze({
          relative_path: relativePath,
          sha256: sha256(body),
          size_bytes: body.byteLength,
        }));
      } else {
        invalidFrame();
      }
    }
  };
  visit(resourceRoot, "");
  if (files.length === 0) invalidFrame();
  files.sort((left, right) =>
    compareUnicodeCodePoints(left.relative_path, right.relative_path)
  );
  return Object.freeze({ files: Object.freeze(files), bytes, entries });
}

function validateSource(value: unknown): PrimeEcosystemSource {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["contentDigest", "kind", "sourceId", "version"]) ||
    typeof value.contentDigest !== "string" ||
    !DIGEST.test(value.contentDigest) ||
    typeof value.kind !== "string" ||
    !SOURCE_KINDS.has(value.kind) ||
    typeof value.sourceId !== "string" ||
    !OPAQUE_ID.test(value.sourceId) ||
    typeof value.version !== "string" ||
    !VERSION.test(value.version)
  ) invalidFrame();
  return Object.freeze({
    contentDigest: value.contentDigest,
    kind: value.kind as PrimeEcosystemSource["kind"],
    sourceId: value.sourceId,
    version: value.version,
  });
}

function validateResource(value: unknown): PrimeEcosystemResource {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "contentDigest",
      "kind",
      "projectionPath",
      "resourceId",
      "scope",
      "source",
      "version",
    ]) ||
    typeof value.contentDigest !== "string" ||
    !DIGEST.test(value.contentDigest) ||
    typeof value.kind !== "string" ||
    !RESOURCE_KINDS.has(value.kind) ||
    typeof value.projectionPath !== "string" ||
    typeof value.resourceId !== "string" ||
    !OPAQUE_ID.test(value.resourceId) ||
    typeof value.scope !== "string" ||
    !SCOPES.has(value.scope) ||
    typeof value.version !== "string" ||
    !VERSION.test(value.version)
  ) invalidFrame();
  return Object.freeze({
    contentDigest: value.contentDigest,
    kind: value.kind as PrimeEcosystemResource["kind"],
    projectionPath: value.projectionPath,
    resourceId: value.resourceId,
    scope: value.scope as PrimeEcosystemResource["scope"],
    source: validateSource(value.source),
    version: value.version,
  });
}

function validateRegistration(value: unknown): PrimeEcosystemRegistration {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["extensionId", "kind", "registrationId", "version"]) ||
    typeof value.extensionId !== "string" ||
    !OPAQUE_ID.test(value.extensionId) ||
    typeof value.kind !== "string" ||
    !REGISTRATION_KINDS.has(value.kind) ||
    typeof value.registrationId !== "string" ||
    !OPAQUE_ID.test(value.registrationId) ||
    typeof value.version !== "string" ||
    !VERSION.test(value.version)
  ) invalidFrame();
  return Object.freeze({
    extensionId: value.extensionId,
    kind: value.kind as PrimeEcosystemRegistration["kind"],
    registrationId: value.registrationId,
    version: value.version,
  });
}

function validateLimits(value: unknown): PrimeEcosystemLimits {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["deadlineMs", "maxBytes", "maxEntries", "maxProcesses"]) ||
    !positiveSafeInteger(value.deadlineMs) ||
    value.deadlineMs > MAX_ECOSYSTEM_DEADLINE_MS ||
    !positiveSafeInteger(value.maxBytes) ||
    value.maxBytes > MAX_ECOSYSTEM_BYTES ||
    !positiveSafeInteger(value.maxEntries) ||
    value.maxEntries > MAX_ECOSYSTEM_ENTRIES ||
    !positiveSafeInteger(value.maxProcesses) ||
    value.maxProcesses > MAX_ECOSYSTEM_PROCESSES
  ) invalidFrame();
  return Object.freeze({
    deadlineMs: value.deadlineMs,
    maxBytes: value.maxBytes,
    maxEntries: value.maxEntries,
    maxProcesses: value.maxProcesses,
  });
}

export function validatePrimeEcosystemFrame(value: unknown): PrimeEcosystemFrame {
  try {
    if (
      !isRecord(value) ||
      !hasExactKeys(value, [
        "artifactLockDigest",
        "authorityDigest",
        "effectId",
        "features",
        "format",
        "limits",
        "mcpCredentialLeaseId",
        "moduleLockDigest",
        "portfolioDigest",
        "projectionRoot",
        "registrations",
        "resources",
      ]) ||
      value.format !== PRIME_ECOSYSTEM_FRAME ||
      typeof value.effectId !== "string" ||
      !EFFECT_ID.test(value.effectId) ||
      typeof value.authorityDigest !== "string" ||
      !DIGEST.test(value.authorityDigest) ||
      typeof value.portfolioDigest !== "string" ||
      !DIGEST.test(value.portfolioDigest) ||
      !value.effectId.endsWith(`:${value.portfolioDigest.slice(0, 32)}`) ||
      value.artifactLockDigest !== PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST ||
      value.moduleLockDigest !== PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST ||
      typeof value.mcpCredentialLeaseId !== "string" ||
      !OPAQUE_ID.test(value.mcpCredentialLeaseId) ||
      typeof value.projectionRoot !== "string" ||
      !isAbsolute(value.projectionRoot) ||
      normalize(value.projectionRoot) !== value.projectionRoot ||
      basename(value.projectionRoot) !== value.portfolioDigest ||
      !Array.isArray(value.features) ||
      value.features.some((feature) => typeof feature !== "string" || !OPAQUE_ID.test(feature)) ||
      !Array.isArray(value.resources) ||
      !Array.isArray(value.registrations)
    ) invalidFrame();

    const limits = validateLimits(value.limits);
    const resources = value.resources.map(validateResource);
    const registrations = value.registrations.map(validateRegistration);
    const features = Object.freeze([...(value.features as string[])]);
    if (
      features.join("\0") !== [...new Set(features)]
        .sort(compareUnicodeCodePoints).join("\0") ||
      resources.some((resource, index) =>
        index > 0 && compareTuples(resourceKey(resources[index - 1]!), resourceKey(resource)) >= 0
      ) ||
      registrations.some((registration, index) =>
        index > 0 && compareTuples(
          registrationKey(registrations[index - 1]!),
          registrationKey(registration),
        ) >= 0
      ) ||
      new Set(resources.map(({ resourceId }) => resourceId)).size !== resources.length ||
      new Set(registrations.map(({ registrationId }) => registrationId)).size !== registrations.length
    ) invalidFrame();

    const extensionIds = new Set(
      resources.filter(({ kind }) => kind === "extension").map(({ resourceId }) => resourceId),
    );
    if (registrations.some(({ extensionId }) => !extensionIds.has(extensionId))) {
      invalidFrame();
    }
    const expectedFeatures = [...new Set([
      ...resources.flatMap(({ kind }) => RESOURCE_FEATURES[kind] ?? []),
      ...registrations.map(({ kind }) => REGISTRATION_FEATURES[kind]!),
    ])].sort(compareUnicodeCodePoints);
    if (features.join("\0") !== expectedFeatures.join("\0")) invalidFrame();

    requireDirectory(value.projectionRoot);
    const rootEntries = readdirSync(value.projectionRoot)
      .sort(compareUnicodeCodePoints);
    const expectedRootEntries = resources
      .map(({ resourceId }) => resourceId)
      .sort(compareUnicodeCodePoints);
    if (rootEntries.join("\0") !== expectedRootEntries.join("\0")) invalidFrame();
    let totalBytes = 0;
    let totalEntries = resources.length;
    for (const resource of resources) {
      const expectedPath = join(value.projectionRoot, resource.resourceId);
      if (
        resource.projectionPath !== expectedPath ||
        normalize(resource.projectionPath) !== resource.projectionPath
      ) invalidFrame();
      requireDirectory(resource.projectionPath);
      const inspected = inspectResourceProjection(
        resource.projectionPath,
        limits.maxBytes - totalBytes,
        limits.maxEntries - totalEntries,
      );
      totalBytes += inspected.bytes;
      totalEntries += inspected.entries;
      if (
        sha256(canonicalJson(inspected.files)) !== resource.contentDigest ||
        totalBytes > limits.maxBytes ||
        totalEntries > limits.maxEntries
      ) invalidFrame();
    }

    return deepFreeze({
      artifactLockDigest: value.artifactLockDigest,
      authorityDigest: value.authorityDigest,
      effectId: value.effectId,
      features,
      format: PRIME_ECOSYSTEM_FRAME,
      limits,
      mcpCredentialLeaseId: value.mcpCredentialLeaseId,
      moduleLockDigest: value.moduleLockDigest,
      portfolioDigest: value.portfolioDigest,
      projectionRoot: value.projectionRoot,
      registrations: Object.freeze(registrations),
      resources: Object.freeze(resources),
    });
  } catch (error) {
    if (
      error instanceof PrimeEcosystemError &&
      error.message === "Prime ecosystem frame is invalid"
    ) throw error;
    invalidFrame();
  }
}

export function ecosystemEffectBinding(
  value: unknown,
): GatewayEcosystemEffectBinding {
  const frame = validatePrimeEcosystemFrame(value);
  const publicFrame = {
    artifactLockDigest: frame.artifactLockDigest,
    authorityDigest: frame.authorityDigest,
    effectId: frame.effectId,
    features: frame.features,
    format: frame.format,
    limits: frame.limits,
    moduleLockDigest: frame.moduleLockDigest,
    portfolioDigest: frame.portfolioDigest,
    registrations: frame.registrations,
    resources: frame.resources.map(({ projectionPath: _projectionPath, ...resource }) => resource),
  };
  return Object.freeze({
    effectId: frame.effectId,
    frameDigest: sha256(canonicalJson(publicFrame)),
    authorityDigest: frame.authorityDigest,
    portfolioDigest: frame.portfolioDigest,
    artifactLockDigest: frame.artifactLockDigest,
    moduleLockDigest: frame.moduleLockDigest,
    featureIds: Object.freeze([...frame.features]),
    lifecycleCount: frame.resources.filter(({ kind }) => kind === "extension").length,
    mcpCount: frame.resources.filter(({ kind }) => kind === "mcp-server").length,
    packageCount: frame.resources.filter(({ kind }) => kind === "package").length,
    registrationCount: frame.registrations.length,
    resourceCount: frame.resources.length,
  });
}

export function validateGatewayEcosystemEffectBinding(
  value: unknown,
): GatewayEcosystemEffectBinding {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "artifactLockDigest",
      "authorityDigest",
      "effectId",
      "featureIds",
      "frameDigest",
      "lifecycleCount",
      "mcpCount",
      "moduleLockDigest",
      "packageCount",
      "portfolioDigest",
      "registrationCount",
      "resourceCount",
    ]) ||
    typeof value.effectId !== "string" ||
    !EFFECT_ID.test(value.effectId) ||
    typeof value.frameDigest !== "string" ||
    !DIGEST.test(value.frameDigest) ||
    typeof value.authorityDigest !== "string" ||
    !DIGEST.test(value.authorityDigest) ||
    typeof value.portfolioDigest !== "string" ||
    !DIGEST.test(value.portfolioDigest) ||
    !value.effectId.endsWith(`:${value.portfolioDigest.slice(0, 32)}`) ||
    value.artifactLockDigest !== PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST ||
    value.moduleLockDigest !== PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST ||
    !Array.isArray(value.featureIds) ||
    value.featureIds.some((feature) => typeof feature !== "string" || !OPAQUE_ID.test(feature)) ||
    value.featureIds.join("\0") !== [...new Set(value.featureIds as string[])]
      .sort(compareUnicodeCodePoints).join("\0") ||
    [
      value.lifecycleCount,
      value.mcpCount,
      value.packageCount,
      value.registrationCount,
      value.resourceCount,
    ].some((count) => !Number.isSafeInteger(count) || Number(count) < 0)
  ) throw new PrimeEcosystemError();
  return Object.freeze({
    effectId: value.effectId,
    frameDigest: value.frameDigest,
    authorityDigest: value.authorityDigest,
    portfolioDigest: value.portfolioDigest,
    artifactLockDigest: value.artifactLockDigest,
    moduleLockDigest: value.moduleLockDigest,
    featureIds: Object.freeze([...(value.featureIds as string[])]),
    lifecycleCount: value.lifecycleCount as number,
    mcpCount: value.mcpCount as number,
    packageCount: value.packageCount as number,
    registrationCount: value.registrationCount as number,
    resourceCount: value.resourceCount as number,
  });
}

export function validatePrimeEcosystemReceipt(
  value: unknown,
  frame: PrimeEcosystemFrame,
): PrimeEcosystemReceipt {
  const integerFields = [
    "lifecycleCount",
    "mcpCount",
    "modelCredentialReads",
    "ownedProcessCount",
    "packageCount",
    "providerOperations",
    "registrationCount",
    "resourceCount",
  ] as const;
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "authorityDigest",
      "featureIds",
      "lifecycleCount",
      "mcpCount",
      "modelCredentialReads",
      "ownedProcessCount",
      "packageCount",
      "portfolioDigest",
      "providerOperations",
      "registrationCount",
      "resourceCount",
      "status",
    ]) ||
    value.authorityDigest !== frame.authorityDigest ||
    value.portfolioDigest !== frame.portfolioDigest ||
    !Array.isArray(value.featureIds) ||
    value.featureIds.join("\0") !== frame.features.join("\0") ||
    typeof value.status !== "string" ||
    !TERMINAL_STATUSES.has(value.status) ||
    integerFields.some((field) =>
      !Number.isSafeInteger(value[field]) || Number(value[field]) < 0
    ) ||
    value.resourceCount !== frame.resources.length ||
    value.registrationCount !== frame.registrations.length ||
    value.packageCount !== frame.resources.filter(({ kind }) => kind === "package").length ||
    value.mcpCount !== frame.resources.filter(({ kind }) => kind === "mcp-server").length ||
    value.lifecycleCount !== frame.resources.filter(({ kind }) => kind === "extension").length ||
    value.providerOperations !== 0 ||
    value.modelCredentialReads !== 0 ||
    value.ownedProcessCount !== 0
  ) throw new PrimeEcosystemError();
  return deepFreeze({
    authorityDigest: frame.authorityDigest,
    featureIds: Object.freeze([...frame.features]),
    lifecycleCount: value.lifecycleCount as number,
    mcpCount: value.mcpCount as number,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: value.packageCount as number,
    portfolioDigest: frame.portfolioDigest,
    providerOperations: 0,
    registrationCount: value.registrationCount as number,
    resourceCount: value.resourceCount as number,
    status: value.status as PrimeEcosystemReceipt["status"],
  });
}

export function uncertainPrimeEcosystemReceipt(
  frame: PrimeEcosystemFrame,
): PrimeEcosystemReceipt {
  return deepFreeze({
    authorityDigest: frame.authorityDigest,
    featureIds: Object.freeze([...frame.features]),
    lifecycleCount: frame.resources.filter(({ kind }) => kind === "extension").length,
    mcpCount: frame.resources.filter(({ kind }) => kind === "mcp-server").length,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: frame.resources.filter(({ kind }) => kind === "package").length,
    portfolioDigest: frame.portfolioDigest,
    providerOperations: 0,
    registrationCount: frame.registrations.length,
    resourceCount: frame.resources.length,
    status: "uncertain",
  });
}

export function validatePrimeEcosystemReceiptForBinding(
  value: unknown,
  bindingValue: unknown,
): PrimeEcosystemReceipt {
  const binding = validateGatewayEcosystemEffectBinding(bindingValue);
  const integerFields = [
    "lifecycleCount",
    "mcpCount",
    "modelCredentialReads",
    "ownedProcessCount",
    "packageCount",
    "providerOperations",
    "registrationCount",
    "resourceCount",
  ] as const;
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "authorityDigest",
      "featureIds",
      "lifecycleCount",
      "mcpCount",
      "modelCredentialReads",
      "ownedProcessCount",
      "packageCount",
      "portfolioDigest",
      "providerOperations",
      "registrationCount",
      "resourceCount",
      "status",
    ]) ||
    value.authorityDigest !== binding.authorityDigest ||
    value.portfolioDigest !== binding.portfolioDigest ||
    !Array.isArray(value.featureIds) ||
    value.featureIds.join("\0") !== binding.featureIds.join("\0") ||
    typeof value.status !== "string" ||
    !TERMINAL_STATUSES.has(value.status) ||
    integerFields.some((field) =>
      !Number.isSafeInteger(value[field]) || Number(value[field]) < 0
    ) ||
    value.resourceCount !== binding.resourceCount ||
    value.registrationCount !== binding.registrationCount ||
    value.packageCount !== binding.packageCount ||
    value.mcpCount !== binding.mcpCount ||
    value.lifecycleCount !== binding.lifecycleCount ||
    value.providerOperations !== 0 ||
    value.modelCredentialReads !== 0 ||
    value.ownedProcessCount !== 0
  ) throw new PrimeEcosystemError();
  return deepFreeze({
    authorityDigest: binding.authorityDigest,
    featureIds: Object.freeze([...binding.featureIds]),
    lifecycleCount: binding.lifecycleCount,
    mcpCount: binding.mcpCount,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: binding.packageCount,
    portfolioDigest: binding.portfolioDigest,
    providerOperations: 0,
    registrationCount: binding.registrationCount,
    resourceCount: binding.resourceCount,
    status: value.status as PrimeEcosystemReceipt["status"],
  });
}

export function validateGatewayEcosystemEffectResult(
  value: unknown,
): GatewayEcosystemEffectResult {
  if (!isRecord(value)) throw new PrimeEcosystemError();
  const binding = validateGatewayEcosystemEffectBinding({
    artifactLockDigest: value.artifactLockDigest,
    authorityDigest: value.authorityDigest,
    effectId: value.effectId,
    featureIds: value.featureIds,
    frameDigest: value.frameDigest,
    lifecycleCount: value.lifecycleCount,
    mcpCount: value.mcpCount,
    moduleLockDigest: value.moduleLockDigest,
    packageCount: value.packageCount,
    portfolioDigest: value.portfolioDigest,
    registrationCount: value.registrationCount,
    resourceCount: value.resourceCount,
  });
  if (
    !hasExactKeys(value, [
      "artifactLockDigest",
      "authorityDigest",
      "effectId",
      "featureIds",
      "frameDigest",
      "lifecycleCount",
      "mcpCount",
      "modelCredentialReads",
      "moduleLockDigest",
      "ownedProcessCount",
      "packageCount",
      "portfolioDigest",
      "providerOperations",
      "registrationCount",
      "resourceCount",
      "status",
    ]) ||
    !Array.isArray(value.featureIds) ||
    value.featureIds.some((feature) => typeof feature !== "string" || !OPAQUE_ID.test(feature)) ||
    value.featureIds.join("\0") !== [...new Set(value.featureIds as string[])]
      .sort(compareUnicodeCodePoints).join("\0") ||
    typeof value.status !== "string" ||
    !TERMINAL_STATUSES.has(value.status)
  ) throw new PrimeEcosystemError();
  const counts = [
    value.lifecycleCount,
    value.mcpCount,
    value.modelCredentialReads,
    value.ownedProcessCount,
    value.packageCount,
    value.providerOperations,
    value.registrationCount,
    value.resourceCount,
  ];
  if (
    counts.some((count) => !Number.isSafeInteger(count) || Number(count) < 0) ||
    value.providerOperations !== 0 ||
    value.modelCredentialReads !== 0 ||
    value.ownedProcessCount !== 0 ||
    (value.featureIds as string[]).join("\0") !== binding.featureIds.join("\0") ||
    value.lifecycleCount !== binding.lifecycleCount ||
    value.mcpCount !== binding.mcpCount ||
    value.packageCount !== binding.packageCount ||
    value.registrationCount !== binding.registrationCount ||
    value.resourceCount !== binding.resourceCount
  ) throw new PrimeEcosystemError();
  return deepFreeze({
    ...binding,
    authorityDigest: binding.authorityDigest,
    featureIds: Object.freeze([...(value.featureIds as string[])]),
    lifecycleCount: value.lifecycleCount as number,
    mcpCount: value.mcpCount as number,
    modelCredentialReads: 0,
    ownedProcessCount: 0,
    packageCount: value.packageCount as number,
    portfolioDigest: binding.portfolioDigest,
    providerOperations: 0,
    registrationCount: value.registrationCount as number,
    resourceCount: value.resourceCount as number,
    status: value.status as PrimeEcosystemReceipt["status"],
  });
}

export class PrimeEcosystemAdapter {
  private readonly store: PrimeEcosystemStore;
  private readonly module: PrimeEcosystemModule;

  constructor(options: PrimeEcosystemAdapterOptions) {
    try {
      if (
        !isRecord(options) ||
        typeof options.store?.bindEcosystemEffect !== "function" ||
        typeof options.store?.commitEcosystemEffectResult !== "function" ||
        typeof options.store?.ecosystemEffectBinding !== "function" ||
        typeof options.store?.ecosystemEffectResult !== "function" ||
        typeof options.module?.activate !== "function" ||
        !isRecord(options.lock) ||
        !hasExactKeys(options.lock, [
          "artifactLockDigest",
          "bundleDigest",
          "moduleLockDigest",
        ]) ||
        options.lock.artifactLockDigest !== PRIME_ECOSYSTEM_ARTIFACT_LOCK_DIGEST ||
        options.lock.bundleDigest !== PRIME_ECOSYSTEM_BUNDLE_DIGEST ||
        options.lock.moduleLockDigest !== PRIME_ECOSYSTEM_MODULE_LOCK_DIGEST
      ) throw new TypeError();
      this.store = options.store;
      this.module = options.module;
    } catch {
      throw new PrimeEcosystemError("Prime ecosystem adapter is invalid");
    }
  }

  async activate(value: unknown): Promise<GatewayEcosystemEffectResult> {
    const frame = validatePrimeEcosystemFrame(value);
    const bind = await this.store.bindEcosystemEffect(frame);
    const terminal = this.store.ecosystemEffectResult(frame.effectId);
    if (terminal !== undefined) return terminal;
    if (bind.disposition === "preexisting") {
      return this.store.commitEcosystemEffectResult(
        frame.effectId,
        uncertainPrimeEcosystemReceipt(frame),
      );
    }
    let receipt: PrimeEcosystemReceipt;
    try {
      receipt = validatePrimeEcosystemReceipt(
        await this.module.activate(frame),
        frame,
      );
    } catch {
      receipt = uncertainPrimeEcosystemReceipt(frame);
    }
    return this.store.commitEcosystemEffectResult(frame.effectId, receipt);
  }
}
