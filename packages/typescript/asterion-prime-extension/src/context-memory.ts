/** Capacity-driven request-time projection; application text remains opaque. */
export const CONTEXT_MEMORY_VERSION = "asterion.prime-context-memory/v2";
const LEGACY_VERSION = "asterion.prime-context-memory/v1";
const SNAPSHOT_BYTE_CAP = 128 * 1024;
const HISTORY_TRIGGER_BYTES = 96 * 1024;
const HISTORY_TARGET_BYTES = 48 * 1024;
const MAX_RECENT_UNITS = 8;
const PROTECTED_RECENT_UNITS = 2;
const REVISION = /^sha256:[0-9a-f]{64}$(?![\s\S])/;
const CALL_ID = /^[A-Za-z0-9][A-Za-z0-9._:|-]{0,255}$(?![\s\S])/;
const CUSTOM_TYPE = "asterion_context_memory";
const PINNED_ROLES = new Set(["user","system","compactionSummary","branchSummary"]);

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
  readonly status: "inactive" | "retained" | "trimmed" | "over-budget" | "unsafe-boundary";
  readonly removed_messages: number;
  readonly retained_messages: number;
  readonly history_bytes: number;
  readonly retained_history_bytes: number;
  readonly snapshot_bytes: number;
  readonly retained_complete_units: number;
  readonly pinned_messages: number;
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

interface ContextUnits {
  readonly completed: number[][];
  readonly protectedTail: number[];
  readonly pinned: Set<number>;
}

/** Each unit includes the observation prelude leading into its assistant/tool group. */
function contextUnits(messages: readonly unknown[]): ContextUnits | undefined {
  const completed: number[][] = [];
  const pinned = new Set<number>();
  const seen = new Set<string>();
  const pending = new Map<string,string>();
  let prelude: number[] = [];
  let active: number[] | undefined;
  for (let index = 0; index < messages.length; index++) {
    const message = memoryRecord(messages[index]);
    if (!message) return undefined;
    if (PINNED_ROLES.has(String(message.role))) {
      pinned.add(index);
      continue;
    }
    if (message.role === "assistant") {
      if (active || !Array.isArray(message.content)) return undefined;
      active = [...prelude,index];
      prelude = [];
      for (const raw of message.content) {
        const block = memoryRecord(raw);
        if (block?.type !== "toolCall") continue;
        const id = block.id;
        if (typeof id !== "string" || !CALL_ID.test(id) || seen.has(id)
          || typeof block.name !== "string" || !block.name) return undefined;
        seen.add(id);
        pending.set(id,block.name);
      }
      if (!pending.size) {
        completed.push(active);
        active = undefined;
      }
    } else if (message.role === "toolResult") {
      const id = message.toolCallId;
      if (!active || typeof id !== "string" || !pending.has(id)
        || pending.get(id) !== message.toolName) return undefined;
      active.push(index);
      pending.delete(id);
      if (!pending.size) {
        completed.push(active);
        active = undefined;
      }
    } else {
      (active ?? prelude).push(index);
    }
  }
  return {completed,protectedTail:active ?? prelude,pinned};
}

function unchanged<T>(messages: readonly T[], status: "inactive" | "unsafe-boundary"): MemoryProjection<T> {
  return {messages:[...messages],outcome:{status,removed_messages:0,retained_messages:messages.length,
    history_bytes:0,retained_history_bytes:0,snapshot_bytes:0,retained_complete_units:0,pinned_messages:0}};
}

function arrayBytes(indices: Iterable<number>, costs: readonly number[]): number {
  let bytes = 2;
  let count = 0;
  for (const index of indices) {
    bytes += costs[index] ?? 0;
    if (count++) bytes += 1;
  }
  return bytes;
}

/** Notes refresh the snapshot; history capacity alone selects a safe recent window. */
export function projectMemoryContext<T>(messages: readonly T[], checkpoint?: MemoryCheckpoint): MemoryProjection<T> {
  if (!checkpoint) return unchanged(messages,"inactive");
  const valid = parseMemoryEnvelope({version:CONTEXT_MEMORY_VERSION,revision:checkpoint.revision,
    content:checkpoint.content,commit:false});
  if (!valid) return unchanged(messages,"unsafe-boundary");
  const visible = messages.filter(message => !synthetic(message));
  let costs: number[];
  try { costs = visible.map(messageBytes); }
  catch { return unchanged(messages,"unsafe-boundary"); }
  const groups = contextUnits(visible);
  if (!groups) return unchanged(messages,"unsafe-boundary");
  const historyBytes = arrayBytes(costs.keys(),costs);
  const selected = new Set(groups.pinned);
  let retainedUnits = groups.completed.length;
  let status: MemoryProjectionOutcome["status"] = "retained";
  if (historyBytes >= HISTORY_TRIGGER_BYTES) {
    for (const index of groups.protectedTail) selected.add(index);
    retainedUnits = Math.min(PROTECTED_RECENT_UNITS,groups.completed.length);
    const protectedUnits = retainedUnits ? groups.completed.slice(-retainedUnits) : [];
    for (const unit of protectedUnits) {
      for (const index of unit) selected.add(index);
    }
    status = arrayBytes(selected,costs) > HISTORY_TARGET_BYTES ? "over-budget" : "trimmed";
    if (status !== "over-budget") {
      for (let index = groups.completed.length-retainedUnits-1; index >= 0 && retainedUnits < MAX_RECENT_UNITS; index--) {
        const candidate = new Set(selected);
        for (const messageIndex of groups.completed[index]!) candidate.add(messageIndex);
        if (arrayBytes(candidate,costs) > HISTORY_TARGET_BYTES) break;
        for (const messageIndex of candidate) selected.add(messageIndex);
        retainedUnits += 1;
      }
    }
  } else {
    for (let index = 0; index < visible.length; index++) selected.add(index);
  }
  const retained = visible.filter((_message,index) => selected.has(index));
  const memory: MemoryMessage = {role:"custom",customType:CUSTOM_TYPE,content:checkpoint.content,display:false,timestamp:0};
  // Preserve the leading Pi system transcript even when this pure helper is used
  // directly. The registered conversation-only hook normally sees no system role.
  let insertion = 0;
  while (memoryRecord(retained[insertion])?.role === "system") insertion += 1;
  const projected: Array<T | MemoryMessage> = [...retained];
  projected.splice(insertion,0,memory);
  return {messages:projected,outcome:{status,removed_messages:visible.length-retained.length,
    retained_messages:retained.length,history_bytes:historyBytes,
    retained_history_bytes:arrayBytes(selected,costs),snapshot_bytes:Buffer.byteLength(checkpoint.content,"utf8"),
    retained_complete_units:retainedUnits,pinned_messages:groups.pinned.size}};
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
