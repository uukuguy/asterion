/** Snapshot-only model view; Pi owns conversation history and compaction. */
export const CONTEXT_MEMORY_VERSION = "asterion.prime-context-memory/v2";
const LEGACY_VERSION = "asterion.prime-context-memory/v1";
const SNAPSHOT_BYTE_CAP = 128 * 1024;
const REVISION = /^sha256:[0-9a-f]{64}$(?![\s\S])/;
const CALL_ID = /^[A-Za-z0-9][A-Za-z0-9._:|-]{0,255}$(?![\s\S])/;
const CUSTOM_TYPE = "asterion_context_memory";

type RecordValue = Record<string, unknown>;
export interface MemoryEnvelope {
  readonly version: typeof CONTEXT_MEMORY_VERSION | typeof LEGACY_VERSION;
  readonly revision: string | null;
  readonly content: string;
  readonly commit: boolean;
}
export interface MemoryCheckpoint {
  readonly revision: string | null;
  readonly content: string;
  /** Historical receipt identity, never a window boundary. */
  readonly anchorToolCallId?: string;
}
interface MemoryMessage {
  role: "custom";
  customType: typeof CUSTOM_TYPE;
  content: string;
  display: false;
  timestamp: number;
}
export interface MemoryProjectionOutcome {
  readonly status: "inactive" | "retained" | "unsafe-boundary";
  readonly removed_messages: number;
  readonly retained_messages: number;
  readonly history_bytes: number | null;
  readonly retained_history_bytes: number | null;
  readonly snapshot_bytes: number;
}
export interface MemoryProjection<T> {
  readonly messages: Array<T | MemoryMessage>;
  readonly outcome: MemoryProjectionOutcome;
}

export function memoryRecord(value: unknown): RecordValue | undefined {
  return typeof value === "object" && value !== null && !Array.isArray(value)
    ? value as RecordValue : undefined;
}

export function parseMemoryEnvelope(value: unknown): MemoryEnvelope | undefined {
  const record = memoryRecord(value);
  if (!record || Object.keys(record).sort().join(",") !== "commit,content,revision,version"
    || (record.version !== CONTEXT_MEMORY_VERSION && record.version !== LEGACY_VERSION)
    || typeof record.commit !== "boolean"
    || (record.revision === null
      ? record.version !== CONTEXT_MEMORY_VERSION || record.commit
      : typeof record.revision !== "string" || !REVISION.test(record.revision))
    || typeof record.content !== "string" || !record.content.trim()
    || Buffer.byteLength(record.content,"utf8") > SNAPSHOT_BYTE_CAP
    || Buffer.from(record.content,"utf8").toString("utf8") !== record.content) return undefined;
  return {version:record.version,revision:record.revision as string | null,content:record.content,commit:record.commit};
}

function synthetic(value: unknown): boolean {
  const record = memoryRecord(value);
  return record?.role === "custom" && record.customType === CUSTOM_TYPE;
}

/** Count the model-bearing JSON only; private details and provider usage are excluded. */
function messageBytes(value: unknown): number {
  const message = memoryRecord(value);
  if (!message || typeof message.role !== "string") throw new Error("invalid context");
  let projection: RecordValue;
  switch (message.role) {
    case "user":
    case "assistant":
    case "custom":
      projection = {role:message.role,content:message.content};
      break;
    case "toolResult":
      projection = {role:message.role,toolCallId:message.toolCallId,toolName:message.toolName,
        isError:message.isError,content:message.content};
      break;
    case "system":
      projection = {role:message.role,content:message.content,
        toolsAdded:message.toolsAdded,toolsRemoved:message.toolsRemoved};
      break;
    case "bashExecution":
      projection = {role:message.role,command:message.command,output:message.output,
        exitCode:message.exitCode,cancelled:message.cancelled,truncated:message.truncated};
      break;
    case "compactionSummary":
    case "branchSummary":
      projection = {role:message.role,summary:message.summary};
      break;
    default:
      throw new Error("invalid context");
  }
  return Buffer.byteLength(JSON.stringify(projection),"utf8");
}

/** Unmeasurable diagnostics never remove or block native conversation messages. */
function historyBytes(messages: readonly unknown[]): number | null {
  try {
    return 2 + messages.reduce<number>((bytes,message,index) => bytes+messageBytes(message)+(index ? 1 : 0),0);
  } catch {
    return null;
  }
}

function unchanged<T>(messages: readonly T[], status: "inactive" | "unsafe-boundary"): MemoryProjection<T> {
  const bytes = historyBytes(messages);
  return {messages:[...messages],outcome:{status,removed_messages:0,retained_messages:messages.length,
    history_bytes:bytes,retained_history_bytes:bytes,snapshot_bytes:0}};
}

/** Replace only our own snapshot; retain all native history in its original order. */
export function projectMemoryContext<T>(messages: readonly T[], checkpoint?: MemoryCheckpoint): MemoryProjection<T> {
  if (!checkpoint) return unchanged(messages,"inactive");
  const valid = parseMemoryEnvelope({version:CONTEXT_MEMORY_VERSION,revision:checkpoint.revision,
    content:checkpoint.content,commit:false});
  if (!valid) return unchanged(messages,"unsafe-boundary");
  const visible = messages.filter(message => !synthetic(message));
  const bytes = historyBytes(visible);
  const memory: MemoryMessage = {role:"custom",customType:CUSTOM_TYPE,content:checkpoint.content,display:false,timestamp:0};
  // Preserve leading Pi system messages. The registered conversation-only hook
  // normally excludes the system role and Pi restores it after this hook.
  let insertion = 0;
  while (memoryRecord(visible[insertion])?.role === "system") insertion += 1;
  const projected: Array<T | MemoryMessage> = [...visible];
  projected.splice(insertion,0,memory);
  return {messages:projected,outcome:{status:"retained",removed_messages:0,
    retained_messages:visible.length,history_bytes:bytes,retained_history_bytes:bytes,
    snapshot_bytes:Buffer.byteLength(checkpoint.content,"utf8")}};
}

/** Only native trusted application results may admit snapshots. */
export class MemoryContextController {
  #checkpoint: MemoryCheckpoint | undefined;

  accept(toolCallId: string, value: unknown): boolean {
    const envelope = parseMemoryEnvelope(value);
    if (!envelope || !CALL_ID.test(toolCallId)) return false;
    if (envelope.commit) {
      this.#checkpoint = {revision:envelope.revision,anchorToolCallId:toolCallId,content:envelope.content};
      return true;
    }
    if (!this.#checkpoint) {
      if (envelope.version !== CONTEXT_MEMORY_VERSION) return false;
      this.#checkpoint = {revision:envelope.revision,content:envelope.content};
      return true;
    }
    // V2 is an authoritative current-state snapshot and can repair a withheld
    // note acknowledgement. V1 retains its original revision-bound refresh rule.
    if (envelope.version !== CONTEXT_MEMORY_VERSION && this.#checkpoint.revision !== envelope.revision) return false;
    this.#checkpoint = {...this.#checkpoint,revision:envelope.revision,content:envelope.content};
    return true;
  }

  project<T>(messages: readonly T[]): MemoryProjection<T> {
    return projectMemoryContext(messages,this.#checkpoint);
  }
}
