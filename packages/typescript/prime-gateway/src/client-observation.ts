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

export class PrimeClientObservationError extends Error {
  constructor() { super("Prime client observation failed"); this.name = "PrimeClientObservationError"; }
}

export interface PrimeClientObservationMapperOptions {
  readonly sessionId: string;
  readonly generation: number;
  readonly activeSessionId: string;
  readonly privateValues: Pick<PrivateValueStore, "putClientValue">;
  readonly initialNativeSequence?: number;
  readonly initialObservationSequence?: number;
  readonly commit?: (
    nativeSequence: number,
    observation: PrimeClientObservation | null,
  ) => Promise<void>;
  readonly now?: () => string;
}

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const PRIVATE_REF = /^private:[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/u;
const MEDIA_TYPE = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;
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

  constructor(private readonly options: PrimeClientObservationMapperOptions) {
    if (!OPAQUE_ID.test(options.sessionId) || !Number.isSafeInteger(options.generation) || options.generation < 1 ||
      !OPAQUE_ID.test(options.activeSessionId) || typeof options.privateValues.putClientValue !== "function" ||
      !Number.isSafeInteger(options.initialNativeSequence ?? 0) || Number(options.initialNativeSequence ?? 0) < 0 ||
      !Number.isSafeInteger(options.initialObservationSequence ?? 0) || Number(options.initialObservationSequence ?? 0) < 0 ||
      (options.commit !== undefined && typeof options.commit !== "function")) throw new PrimeClientObservationError();
    this.now = options.now ?? (() => new Date().toISOString());
    this.nativeSequence = options.initialNativeSequence ?? 0;
    this.sequence = options.initialObservationSequence ?? 0;
  }

  async map(value: unknown): Promise<readonly PrimeClientObservation[]> {
    const work = this.serial.then(() => this.mapOne(value));
    this.serial = work.then(() => undefined, () => undefined);
    return work;
  }
  async close(): Promise<void> { this.closed = true; await this.serial; }
  toString(): string { return "[Prime client observation mapper]"; }

  private async mapOne(value: unknown): Promise<readonly PrimeClientObservation[]> {
    try {
      if (this.closed || !record(value) || typeof value.type !== "string" || value.activeSessionId !== this.options.activeSessionId) throw new PrimeClientObservationError();
      const nativeSequence = this.nextNativeSequence(value.meta);
      const prepared = value.type === "session_event" ? await this.prepareSessionEvent(value.event, nativeSequence)
        : value.type === "extension_ui_request" ? await this.prepareExtension(value, nativeSequence) : undefined;
      if (prepared === undefined) {
        await this.options.commit?.(nativeSequence, null);
        this.nativeSequence = nativeSequence;
        return Object.freeze([]);
      }
      const emittedAtValue = this.now();
      if (typeof emittedAtValue !== "string" || Number.isNaN(Date.parse(emittedAtValue))) throw new PrimeClientObservationError();
      const emittedAt = new Date(emittedAtValue).toISOString();
      const next = this.sequence + 1;
      const observation = Object.freeze({ observation_id: `prime-client-${this.options.generation}-${next}`, active_session_id: this.options.sessionId,
        generation: this.options.generation, source_sequence: next, emitted_at: emittedAt, kind: prepared.kind, payload: Object.freeze({ ...prepared.payload }) });
      await this.options.commit?.(prepared.nativeSequence, observation);
      this.nativeSequence = prepared.nativeSequence;
      this.sequence = next;
      return Object.freeze([observation]);
    } catch (error) { if (error instanceof PrimeClientObservationError) throw error; throw new PrimeClientObservationError(); }
  }

  private nextNativeSequence(meta: unknown): number {
    if (!record(meta) || !Number.isSafeInteger(meta.sequence) || Number(meta.sequence) < 1 || Number(meta.sequence) !== this.nativeSequence + 1) throw new PrimeClientObservationError();
    return Number(meta.sequence);
  }

  private async prepareSessionEvent(value: unknown, nativeSequence: number): Promise<Prepared | undefined> {
    if (!record(value) || typeof value.type !== "string") throw new PrimeClientObservationError();
    if (value.type === "message_end") {
      if ((value.role !== "assistant" && value.role !== "user") || typeof value.content !== "string") throw new PrimeClientObservationError();
      const d = await this.store("message", "text/plain", value.content);
      return { nativeSequence, kind: "message.available", payload: { content_ref: d.reference, media_type: d.mediaType, message_id: typeof value.id === "string" && OPAQUE_ID.test(value.id) ? value.id : `message-${this.sequence + 1}`, role: value.role, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "tool_start") {
      if (typeof value.callId !== "string" || !OPAQUE_ID.test(value.callId) || typeof value.name !== "string" || !OPAQUE_ID.test(value.name)) throw new PrimeClientObservationError();
      const d = await this.store("tool-arguments", "application/json", value.arguments);
      return { nativeSequence, kind: "tool.started", payload: { arguments_ref: d.reference, call_id: value.callId, name: value.name, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "tool_end") {
      if (typeof value.callId !== "string" || !OPAQUE_ID.test(value.callId) || typeof value.isError !== "boolean") throw new PrimeClientObservationError();
      const d = await this.store("tool-result", "application/json", value.result);
      return { nativeSequence, kind: "tool.completed", payload: { call_id: value.callId, is_error: value.isError, media_type: d.mediaType, result_ref: d.reference, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "artifact_available") {
      if (typeof value.artifactId !== "string" || !OPAQUE_ID.test(value.artifactId) || typeof value.mediaType !== "string" || !MEDIA_TYPE.test(value.mediaType)) throw new PrimeClientObservationError();
      const d = await this.store("artifact", value.mediaType, value.body);
      return { nativeSequence, kind: "artifact.available", payload: { artifact_id: value.artifactId, artifact_ref: d.reference, media_type: d.mediaType, sha256: d.sha256, size: d.size } };
    }
    if (value.type === "commands_changed") {
      if (!Array.isArray(value.commands) || !Number.isSafeInteger(value.revision) || Number(value.revision) < 1) throw new PrimeClientObservationError();
      return { nativeSequence, kind: "commands.changed", payload: { commands: Object.freeze([...value.commands]), revision: Number(value.revision) } };
    }
    return undefined;
  }

  private async prepareExtension(value: Record<string, unknown>, nativeSequence: number): Promise<Prepared> {
    if (typeof value.id !== "string" || !OPAQUE_ID.test(value.id) || typeof value.method !== "string" || !OPAQUE_ID.test(value.method)) throw new PrimeClientObservationError();
    const d = await this.store("extension-ui", "application/json", value.payload);
    return { nativeSequence, kind: "extension-ui.requested", payload: { deadline_ms: 9_007_199_254_740_991, method: value.method, payload_ref: d.reference, request_id: value.id } };
  }

  private async store(kind: string, mediaType: string, value: unknown): Promise<PrivateClientValueDescriptor> {
    const bytes = body(value);
    if (bytes.byteLength > MAX_CLIENT_VALUE_BYTES) throw new PrimeClientObservationError();
    return exactDescriptor(await this.options.privateValues.putClientValue(this.options.sessionId, kind, mediaType, bytes), kind, mediaType, bytes);
  }
}
