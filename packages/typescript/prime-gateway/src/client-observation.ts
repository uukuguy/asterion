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
  constructor() {
    super("Prime client observation failed");
    this.name = "PrimeClientObservationError";
  }
}

export interface PrimeClientObservationMapperOptions {
  readonly sessionId: string;
  readonly generation: number;
  readonly activeSessionId: string;
  readonly privateValues: Pick<PrivateValueStore, "putClientValue">;
  readonly now?: () => string;
}

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MEDIA_TYPE = /^[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*\/[A-Za-z0-9][A-Za-z0-9!#$&^_.+-]*$/u;

function record(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function body(value: unknown): Buffer {
  if (typeof value === "string") return Buffer.from(value, "utf8");
  if (value instanceof Uint8Array) return Buffer.from(value);
  if (record(value) || Array.isArray(value)) return canonicalJsonBytes(value);
  throw new PrimeClientObservationError();
}

export class PrimeClientObservationMapper {
  private sequence = 0;
  private nativeSequence: number | undefined;
  private closed = false;
  private readonly now: () => string;

  constructor(private readonly options: PrimeClientObservationMapperOptions) {
    if (
      !OPAQUE_ID.test(options.sessionId) || !Number.isSafeInteger(options.generation) || options.generation < 1 ||
      !OPAQUE_ID.test(options.activeSessionId) || typeof options.privateValues.putClientValue !== "function"
    ) throw new PrimeClientObservationError();
    this.now = options.now ?? (() => new Date().toISOString());
  }

  async map(value: unknown): Promise<readonly PrimeClientObservation[]> {
    try {
      if (this.closed || !record(value) || typeof value.type !== "string") throw new PrimeClientObservationError();
      if (value.activeSessionId !== this.options.activeSessionId) throw new PrimeClientObservationError();
      this.advance(value.meta);
      if (value.type === "session_event") return this.sessionEvent(value.event);
      if (value.type === "extension_ui_request") return this.extension(value);
      return Object.freeze([]);
    } catch (error) {
      if (error instanceof PrimeClientObservationError) throw error;
      throw new PrimeClientObservationError();
    }
  }

  async close(): Promise<void> { this.closed = true; }

  toString(): string { return "[Prime client observation mapper]"; }

  private advance(meta: unknown): void {
    if (!record(meta) || meta.sequence === undefined) return;
    if (!Number.isSafeInteger(meta.sequence) || Number(meta.sequence) < 1 ||
      (this.nativeSequence !== undefined && Number(meta.sequence) !== this.nativeSequence + 1)) {
      throw new PrimeClientObservationError();
    }
    this.nativeSequence = Number(meta.sequence);
  }

  private async sessionEvent(value: unknown): Promise<readonly PrimeClientObservation[]> {
    if (!record(value) || typeof value.type !== "string") throw new PrimeClientObservationError();
    if (value.type === "message_end") {
      if ((value.role !== "assistant" && value.role !== "user") || typeof value.content !== "string") throw new PrimeClientObservationError();
      const descriptor = await this.store("message", "text/plain", value.content);
      return Object.freeze([this.observation("message.available", {
        content_ref: descriptor.reference, media_type: descriptor.mediaType,
        message_id: typeof value.id === "string" && OPAQUE_ID.test(value.id) ? value.id : `message-${this.sequence + 1}`,
        role: value.role, sha256: descriptor.sha256, size: descriptor.size,
      })]);
    }
    if (value.type === "tool_start") {
      if (typeof value.callId !== "string" || !OPAQUE_ID.test(value.callId) || typeof value.name !== "string" || !OPAQUE_ID.test(value.name)) throw new PrimeClientObservationError();
      const descriptor = await this.store("tool-arguments", "application/json", value.arguments);
      return Object.freeze([this.observation("tool.started", {
        arguments_ref: descriptor.reference, call_id: value.callId, name: value.name,
        sha256: descriptor.sha256, size: descriptor.size,
      })]);
    }
    if (value.type === "tool_end") {
      if (typeof value.callId !== "string" || !OPAQUE_ID.test(value.callId) || typeof value.isError !== "boolean") throw new PrimeClientObservationError();
      const descriptor = await this.store("tool-result", "application/json", value.result);
      return Object.freeze([this.observation("tool.completed", {
        call_id: value.callId, is_error: value.isError, media_type: descriptor.mediaType,
        result_ref: descriptor.reference, sha256: descriptor.sha256, size: descriptor.size,
      })]);
    }
    if (value.type === "artifact_available") {
      if (typeof value.artifactId !== "string" || !OPAQUE_ID.test(value.artifactId) || typeof value.mediaType !== "string" || !MEDIA_TYPE.test(value.mediaType)) throw new PrimeClientObservationError();
      const descriptor = await this.store("artifact", value.mediaType, value.body);
      return Object.freeze([this.observation("artifact.available", {
        artifact_id: value.artifactId, artifact_ref: descriptor.reference, media_type: descriptor.mediaType,
        sha256: descriptor.sha256, size: descriptor.size,
      })]);
    }
    if (value.type === "commands_changed") {
      if (!Array.isArray(value.commands) || !Number.isSafeInteger(value.revision) || Number(value.revision) < 1) throw new PrimeClientObservationError();
      return Object.freeze([this.observation("commands.changed", { commands: Object.freeze([...value.commands]), revision: Number(value.revision) })]);
    }
    return Object.freeze([]);
  }

  private async extension(value: Record<string, unknown>): Promise<readonly PrimeClientObservation[]> {
    if (typeof value.id !== "string" || !OPAQUE_ID.test(value.id) || typeof value.method !== "string" || !OPAQUE_ID.test(value.method)) throw new PrimeClientObservationError();
    const descriptor = await this.store("extension-ui", "application/json", value.payload);
    return Object.freeze([this.observation("extension-ui.requested", {
      deadline_ms: 9_007_199_254_740_991, method: value.method, payload_ref: descriptor.reference, request_id: value.id,
    })]);
  }

  private async store(kind: string, mediaType: string, value: unknown): Promise<PrivateClientValueDescriptor> {
    return this.options.privateValues.putClientValue(this.options.sessionId, kind, mediaType, body(value));
  }

  private observation(kind: PrimeClientObservationKind, payload: Record<string, unknown>): PrimeClientObservation {
    const emittedAt = this.now();
    if (typeof emittedAt !== "string" || Number.isNaN(Date.parse(emittedAt))) throw new PrimeClientObservationError();
    this.sequence += 1;
    return Object.freeze({
      observation_id: `prime-client-${this.options.generation}-${this.sequence}`,
      active_session_id: this.options.sessionId,
      generation: this.options.generation,
      source_sequence: this.sequence,
      emitted_at: emittedAt,
      kind,
      payload: Object.freeze({ ...payload }),
    });
  }
}
