/** Request-time memory projection. Text and application identities remain opaque. */
export const CONTEXT_MEMORY_VERSION = "asterion.prime-context-memory/v1";
const SNAPSHOT_BYTE_CAP = 128 * 1024;
const REVISION = /^sha256:[0-9a-f]{64}$(?![\s\S])/;
const CALL_ID = /^[A-Za-z0-9][A-Za-z0-9._:|-]{0,255}$(?![\s\S])/;
const CUSTOM_TYPE = "asterion_context_memory";

type RecordValue = Record<string, unknown>;
export interface MemoryEnvelope {
  readonly version: typeof CONTEXT_MEMORY_VERSION;
  readonly revision: string;
  readonly content: string;
  readonly commit: boolean;
}
export interface MemoryCheckpoint {
  readonly revision: string;
  readonly anchorToolCallId: string;
  readonly content: string;
}
interface MemoryMessage {
  role: "custom";
  customType: typeof CUSTOM_TYPE;
  content: string;
  display: false;
  timestamp: number;
}
export interface MemoryProjectionOutcome {
  readonly status: "inactive" | "cut" | "anchor-missing" | "unsafe-boundary";
  readonly removed_messages: number;
  readonly retained_messages: number;
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
    || record.version !== CONTEXT_MEMORY_VERSION || typeof record.commit !== "boolean"
    || typeof record.revision !== "string" || !REVISION.test(record.revision)
    || typeof record.content !== "string" || !record.content.trim()
    || Buffer.byteLength(record.content,"utf8") > SNAPSHOT_BYTE_CAP
    || Buffer.from(record.content,"utf8").toString("utf8") !== record.content) return undefined;
  return {version:CONTEXT_MEMORY_VERSION,revision:record.revision,content:record.content,commit:record.commit};
}

function synthetic(value: unknown): boolean {
  const record = memoryRecord(value);
  return record?.role === "custom" && record.customType === CUSTOM_TYPE;
}

function outcome<T>(messages: readonly T[], status: MemoryProjectionOutcome["status"], removed = 0): MemoryProjection<T> {
  return {messages:[...messages],outcome:{status,removed_messages:removed,retained_messages:messages.length}};
}

/** Never edit message objects or split an assistant's complete tool-call group. */
export function projectMemoryContext<T>(messages: readonly T[], checkpoint?: MemoryCheckpoint): MemoryProjection<T> {
  if (!checkpoint) return outcome(messages,"inactive");
  const valid = parseMemoryEnvelope({version:CONTEXT_MEMORY_VERSION,revision:checkpoint.revision,
    content:checkpoint.content,commit:true});
  if (!valid || !CALL_ID.test(checkpoint.anchorToolCallId)) return outcome(messages,"unsafe-boundary");
  const visible = messages.filter(message => !synthetic(message));
  const memory: MemoryMessage = {role:"custom",customType:CUSTOM_TYPE,content:checkpoint.content,display:false,timestamp:0};
  const pending = new Map<string,{index:number,name:string}>();
  const seen = new Set<string>();
  let anchorIndex: number | undefined;
  let anchorSettled = false;
  let unsafe = false;
  for (let index = 0; index < visible.length; index++) {
    const message = memoryRecord(visible[index]);
    if (!message) { unsafe = true; break; }
    if (message.role === "assistant") {
      const content = message.content;
      if (!Array.isArray(content)) { unsafe = true; break; }
      if (pending.size) { unsafe = true; break; }
      for (const value of content) {
        const block = memoryRecord(value);
        if (block?.type !== "toolCall") continue;
        const id = block.id;
        if (typeof id !== "string" || !CALL_ID.test(id) || seen.has(id)
          || typeof block.name !== "string" || !block.name) { unsafe = true; break; }
        seen.add(id);
        pending.set(id,{index,name:block.name});
        if (id === checkpoint.anchorToolCallId) anchorIndex = index;
      }
    } else if (message.role === "toolResult") {
      const id = message.toolCallId;
      if (typeof id !== "string" || !pending.has(id)
        || pending.get(id)?.name !== message.toolName) { unsafe = true; break; }
      pending.delete(id);
      if (id === checkpoint.anchorToolCallId) {
        if (message.isError !== false) { unsafe = true; break; }
        anchorSettled = true;
      }
    } else if (pending.size) { unsafe = true; break; }
    if (unsafe) break;
  }
  if (unsafe || (anchorIndex !== undefined && (!anchorSettled || [...pending.values()].some(group => group.index === anchorIndex)))) {
    return outcome(messages,"unsafe-boundary");
  }
  if (anchorIndex === undefined) {
    return {messages:[memory,...visible],outcome:{status:"anchor-missing",removed_messages:0,retained_messages:visible.length}};
  }
  return {messages:[memory,...visible.slice(anchorIndex)],
    outcome:{status:"cut",removed_messages:anchorIndex,retained_messages:visible.length-anchorIndex}};
}

/** Only trusted adapters may admit envelopes; refreshes never move the anchor. */
export class MemoryContextController {
  #checkpoint: MemoryCheckpoint | undefined;

  accept(toolCallId: string, value: unknown): boolean {
    const envelope = parseMemoryEnvelope(value);
    if (!envelope || !CALL_ID.test(toolCallId)) return false;
    if (envelope.commit) {
      this.#checkpoint = {revision:envelope.revision,anchorToolCallId:toolCallId,content:envelope.content};
      return true;
    }
    if (this.#checkpoint?.revision !== envelope.revision) return false;
    this.#checkpoint = {...this.#checkpoint,content:envelope.content};
    return true;
  }

  project<T>(messages: readonly T[]): MemoryProjection<T> {
    return projectMemoryContext(messages,this.#checkpoint);
  }
}
