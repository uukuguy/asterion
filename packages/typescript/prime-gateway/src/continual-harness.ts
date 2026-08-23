import { createHash } from "node:crypto";

const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const DIGEST = /^[0-9a-f]{64}$/u;
const BASE_PROMPTS = new Set(["base-prompt", "base-system-prompt", "system-prompt"]);

export type PrimeHarnessScope = Readonly<{
  primeScope: "local" | "global";
  scopeDigest: string;
  projectionRootRef: string;
}>;

export type PrimeHarnessEdit = Readonly<{
  action: "create" | "update" | "delete";
  entryId: string;
  expectedVersion: number | null;
  kind: "prompt" | "memory" | "skill" | "subagent" | null;
  titleDigest: string | null;
  bodyDigest: string | null;
  groupingPathDigest: string | null;
  metadataDigest: string | null;
  version: number | null;
  bodyText: string | null;
  pythonReference: string | null;
  pythonArguments: readonly string[];
}>;

export type PrimeHarnessEffect = Readonly<{
  effectId: string;
  proposalDigest: string;
  scope: PrimeHarnessScope;
  edits: readonly PrimeHarnessEdit[];
}>;

export interface GatewayHarnessEffectBinding {
  readonly effectId: string;
  readonly proposalDigest: string;
  readonly scopeDigest: string;
  readonly effectDigest: string;
}

export interface GatewayHarnessEffectResult extends GatewayHarnessEffectBinding {
  readonly status: "succeeded" | "failed" | "uncertain";
  readonly snapshotDigest: string | null;
}

export interface PrimeHarnessModule {
  loadHarnessState(root: string, scope: "local" | "global"): unknown;
  applyRefinementProposal(
    state: unknown,
    proposal: unknown,
    options: Readonly<{ id: string; scope: "local" | "global" }>,
  ): unknown;
  saveHarnessState(root: string, state: unknown): string;
}

interface PrimeHarnessStore {
  bindHarnessEffect(effect: unknown): Promise<GatewayHarnessEffectBinding>;
  commitHarnessEffectResult(
    effectId: string,
    status: GatewayHarnessEffectResult["status"],
    snapshotDigest: string | null,
  ): Promise<GatewayHarnessEffectResult>;
  harnessEffectBinding(effectId: string): GatewayHarnessEffectBinding | undefined;
  harnessEffectResult(effectId: string): GatewayHarnessEffectResult | undefined;
}

export interface PrimeContinualHarnessAdapterOptions {
  readonly store: PrimeHarnessStore;
  readonly module: PrimeHarnessModule;
}

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function exact(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return Object.keys(value).sort().join("\0") === [...keys].sort().join("\0");
}

function canonical(value: unknown): string {
  if (value === null || typeof value === "string" || typeof value === "boolean") {
    return JSON.stringify(value);
  }
  if (typeof value === "number" && Number.isFinite(value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (record(value)) {
    return `{${Object.keys(value).sort().map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`).join(",")}}`;
  }
  throw new Error("Prime harness effect is invalid");
}

function positive(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) > 0;
}

function nullableDigest(value: unknown): value is string | null {
  return value === null || (typeof value === "string" && DIGEST.test(value));
}

export function validatePrimeHarnessEffect(value: unknown): PrimeHarnessEffect {
  if (!record(value) || !exact(value, ["edits", "effectId", "proposalDigest", "scope"]) ||
      typeof value.effectId !== "string" || !ID.test(value.effectId) ||
      typeof value.proposalDigest !== "string" || !DIGEST.test(value.proposalDigest) ||
      !record(value.scope) || !exact(value.scope, ["primeScope", "projectionRootRef", "scopeDigest"]) ||
      (value.scope.primeScope !== "local" && value.scope.primeScope !== "global") ||
      typeof value.scope.scopeDigest !== "string" || !DIGEST.test(value.scope.scopeDigest) ||
      typeof value.scope.projectionRootRef !== "string" || !ID.test(value.scope.projectionRootRef) ||
      !Array.isArray(value.edits) || value.edits.length === 0) {
    throw new Error("Prime harness effect is invalid");
  }
  const edits = value.edits.map((raw): PrimeHarnessEdit => {
    const keys = ["action", "bodyDigest", "bodyText", "entryId", "expectedVersion", "groupingPathDigest", "kind", "metadataDigest", "pythonArguments", "pythonReference", "titleDigest", "version"];
    if (!record(raw) || !exact(raw, keys) || typeof raw.entryId !== "string" || !ID.test(raw.entryId) ||
        !["create", "update", "delete"].includes(String(raw.action)) || !Array.isArray(raw.pythonArguments) ||
        raw.pythonArguments.some((item) => typeof item !== "string")) {
      throw new Error("Prime harness effect is invalid");
    }
    if (raw.action === "delete") {
      if (!positive(raw.expectedVersion) || [raw.kind, raw.titleDigest, raw.bodyDigest, raw.groupingPathDigest, raw.metadataDigest, raw.version, raw.bodyText, raw.pythonReference].some((item) => item !== null) || raw.pythonArguments.length !== 0) throw new Error("Prime harness effect is invalid");
    } else {
      const expectedOk = raw.action === "create" ? raw.expectedVersion === null : positive(raw.expectedVersion);
      if (!expectedOk || !["prompt", "memory", "skill", "subagent"].includes(String(raw.kind)) ||
          typeof raw.titleDigest !== "string" || !DIGEST.test(raw.titleDigest) ||
          typeof raw.bodyDigest !== "string" || !DIGEST.test(raw.bodyDigest) || !nullableDigest(raw.groupingPathDigest) ||
          typeof raw.metadataDigest !== "string" || !DIGEST.test(raw.metadataDigest) || !positive(raw.version) ||
          typeof raw.bodyText !== "string" || Buffer.byteLength(raw.bodyText, "utf8") > 1024 * 1024 ||
          (raw.kind === "prompt" && BASE_PROMPTS.has(raw.entryId)) ||
          (raw.kind === "skill" && (typeof raw.pythonReference !== "string" || !ID.test(raw.pythonReference))) ||
          (raw.kind !== "skill" && (raw.pythonReference !== null || raw.pythonArguments.length !== 0))) throw new Error("Prime harness effect is invalid");
    }
    return Object.freeze(raw as unknown as PrimeHarnessEdit);
  });
  const ids = edits.map((item) => item.entryId);
  if (ids.join("\0") !== [...new Set(ids)].sort().join("\0")) throw new Error("Prime harness effect is invalid");
  return Object.freeze({
    effectId: value.effectId,
    proposalDigest: value.proposalDigest,
    scope: Object.freeze(value.scope as unknown as PrimeHarnessScope),
    edits: Object.freeze(edits),
  });
}

export function harnessEffectBinding(value: unknown): GatewayHarnessEffectBinding {
  const effect = validatePrimeHarnessEffect(value);
  const publicEffect = {
    effectId: effect.effectId,
    proposalDigest: effect.proposalDigest,
    scopeDigest: effect.scope.scopeDigest,
    edits: effect.edits.map(({ bodyText: _bodyText, ...edit }) => edit),
  };
  return Object.freeze({
    effectId: effect.effectId,
    proposalDigest: effect.proposalDigest,
    scopeDigest: effect.scope.scopeDigest,
    effectDigest: createHash("sha256").update(canonical(publicEffect)).digest("hex"),
  });
}

export class PrimeContinualHarnessAdapter {
  readonly store: PrimeHarnessStore;
  readonly module: PrimeHarnessModule;

  constructor(options: PrimeContinualHarnessAdapterOptions) {
    if (!record(options) || typeof options.store?.bindHarnessEffect !== "function" ||
        typeof options.module?.loadHarnessState !== "function" || typeof options.module?.applyRefinementProposal !== "function" ||
        typeof options.module?.saveHarnessState !== "function") throw new Error("Prime harness adapter is invalid");
    this.store = options.store;
    this.module = options.module;
  }

  async apply(value: unknown): Promise<GatewayHarnessEffectResult> {
    let effect: PrimeHarnessEffect;
    try {
      effect = validatePrimeHarnessEffect(value);
    } catch {
      await this.store.bindHarnessEffect(value);
      throw new Error("Prime harness effect is invalid");
    }
    const existing = this.store.harnessEffectBinding(effect.effectId);
    const binding = await this.store.bindHarnessEffect(effect);
    const terminal = this.store.harnessEffectResult(effect.effectId);
    if (terminal !== undefined) return terminal;
    if (existing !== undefined) return this.store.commitHarnessEffectResult(effect.effectId, "uncertain", null);
    try {
      const state = this.module.loadHarnessState(effect.scope.projectionRootRef, effect.scope.primeScope);
      const next = this.module.applyRefinementProposal(state, { edits: effect.edits }, { id: effect.effectId, scope: effect.scope.primeScope });
      const snapshotDigest = this.module.saveHarnessState(effect.scope.projectionRootRef, next);
      if (!DIGEST.test(snapshotDigest) || binding.effectDigest !== harnessEffectBinding(effect).effectDigest) throw new Error("invalid result");
      return this.store.commitHarnessEffectResult(effect.effectId, "succeeded", snapshotDigest);
    } catch {
      return this.store.commitHarnessEffectResult(effect.effectId, "uncertain", null);
    }
  }
}
