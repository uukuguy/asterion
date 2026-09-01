import { createHash } from "node:crypto";

import { canonicalJsonBytes } from "./durable-store.js";
import type { PrivateClientValueDescriptor, PrivateValueStore } from "./private-store.js";

export type PrimeClientObservationKind =
  | "artifact.available" | "commands.changed" | "extension-ui.requested"
  | "message.available" | "tool.completed" | "tool.started";

export interface PrimeClientObservation {
  readonly observation_id: string;
  readonly active_session_id: string;
  readonly generation: number;
  readonly source_sequence: number;
  readonly emitted_at: string;
  readonly kind: PrimeClientObservationKind;
  readonly payload: Readonly<Record<string, unknown>>;
}

export interface PrimeClientObservationHealth {
  readonly status: "healthy" | "degraded" | "resync-required";
  readonly reason_code: "native-sequence-gap" | null;
  readonly observed_through_native_sequence: number;
  readonly first_missing_native_sequence: number | null;
  readonly resync_required: boolean;
}

export class PrimeClientObservationError extends Error {
  constructor(
    readonly kind: "session-mismatch" | "sequence" | "invalid" = "invalid",
  ) { super("Prime client observation failed"); this.name = "PrimeClientObservationError"; }
}

export interface PrimeClientObservationMapperOptions {
  readonly sessionId: string;
  readonly generation: number;
  readonly activeSessionId: string;
  readonly privateValues: Pick<PrivateValueStore, "putClientValue" | "deleteClientValue">;
  readonly initialNativeSequence?: number;
  readonly initialObservationSequence?: number;
  readonly commit?: (
    nativeSequence: number,
    observation: PrimeClientObservation | null,
    stage?: Readonly<{ generation: number; nativeSequence: number; reference: string; kind: string; mediaType: string; size: number; sha256: string }> | null,
  ) => Promise<void>;
  readonly stage?: (value: Readonly<{
    generation: number;
    nativeSequence: number;
    reference: string;
    kind: string;
    mediaType: string;
    size: number;
    sha256: string;
  }>) => Promise<void>;
  readonly now?: () => string;
}

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const IDENTIFIER = /^[a-z][a-z0-9]*(?:[.-][a-z0-9]+)*$/u;
const PRIVATE_REF = /^private:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const MEDIA_TYPE = /^[a-z0-9][a-z0-9!#$&^_.+-]*\/[a-z0-9][a-z0-9!#$&^_.+-]*$/u;
const SHA256 = /^[0-9a-f]{64}$/u;
export const MAX_CLIENT_VALUE_BYTES = 700 * 1024;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function body(value: unknown): Buffer {
  if (typeof value === "string") return Buffer.from(value, "utf8");
  if (value instanceof Uint8Array) return Buffer.from(value);
  if (record(value) || Array.isArray(value)) return canonicalJsonBytes(value);
  throw new PrimeClientObservationError();
}

function exactDescriptor(value: unknown, kind: string, mediaType: string, bytes: Buffer): PrivateClientValueDescriptor {
  if (!record(value) ||
    typeof value.reference !== "string" || !PRIVATE_REF.test(value.reference) || value.kind !== kind || value.mediaType !== mediaType ||
    !Number.isSafeInteger(value.size) || Number(value.size) !== bytes.byteLength || typeof value.sha256 !== "string" || !SHA256.test(value.sha256) ||
    String(value.sha256) !== createHash("sha256").update(bytes).digest("hex")) throw new PrimeClientObservationError();
  return Object.freeze({ reference: value.reference as `private:${string}`, kind, mediaType, size: Number(value.size), sha256: value.sha256 });
}

interface Prepared {
  readonly nativeSequence: number;
  readonly kind: PrimeClientObservationKind;
  readonly payload: Readonly<Record<string, unknown>>;
}

export class PrimeClientObservationMapper {
  private sequence: number;
  private nativeSequence: number;
  private closed = false;
  private serial: Promise<void> = Promise.resolve();
  private readonly now: () => string;
  private healthValue: PrimeClientObservationHealth;

  constructor(private readonly options: PrimeClientObservationMapperOptions) {
    if (!OPAQUE_ID.test(options.sessionId) || !Number.isSafeInteger(options.generation) || options.generation < 1 ||
      !OPAQUE_ID.test(options.activeSessionId) || typeof options.privateValues.putClientValue !== "function" ||
      !Number.isSafeInteger(options.initialNativeSequence ?? 0) || Number(options.initialNativeSequence ?? 0) < 0 ||
      !Number.isSafeInteger(options.initialObservationSequence ?? 0) || Number(options.initialObservationSequence ?? 0) < 0 ||
      (options.commit !== undefined && typeof options.commit !== "function") ||
      (options.stage !== undefined && typeof options.stage !== "function")) throw new PrimeClientObservationError();
    this.now = options.now ?? (() => new Date().toISOString());
    this.nativeSequence = options.initialNativeSequence ?? 0;
    this.sequence = options.initialObservationSequence ?? 0;
    this.healthValue = Object.freeze({
      status: "healthy",
      reason_code: null,
      observed_through_native_sequence: this.nativeSequence,
      first_missing_native_sequence: null,
      resync_required: false,
    });
  }

  async map(value: unknown): Promise<readonly PrimeClientObservation[]> {
    const work = this.serial.then(() => this.mapOne(value)).catch((error: unknown) => {
      if (error instanceof PrimeClientObservationError && error.kind === "sequence") {
        this.healthValue = Object.freeze({
          status: "degraded",
          reason_code: "native-sequence-gap",
          observed_through_native_sequence: this.nativeSequence,
          first_missing_native_sequence: this.nativeSequence + 1,
          resync_required: false,
        });
      }
      throw error;
    });
    this.serial = work.then(() => undefined, () => undefined);
    return work;
  }
  async close(): Promise<void> { this.closed = true; await this.serial; }
  get health(): PrimeClientObservationHealth { return this.healthValue; }
  toString(): string { return "[Prime client observation mapper]"; }

  private async mapOne(value: unknown): Promise<readonly PrimeClientObservation[]> {
    const written: PrivateClientValueDescriptor[] = [];
    try {
      if (this.closed || !record(value) || typeof value.type !== "string") throw new PrimeClientObservationError();
      if (value.type !== "session_event" && value.type !== "extension_ui_request") return Object.freeze([]);
      if (value.activeSessionId !== this.options.activeSessionId) {
        return Object.freeze([]);
      }
      const nativeSequence = this.nextNativeSequence(value.meta);
      if (nativeSequence === undefined) return Object.freeze([]);
      const prepared = value.type === "session_event" ? await this.prepareSessionEvent(value.event, nativeSequence, written)
        : value.type === "extension_ui_request" ? await this.prepareExtension(value, nativeSequence, written) : undefined;
      if (prepared === undefined) {
        await this.options.commit?.(nativeSequence, null);
        this.nativeSequence = nativeSequence;
        this.markHealthyThrough(nativeSequence);
        return Object.freeze([]);
      }
      const emittedAtValue = this.now();
      if (typeof emittedAtValue !== "string" || Number.isNaN(Date.parse(emittedAtValue))) throw new PrimeClientObservationError();
      const emittedAt = new Date(emittedAtValue).toISOString();
      const next = this.sequence + 1;
      const observation = Object.freeze({ observation_id: `prime-client-${this.options.generation}-${next}`, active_session_id: this.options.sessionId,
        generation: this.options.generation, source_sequence: next, emitted_at: emittedAt, kind: prepared.kind, payload: Object.freeze({ ...prepared.payload }) });
      const descriptor = written.at(-1);
      await this.options.commit?.(prepared.nativeSequence, observation, descriptor === undefined ? null : Object.freeze({
        generation: this.options.generation, nativeSequence: prepared.nativeSequence,
        reference: descriptor.reference, kind: descriptor.kind, mediaType: descriptor.mediaType,
        size: descriptor.size, sha256: descriptor.sha256,
      }));
      this.nativeSequence = prepared.nativeSequence;
      this.sequence = next;
      this.markHealthyThrough(prepared.nativeSequence);
      return Object.freeze([observation]);
    } catch (error) {
      try {
        for (const descriptor of written) {
          await this.options.privateValues.deleteClientValue(
            descriptor.reference,
            this.options.sessionId,
          );
        }
      } catch { throw new PrimeClientObservationError(); }
      if (error instanceof PrimeClientObservationError) throw error;
      throw new PrimeClientObservationError();
    }
  }

  private nextNativeSequence(meta: unknown): number | undefined {
    if (!record(meta) || !Number.isSafeInteger(meta.sequence) || Number(meta.sequence) < 1) {
      throw new PrimeClientObservationError("sequence");
    }
    const received = Number(meta.sequence);
    if (this.nativeSequence !== 0 && received === this.nativeSequence) {
      return undefined;
    }
    if (this.nativeSequence !== 0 && received < this.nativeSequence) {
      throw new PrimeClientObservationError("sequence");
    }
    return received;
  }

  private markHealthyThrough(nativeSequence: number): void {
    if (this.healthValue.status !== "healthy") return;
    this.healthValue = Object.freeze({
      status: "healthy", reason_code: null,
      observed_through_native_sequence: nativeSequence,
      first_missing_native_sequence: null, resync_required: false,
    });
  }

  private async prepareSessionEvent(value: unknown, nativeSequence: number, written: PrivateClientValueDescriptor[]): Promise<Prepared | undefined> {
    if (!record(value) || typeof value.type !== "string") throw new PrimeClientObservationError();
    if (value.type === "message_end") {
      const message = value.message;
      if (!record(message) || (message.role !== "assistant" && message.role !== "user") || !("content" in message)) throw new PrimeClientObservationError();
      const d = await this.store("message", "application/json", message.content, nativeSequence, written);
      return { nativeSequence, kind: "message.available", payload: { content_ref: d.reference, media_type: d.mediaType, message_id: typeof message.id === "string" && OPAQUE_ID.test(message.id) ? message.id : `message-${this.sequence + 1}`, role: message.role, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "tool_execution_start") {
      if (typeof value.toolCallId !== "string" || !OPAQUE_ID.test(value.toolCallId) || typeof value.toolName !== "string" || !IDENTIFIER.test(value.toolName)) throw new PrimeClientObservationError();
      const d = await this.store("tool-arguments", "application/json", value.args, nativeSequence, written);
      return { nativeSequence, kind: "tool.started", payload: { arguments_ref: d.reference, call_id: value.toolCallId, name: value.toolName, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "tool_execution_end") {
      if (typeof value.toolCallId !== "string" || !OPAQUE_ID.test(value.toolCallId) || typeof value.toolName !== "string" || !IDENTIFIER.test(value.toolName) || typeof value.isError !== "boolean") throw new PrimeClientObservationError();
      const d = await this.store("tool-result", "application/json", value.result, nativeSequence, written);
      return { nativeSequence, kind: "tool.completed", payload: { call_id: value.toolCallId, is_error: value.isError, media_type: d.mediaType, result_ref: d.reference, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "artifact_available") {
      if (typeof value.artifactId !== "string" || !OPAQUE_ID.test(value.artifactId) || typeof value.mediaType !== "string" || !MEDIA_TYPE.test(value.mediaType)) throw new PrimeClientObservationError();
      const d = await this.store("artifact", value.mediaType, value.body, nativeSequence, written);
      return { nativeSequence, kind: "artifact.available", payload: { artifact_id: value.artifactId, artifact_ref: d.reference, media_type: d.mediaType, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "commands_changed") {
      const commands = value.commands;
      if (!Array.isArray(commands) || !commands.every((item) => typeof item === "string" && IDENTIFIER.test(item)) ||
        !commands.every((item, index) => index === 0 || String(commands[index - 1]) < item) ||
        !Number.isSafeInteger(value.revision) || Number(value.revision) < 1) throw new PrimeClientObservationError();
      return { nativeSequence, kind: "commands.changed", payload: { commands: Object.freeze([...commands] as string[]), revision: Number(value.revision) } };
    }
    return undefined;
  }

  private async prepareExtension(value: Record<string, unknown>, nativeSequence: number, written: PrivateClientValueDescriptor[]): Promise<Prepared> {
    if (typeof value.id !== "string" || !OPAQUE_ID.test(value.id) || typeof value.method !== "string" || !IDENTIFIER.test(value.method)) throw new PrimeClientObservationError();
    const d = await this.store("extension-ui", "application/json", value.payload, nativeSequence, written);
    return { nativeSequence, kind: "extension-ui.requested", payload: { deadline_ms: 9_007_199_254_740_991, method: value.method, payload_ref: d.reference, request_id: value.id } };
  }

  private async store(kind: string, mediaType: string, value: unknown, nativeSequence: number, written: PrivateClientValueDescriptor[]): Promise<PrivateClientValueDescriptor> {
    const bytes = body(value);
    if (bytes.byteLength > MAX_CLIENT_VALUE_BYTES) throw new PrimeClientObservationError();
    const sha256 = createHash("sha256").update(bytes).digest("hex");
    const identity = createHash("sha256").update(
      `${this.options.sessionId}:${this.options.generation}:${nativeSequence}:${kind}:${mediaType}:${bytes.byteLength}:${sha256}`,
    ).digest("hex");
    const reference = `private:${identity.slice(0, 8)}-${identity.slice(8, 12)}-${identity.slice(12, 16)}-${identity.slice(16, 20)}-${identity.slice(20, 32)}` as const;
    await this.options.stage?.(Object.freeze({ generation: this.options.generation, nativeSequence, reference, kind, mediaType, size: bytes.byteLength, sha256 }));
    const descriptor = exactDescriptor(await this.options.privateValues.putClientValue(this.options.sessionId, kind, mediaType, bytes, reference), kind, mediaType, bytes);
    if (descriptor.reference !== reference) throw new PrimeClientObservationError();
    written.push(descriptor);
    return descriptor;
  }
}
