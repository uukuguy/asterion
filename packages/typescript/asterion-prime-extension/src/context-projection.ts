import { createHash } from "node:crypto";

const FORMAT = "asterion.prime-context-projection/v1";
const SAFE_INTEGER_MAX = Number.MAX_SAFE_INTEGER;
const EXCLUDED_CUSTOM_CONTEXT_TYPES = new Set([
  "session_slash_command",
  "session_slash_command_result",
  "compaction_outcome",
]);

type CanonicalPrimitive = null | boolean | number | string;
type CanonicalValue = CanonicalPrimitive | CanonicalValue[] | { [key: string]: CanonicalValue };

export interface PrimeContextProjectionV1 {
  readonly format: typeof FORMAT;
  readonly system_prompt: string;
  readonly messages: readonly PrimeContextMessage[];
}

export type PrimeContextMessage =
  | { readonly role: "user" | "assistant" | "custom"; readonly content: readonly PrimeContent[] }
  | {
      readonly role: "toolResult";
      readonly tool_name: string;
      readonly is_error: boolean;
      readonly content: readonly PrimeContent[];
    }
  | {
      readonly role: "bashExecution";
      readonly command: string;
      readonly output: string;
      readonly exit_code: number | null;
      readonly cancelled: boolean;
      readonly truncated: boolean;
    }
  | {
      readonly role: "compactionSummary";
      readonly summary: string;
      readonly retained_message_count: number | null;
      readonly custom_instructions: string | null;
    }
  | { readonly role: "branchSummary"; readonly summary: string };

export type PrimeContent =
  | { readonly type: "text"; readonly text: string }
  | { readonly type: "thinking"; readonly thinking: string }
  | { readonly type: "toolCall"; readonly name: string; readonly arguments_json: string }
  | {
      readonly type: "image";
      readonly media_type: string;
      readonly byte_length: number;
      readonly sha256: string;
    };

function invalid(): never {
  throw new Error("invalid Prime context");
}

function record(value: unknown): Record<string, unknown> {
  if (typeof value !== "object" || value === null || Array.isArray(value)) invalid();
  const prototype = Object.getPrototypeOf(value);
  if (prototype !== Object.prototype && prototype !== null) invalid();
  return value as Record<string, unknown>;
}

function exactKeys(value: Record<string, unknown>, expected: readonly string[]): void {
  const actual = Object.keys(value).sort(unicodeScalarCompare);
  const sortedExpected = [...expected].sort(unicodeScalarCompare);
  if (actual.length !== sortedExpected.length || actual.some((key, index) => key !== sortedExpected[index])) invalid();
}

function string(value: unknown): string {
  if (typeof value !== "string" || !wellFormed(value)) invalid();
  return value;
}

function boolean(value: unknown): boolean {
  if (typeof value !== "boolean") invalid();
  return value;
}

function safeInteger(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value)) invalid();
  return value;
}

function nonnegativeSafeInteger(value: unknown): number {
  const parsed = safeInteger(value);
  if (parsed < 0) invalid();
  return parsed;
}

function nullableString(value: unknown): string | null {
  return value === undefined || value === null ? null : string(value);
}

function wellFormed(value: string): boolean {
  for (let index = 0; index < value.length; index += 1) {
    const codeUnit = value.charCodeAt(index);
    if (codeUnit >= 0xd800 && codeUnit <= 0xdbff) {
      const next = value.charCodeAt(index + 1);
      if (Number.isNaN(next) || next < 0xdc00 || next > 0xdfff) return false;
      index += 1;
    } else if (codeUnit >= 0xdc00 && codeUnit <= 0xdfff) {
      return false;
    }
  }
  return true;
}

function unicodeScalarCompare(left: string, right: string): number {
  const leftScalars = [...left];
  const rightScalars = [...right];
  const length = Math.min(leftScalars.length, rightScalars.length);
  for (let index = 0; index < length; index += 1) {
    const leftScalar = leftScalars[index]!.codePointAt(0)!;
    const rightScalar = rightScalars[index]!.codePointAt(0)!;
    if (leftScalar !== rightScalar) return leftScalar - rightScalar;
  }
  return leftScalars.length - rightScalars.length;
}

function jsonString(value: string): string {
  if (!wellFormed(value)) invalid();
  return JSON.stringify(value);
}

function canonical(value: unknown, allowFiniteFloats: boolean): string {
  if (value === null || typeof value === "boolean") return JSON.stringify(value);
  if (typeof value === "string") return jsonString(value);
  if (typeof value === "number") {
    if (!Number.isFinite(value) || (!allowFiniteFloats && !Number.isSafeInteger(value))) invalid();
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map((item) => canonical(item, allowFiniteFloats)).join(",")}]`;
  if (typeof value === "object" && value !== null) {
    const item = record(value);
    return `{${Object.keys(item)
      .sort(unicodeScalarCompare)
      .map((key) => `${jsonString(key)}:${canonical(item[key], allowFiniteFloats)}`)
      .join(",")}}`;
  }
  return invalid();
}

/** Canonical JSON for the already-projected, integer-only context domain. */
export function canonicalJson(value: unknown): string {
  return canonical(value, false);
}

function canonicalToolArguments(value: unknown): string {
  return canonical(value, true);
}

function imageDescriptor(value: Record<string, unknown>): PrimeContent {
  const mediaType = string(value.mimeType ?? value.media_type);
  const data = string(value.data);
  if (!/^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$/.test(data)) invalid();
  const bytes = Buffer.from(data, "base64");
  if (bytes.toString("base64") !== data) invalid();
  return {
    type: "image",
    media_type: mediaType,
    byte_length: bytes.byteLength,
    sha256: createHash("sha256").update(bytes).digest("hex"),
  };
}

function content(value: unknown, allowedTypes: readonly PrimeContent["type"][]): PrimeContent[] {
  if (!Array.isArray(value)) invalid();
  return value.map((raw) => {
    const block = record(raw);
    const type = string(block.type) as PrimeContent["type"];
    if (!allowedTypes.includes(type)) invalid();
    switch (type) {
      case "text":
        return { type: "text", text: string(block.text) };
      case "thinking":
        return { type: "thinking", thinking: string(block.thinking) };
      case "toolCall":
        return {
          type: "toolCall",
          name: string(block.name),
          arguments_json: canonicalToolArguments(block.arguments),
        };
      case "image":
        return imageDescriptor(block);
      default:
        return invalid();
    }
  });
}

function customContent(value: unknown): PrimeContent[] {
  return typeof value === "string"
    ? [{ type: "text", text: string(value) }]
    : content(value, ["text", "image"]);
}

function projectMessage(value: unknown): PrimeContextMessage {
  const message = record(value);
  const role = string(message.role);
  switch (role) {
    case "user":
      return { role: "user", content: customContent(message.content) };
    case "assistant":
      return { role, content: content(message.content, ["text", "thinking", "toolCall"]) };
    case "custom":
      return { role: "custom", content: customContent(message.content) };
    case "toolResult":
      return {
        role: "toolResult",
        tool_name: string(message.toolName ?? message.tool_name),
        is_error: boolean(message.isError ?? message.is_error),
        content: content(message.content, ["text", "image"]),
      };
    case "bashExecution":
      return {
        role: "bashExecution",
        command: string(message.command),
        output: string(message.output),
        exit_code: message.exitCode === undefined || message.exitCode === null ? null : safeInteger(message.exitCode),
        cancelled: boolean(message.cancelled),
        truncated: boolean(message.truncated),
      };
    case "compactionSummary":
      return {
        role: "compactionSummary",
        summary: string(message.summary),
        retained_message_count:
          message.retainedMessageCount === undefined || message.retainedMessageCount === null
            ? null
            : nonnegativeSafeInteger(message.retainedMessageCount),
        custom_instructions: nullableString(message.customInstructions),
      };
    case "branchSummary":
      return { role: "branchSummary", summary: string(message.summary) };
    default:
      return invalid();
  }
}

/** Match Pi's convertToLlm exclusions without dropping other extension context. */
function excludedFromModelContext(value: unknown): boolean {
  const message = record(value);
  const role = string(message.role);
  return (
    (role === "bashExecution" && message.excludeFromContext === true) ||
    (role === "custom" &&
      typeof message.customType === "string" &&
      EXCLUDED_CUSTOM_CONTEXT_TYPES.has(message.customType))
  );
}

function deepFreeze<T>(value: T): T {
  if (value !== null && typeof value === "object" && !Object.isFrozen(value)) {
    for (const child of Object.values(value)) deepFreeze(child);
    Object.freeze(value);
  }
  return value;
}

/** Project native Pi messages to the complete model-context-bearing public shape. */
export function projectPrimeContext(messages: unknown, systemPrompt = ""): PrimeContextProjectionV1 {
  if (!Array.isArray(messages)) invalid();
  const projection: PrimeContextProjectionV1 = {
    format: FORMAT,
    system_prompt: string(systemPrompt),
    messages: messages.filter((message) => !excludedFromModelContext(message)).map(projectMessage),
  };
  return deepFreeze(projection);
}

function validateContent(value: unknown, allowedTypes: readonly PrimeContent["type"][]): void {
  if (!Array.isArray(value)) invalid();
  for (const raw of value) {
    const block = record(raw);
    const type = string(block.type) as PrimeContent["type"];
    if (!allowedTypes.includes(type)) invalid();
    switch (type) {
      case "text":
        exactKeys(block, ["text", "type"]);
        string(block.text);
        break;
      case "thinking":
        exactKeys(block, ["thinking", "type"]);
        string(block.thinking);
        break;
      case "toolCall": {
        exactKeys(block, ["arguments_json", "name", "type"]);
        string(block.name);
        const argumentsJson = string(block.arguments_json);
        let parsed: unknown;
        try {
          parsed = JSON.parse(argumentsJson);
        } catch {
          invalid();
        }
        if (canonicalToolArguments(parsed) !== argumentsJson) invalid();
        break;
      }
      case "image":
        exactKeys(block, ["byte_length", "media_type", "sha256", "type"]);
        string(block.media_type);
        nonnegativeSafeInteger(block.byte_length);
        if (typeof block.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(block.sha256)) invalid();
        break;
      default:
        invalid();
    }
  }
}

/** Validate the closed, already-projected context shape before it is counted. */
export function validatePrimeContextProjection(value: unknown): asserts value is PrimeContextProjectionV1 {
  const projection = record(value);
  exactKeys(projection, ["format", "messages", "system_prompt"]);
  if (projection.format !== FORMAT) invalid();
  string(projection.system_prompt);
  if (!Array.isArray(projection.messages)) invalid();
  for (const raw of projection.messages) {
    const message = record(raw);
    switch (string(message.role)) {
      case "user":
      case "custom":
        exactKeys(message, ["content", "role"]);
        validateContent(message.content, ["text", "image"]);
        break;
      case "assistant":
        exactKeys(message, ["content", "role"]);
        validateContent(message.content, ["text", "thinking", "toolCall"]);
        break;
      case "toolResult":
        exactKeys(message, ["content", "is_error", "role", "tool_name"]);
        string(message.tool_name);
        boolean(message.is_error);
        validateContent(message.content, ["text", "image"]);
        break;
      case "bashExecution":
        exactKeys(message, ["cancelled", "command", "exit_code", "output", "role", "truncated"]);
        string(message.command);
        string(message.output);
        if (message.exit_code !== null) safeInteger(message.exit_code);
        boolean(message.cancelled);
        boolean(message.truncated);
        break;
      case "compactionSummary":
        exactKeys(message, ["custom_instructions", "retained_message_count", "role", "summary"]);
        string(message.summary);
        if (message.retained_message_count !== null) nonnegativeSafeInteger(message.retained_message_count);
        if (message.custom_instructions !== null) string(message.custom_instructions);
        break;
      case "branchSummary":
        exactKeys(message, ["role", "summary"]);
        string(message.summary);
        break;
      default:
        invalid();
    }
  }
}
