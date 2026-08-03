import { Buffer } from "node:buffer";
import { createHash } from "node:crypto";
import { writeSync } from "node:fs";

export const CAPTURE_CONTRACT_VERSION = "dci.pathlight-provider-request-capture/v1";
export const PRIVATE_RECORD_SCHEMA = "dci.private-provider-request/v1";
export const SAFE_OBSERVATION_SCHEMA = "dci.provider-request-observation/v1";

const runtimeProcess = (globalThis as unknown as {
  process: { env: Record<string, string | undefined> };
}).process;
const privateFdValue = runtimeProcess.env.ASTERION_DCI_PATHLIGHT_PRIVATE_FD;
const captureContractValue = runtimeProcess.env.ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT;
delete runtimeProcess.env.ASTERION_DCI_PATHLIGHT_PRIVATE_FD;
delete runtimeProcess.env.ASTERION_DCI_PATHLIGHT_CAPTURE_CONTRACT;

const MAX_PRIVATE_RECORD_BYTES = 64 * 1024 * 1024;
const MAX_NATIVE_GENERATION_BYTES = 512 * 1024 * 1024;
const FIXED_ERROR = "provider request observation unavailable";

type SegmentRole = "system" | "user" | "assistant" | "tool-result" | "unknown";
type StructureKind = "message" | "tool-result" | "contract" | "missing";

export interface SafeSegmentSummary {
  readonly segment_index: number;
  readonly role: SegmentRole;
  readonly structure_kind: StructureKind;
  readonly content_sha256: string | null;
  readonly content_length: number | null;
  readonly source_call_sha256: string | null;
  readonly missing_evidence: boolean;
  readonly segment_sha256: string;
}

export interface SafeObservation {
  readonly payload_sha256: string;
  readonly payload_bytes: number;
  readonly shape_sha256: string;
  readonly field_count: number;
  readonly leaf_count: number;
  readonly text_characters: number;
  readonly segments: readonly SafeSegmentSummary[];
  readonly missing_evidence: readonly string[];
  readonly summary_sha256: string;
}

interface ExtensionApi {
  on(name: "before_provider_request", handler: (event: unknown, context: unknown) => undefined): void;
  appendEntry(customType: "dci-provider-request-observation", data: unknown): void;
}

interface ShapeSummary {
  readonly projection: unknown;
  readonly fieldCount: number;
  readonly leafCount: number;
  readonly textCharacters: number;
}

interface SummarizedPayload {
  readonly payloadJson: string;
  readonly observation: SafeObservation;
}

type Write = (
  fd: number,
  value: Uint8Array,
  offset: number,
  length: number,
) => number;

function fail(): never {
  throw new Error(FIXED_ERROR);
}

function sha256(value: string | Uint8Array): string {
  return createHash("sha256").update(value).digest("hex");
}

function unicodeScalarCompare(left: string, right: string): number {
  const leftScalars = Array.from(left, (value) => value.codePointAt(0) ?? 0);
  const rightScalars = Array.from(right, (value) => value.codePointAt(0) ?? 0);
  const length = Math.min(leftScalars.length, rightScalars.length);
  for (let index = 0; index < length; index += 1) {
    const difference = (leftScalars[index] ?? 0) - (rightScalars[index] ?? 0);
    if (difference !== 0) return difference;
  }
  return leftScalars.length - rightScalars.length;
}

function isPlainObject(value: object): value is Record<string, unknown> {
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function validateJsonValue(value: unknown, active: Set<object>): void {
  if (value === null || typeof value === "string" || typeof value === "boolean") return;
  if (typeof value === "number") {
    if (!Number.isFinite(value)) fail();
    return;
  }
  if (typeof value !== "object") fail();
  if (active.has(value)) fail();
  if (!Array.isArray(value) && !isPlainObject(value)) fail();
  active.add(value);
  try {
    if (Array.isArray(value)) {
      for (const item of value) validateJsonValue(item, active);
    } else {
      for (const key of Object.keys(value)) validateJsonValue(value[key], active);
    }
  } finally {
    active.delete(value);
  }
}

function strictJsonStringify(value: unknown): string {
  try {
    validateJsonValue(value, new Set());
    const rendered = JSON.stringify(value);
    if (rendered === undefined) fail();
    return rendered;
  } catch {
    fail();
  }
}

function canonicalJson(value: unknown): string {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    const rendered = JSON.stringify(value);
    if (rendered === undefined) fail();
    return rendered;
  }
  if (Array.isArray(value)) {
    return `[${value.map(canonicalJson).join(",")}]`;
  }
  if (typeof value === "object" && value !== null && isPlainObject(value)) {
    return `{${Object.keys(value)
      .sort(unicodeScalarCompare)
      .map((key) => `${JSON.stringify(key)}:${canonicalJson(value[key])}`)
      .join(",")}}`;
  }
  fail();
}

function canonicalDigest(domain: string, value: unknown): string {
  return sha256(canonicalJson({ domain, value }));
}

function summarizeShape(value: unknown): ShapeSummary {
  if (Array.isArray(value)) {
    const children = value.map(summarizeShape);
    return {
      projection: ["array", children.map((child) => child.projection)],
      fieldCount: children.reduce((total, child) => total + child.fieldCount, 0),
      leafCount: children.reduce((total, child) => total + child.leafCount, 0),
      textCharacters: children.reduce((total, child) => total + child.textCharacters, 0),
    };
  }
  if (typeof value === "object" && value !== null) {
    const entries = Object.keys(value as Record<string, unknown>)
      .sort(unicodeScalarCompare)
      .map((key) => summarizeShape((value as Record<string, unknown>)[key]));
    return {
      projection: ["object", entries.map((entry) => entry.projection)],
      fieldCount: entries.length + entries.reduce((total, entry) => total + entry.fieldCount, 0),
      leafCount: entries.reduce((total, entry) => total + entry.leafCount, 0),
      textCharacters: entries.reduce((total, entry) => total + entry.textCharacters, 0),
    };
  }
  return {
    projection: [value === null ? "null" : typeof value],
    fieldCount: 0,
    leafCount: 1,
    textCharacters: typeof value === "string" ? Array.from(value).length : 0,
  };
}

function contentSummary(value: unknown): { digest: string | null; length: number | null } {
  if (value === undefined || value === null) return { digest: null, length: null };
  const rendered = typeof value === "string" ? value : canonicalJson(value);
  return { digest: sha256(rendered), length: Array.from(rendered).length };
}

function closeSegment(
  segmentIndex: number,
  role: SegmentRole,
  structureKind: StructureKind,
  content: unknown,
  sourceCallId: unknown,
  missingEvidence: boolean,
): SafeSegmentSummary {
  const { digest, length } = contentSummary(content);
  const sourceCallSha256 = typeof sourceCallId === "string" && sourceCallId.length > 0
    ? sha256(sourceCallId)
    : null;
  const unsigned = {
    segment_index: segmentIndex,
    role,
    structure_kind: structureKind,
    content_sha256: digest,
    content_length: length,
    source_call_sha256: sourceCallSha256,
    missing_evidence: missingEvidence || digest === null,
  };
  return {
    ...unsigned,
    segment_sha256: canonicalDigest(
      "asterion.pathlight/context-segment-summary/v1",
      unsigned,
    ),
  };
}

interface SegmentDraft {
  readonly role: SegmentRole;
  readonly structureKind: StructureKind;
  readonly content: unknown;
  readonly sourceCallId: unknown;
  readonly missingEvidence: boolean;
}

function toolResultDraft(value: Record<string, unknown>): SegmentDraft {
  const content = Object.hasOwn(value, "content") ? value.content : value.text;
  const sourceCallId = value.toolCallId ?? value.tool_call_id ?? value.tool_use_id;
  return {
    role: "tool-result",
    structureKind: "tool-result",
    content,
    sourceCallId,
    missingEvidence:
      content === undefined || typeof sourceCallId !== "string" || sourceCallId.length === 0,
  };
}

function messageDrafts(value: unknown): SegmentDraft[] {
  if (!isPlainRecord(value)) {
    return [{ role: "unknown", structureKind: "missing", content: undefined, sourceCallId: null, missingEvidence: true }];
  }
  const roleValue = value.role;
  if (roleValue === "tool" || roleValue === "tool-result" || roleValue === "tool_result" || roleValue === "toolResult") {
    return [toolResultDraft(value)];
  }
  const role: SegmentRole = roleValue === "system" || roleValue === "user" || roleValue === "assistant"
    ? roleValue
    : "unknown";
  const content = Object.hasOwn(value, "content") ? value.content : value.text;
  if (Array.isArray(content) && content.some((item) => isToolResultBlock(item))) {
    return content.map((item): SegmentDraft => {
      if (isToolResultBlock(item)) return toolResultDraft(item);
      if (isPlainRecord(item)) {
        const blockContent = Object.hasOwn(item, "text") ? item.text : item;
        return {
          role,
          structureKind: role === "unknown" ? "missing" : "message",
          content: role === "unknown" ? undefined : blockContent,
          sourceCallId: null,
          missingEvidence: role === "unknown",
        };
      }
      return {
        role,
        structureKind: role === "unknown" ? "missing" : "message",
        content: role === "unknown" ? undefined : item,
        sourceCallId: null,
        missingEvidence: role === "unknown",
      };
    });
  }
  return [{
    role,
    structureKind: role === "unknown" ? "missing" : "message",
    content: role === "unknown" ? undefined : content,
    sourceCallId: null,
    missingEvidence: role === "unknown" || content === undefined,
  }];
}

function isPlainRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value) && isPlainObject(value);
}

function isToolResultBlock(value: unknown): value is Record<string, unknown> {
  if (!isPlainRecord(value)) return false;
  return value.type === "tool_result" || value.type === "tool-result" || value.type === "toolResult";
}

function segmentDrafts(payload: unknown): SegmentDraft[] {
  if (!isPlainRecord(payload)) {
    return [{ role: "unknown", structureKind: "missing", content: undefined, sourceCallId: null, missingEvidence: true }];
  }
  const drafts: SegmentDraft[] = [];
  if (Object.hasOwn(payload, "instructions")) {
    drafts.push({
      role: "system",
      structureKind: "contract",
      content: payload.instructions,
      sourceCallId: null,
      missingEvidence: payload.instructions === undefined || payload.instructions === null,
    });
  }
  if (Object.hasOwn(payload, "system")) {
    drafts.push({
      role: "system",
      structureKind: "contract",
      content: payload.system,
      sourceCallId: null,
      missingEvidence: payload.system === undefined || payload.system === null,
    });
  }
  const messages = Array.isArray(payload.messages)
    ? payload.messages
    : Array.isArray(payload.input)
      ? payload.input
      : null;
  if (messages !== null) {
    for (const message of messages) drafts.push(...messageDrafts(message));
  }
  if (drafts.length === 0) {
    drafts.push({
      role: "unknown",
      structureKind: "missing",
      content: undefined,
      sourceCallId: null,
      missingEvidence: true,
    });
  }
  return drafts;
}

function summarizePayload(payload: unknown): SummarizedPayload {
  const payloadJson = strictJsonStringify(payload);
  const payloadBytes = Buffer.byteLength(payloadJson, "utf8");
  const parsed: unknown = JSON.parse(payloadJson);
  const shape = summarizeShape(parsed);
  const segments = segmentDrafts(parsed).map((draft, index) => closeSegment(
    index,
    draft.role,
    draft.structureKind,
    draft.content,
    draft.sourceCallId,
    draft.missingEvidence,
  ));
  const missingEvidence = segments.some((segment) => segment.missing_evidence)
    ? ["context-segment"]
    : [];
  const unsignedSummary = {
    payload_bytes: payloadBytes,
    shape_sha256: canonicalDigest("dci.provider-request/shape/v1", shape.projection),
    field_count: shape.fieldCount,
    leaf_count: shape.leafCount,
    text_characters: shape.textCharacters,
    segments,
    missing_evidence: missingEvidence,
  };
  const observation: SafeObservation = {
    payload_sha256: sha256(payloadJson),
    ...unsignedSummary,
    summary_sha256: canonicalDigest(
      "dci.provider-request-observation/summary/v1",
      unsignedSummary,
    ),
  };
  return { payloadJson, observation };
}

export function summarizeProviderPayload(payload: unknown): SafeObservation {
  return summarizePayload(payload).observation;
}

export function captureFitsLimits(recordBytes: number, capturedBytes: number): boolean {
  return Number.isSafeInteger(recordBytes)
    && Number.isSafeInteger(capturedBytes)
    && recordBytes >= 0
    && capturedBytes >= 0
    && recordBytes <= MAX_PRIVATE_RECORD_BYTES
    && capturedBytes <= MAX_NATIVE_GENERATION_BYTES - recordBytes;
}

export function writeAll(fd: number, value: Uint8Array, writer: Write = writeSync): void {
  for (let offset = 0; offset < value.length;) {
    const written = writer(fd, value, offset, value.length - offset);
    if (!Number.isSafeInteger(written) || written <= 0 || written > value.length - offset) fail();
    offset += written;
  }
}

function captureConfiguration(): { fd: number; available: boolean } {
  const validFd = typeof privateFdValue === "string"
    && /^(0|[1-9][0-9]*)$/.test(privateFdValue)
    && Number.isSafeInteger(Number(privateFdValue));
  return {
    fd: validFd ? Number(privateFdValue) : -1,
    available: validFd && captureContractValue === CAPTURE_CONTRACT_VERSION,
  };
}

function missingEntry(requestIndex: number): Record<string, unknown> {
  return {
    schema: SAFE_OBSERVATION_SCHEMA,
    request_index: requestIndex,
    capture_status: "missing",
    missing_evidence: ["provider-request-private"],
    error: FIXED_ERROR,
  };
}

export default function dciPathlightObservation(pi: ExtensionApi): void {
  const configuration = captureConfiguration();
  let requestIndex = 0;
  let capturedBytes = 0;

  pi.on("before_provider_request", (event: unknown): undefined => {
    requestIndex += 1;
    let safeAppendAttempted = false;
    try {
      if (!configuration.available || !isPlainRecord(event)) fail();
      const summarized = summarizePayload(event.payload);
      const privateRecord = {
        schema: PRIVATE_RECORD_SCHEMA,
        request_index: requestIndex,
        captured_at: new Date().toISOString(),
        payload_json: summarized.payloadJson,
        payload_sha256: summarized.observation.payload_sha256,
        payload_bytes: summarized.observation.payload_bytes,
        shape_sha256: summarized.observation.shape_sha256,
        summary_sha256: summarized.observation.summary_sha256,
      };
      const recordBytes = Buffer.from(`${JSON.stringify(privateRecord)}\n`, "utf8");
      if (!captureFitsLimits(recordBytes.length, capturedBytes)) fail();
      writeAll(configuration.fd, recordBytes);
      capturedBytes += recordBytes.length;
      safeAppendAttempted = true;
      pi.appendEntry("dci-provider-request-observation", {
        schema: SAFE_OBSERVATION_SCHEMA,
        request_index: requestIndex,
        capture_status: "captured",
        ...summarized.observation,
      });
    } catch {
      if (!safeAppendAttempted) {
        try {
          pi.appendEntry("dci-provider-request-observation", missingEntry(requestIndex));
        } catch {
          // Observation is optional and cannot change provider request semantics.
        }
      }
    }
    return undefined;
  });
}
