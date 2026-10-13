/** Snapshot-only model view; Pi owns conversation history and compaction. */
import {archiveSystemMessage,parseContextCheckpoint,primaryContextHistory,type ContextCheckpointReceipt,type NativeContextArchive,type ContextRefusalReason} from './context-archive.js';
export const CONTEXT_MEMORY_VERSION = "asterion.prime-context-memory/v2";
export const PRIMARY_CONTEXT_MEMORY_VERSION = "asterion.prime-context-memory/v3";
const LEGACY_VERSION = "asterion.prime-context-memory/v1";
const SNAPSHOT_BYTE_CAP = 128 * 1024;
const REVISION = /^sha256:[0-9a-f]{64}$(?![\s\S])/;
const CALL_ID = /^[A-Za-z0-9][A-Za-z0-9._:|-]{0,255}$(?![\s\S])/;
const CUSTOM_TYPE = "asterion_context_memory";

type RecordValue = Record<string, unknown>;
export interface MemoryEnvelope {
  readonly version: typeof CONTEXT_MEMORY_VERSION | typeof LEGACY_VERSION | typeof PRIMARY_CONTEXT_MEMORY_VERSION;
  readonly revision: string | null;
  readonly content: string;
  readonly commit: boolean;
}
export interface MemoryCheckpoint {
  readonly revision: string | null;
  readonly content: string;
  /** Historical receipt identity, never a window boundary. */
  readonly anchorToolCallId?: string;
  /** Latest admitted current-state source, independent of the historical note receipt. */
  readonly stateToolCallId?: string | undefined;
}
interface MemoryMessage {
  role: "custom";
  customType: typeof CUSTOM_TYPE;
  content: string;
  display: false;
  timestamp: number;
}
export interface MemoryProjectionOutcome {
  readonly status: "inactive" | "retained" | "unsafe-boundary" | "primary" | "primary-unavailable";
  readonly refusal_reason?: ContextRefusalReason;
  readonly retired_complete_groups?: number;
  readonly protected_complete_groups?: number;
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
    || ![CONTEXT_MEMORY_VERSION,LEGACY_VERSION,PRIMARY_CONTEXT_MEMORY_VERSION].includes(String(record.version))
    || typeof record.commit !== "boolean"
    || (record.revision === null
      ? record.version === LEGACY_VERSION || record.commit
      : typeof record.revision !== "string" || !REVISION.test(record.revision))
    || typeof record.content !== "string" || !record.content.trim()
    || Buffer.byteLength(record.content,"utf8") > SNAPSHOT_BYTE_CAP
    || Buffer.from(record.content,"utf8").toString("utf8") !== record.content) return undefined;
  return {version:record.version as MemoryEnvelope['version'],revision:record.revision as string | null,content:record.content,commit:record.commit};
}

function synthetic(value: unknown): boolean {
  const record = memoryRecord(value);
  return record?.role === "custom" && record.customType === CUSTOM_TYPE;
}

/** Count the model-bearing JSON only; private details and provider usage are excluded. */
export function contextMessageBytes(value: unknown): number {
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
      projection = archiveSystemMessage(message);
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
    return 2 + messages.reduce<number>((bytes,message,index) => bytes+contextMessageBytes(message)+(index ? 1 : 0),0);
  } catch {
    return null;
  }
}

function unchanged<T>(messages: readonly T[], status: "inactive" | "unsafe-boundary"): MemoryProjection<T> {
  const bytes = historyBytes(messages);
  return {messages:[...messages],outcome:{status,removed_messages:0,retained_messages:messages.length,
    history_bytes:bytes,retained_history_bytes:bytes,snapshot_bytes:0}};
}

/** Insert after a complete, uniquely paired source group; never interrupt native siblings. */
function snapshotInsertion(messages: readonly unknown[], stateToolCallId?: string): number {
  if (!stateToolCallId || !CALL_ID.test(stateToolCallId)) return messages.length;
  const sourceResults: number[] = [];
  const sourceCalls: number[] = [];
  messages.forEach((raw,index) => {
    const message = memoryRecord(raw);
    if (message?.role === "toolResult" && message.toolCallId === stateToolCallId) sourceResults.push(index);
    if (message?.role === "assistant" && Array.isArray(message.content)) {
      for (const block of message.content) if (memoryRecord(block)?.type === "toolCall"
        && memoryRecord(block)?.id === stateToolCallId) sourceCalls.push(index);
    }
  });
  if (sourceResults.length === 0 && sourceCalls.length === 0) {
    // Pi compaction can omit the source from the visible view while the selected
    // raw branch still admits it. Leading native summaries form a stable boundary.
    let index = 0;
    while (memoryRecord(messages[index])?.role === "system") index += 1;
    const start = index;
    while (["compactionSummary","branchSummary"].includes(String(memoryRecord(messages[index])?.role))) index += 1;
    return index > start ? index : messages.length;
  }
  if (sourceResults.length !== 1 || sourceCalls.length !== 1 || sourceCalls[0]! >= sourceResults[0]!) return messages.length;
  const assistant = memoryRecord(messages[sourceCalls[0]!])!;
  if (assistant.stopReason === "error" || assistant.stopReason === "aborted") return messages.length;
  const calls = (assistant.content as unknown[]).map(memoryRecord).filter(block => block?.type === "toolCall");
  const expected = new Map<string,string>();
  for (const call of calls) {
    if (!call || typeof call.id !== "string" || !CALL_ID.test(call.id) || typeof call.name !== "string"
      || expected.has(call.id)) return messages.length;
    expected.set(call.id,call.name);
  }
  // Duplicated calls/results anywhere in the view cannot authorize an insertion.
  for (const [id] of expected) {
    let callCount = 0, resultCount = 0;
    for (const raw of messages) {
      const message = memoryRecord(raw);
      if (message?.role === "assistant" && Array.isArray(message.content))
        callCount += message.content.filter(block => memoryRecord(block)?.type === "toolCall" && memoryRecord(block)?.id === id).length;
      if (message?.role === "toolResult" && message.toolCallId === id) resultCount += 1;
    }
    if (callCount !== 1 || resultCount !== 1) return messages.length;
  }
  const completed = new Set<string>();
  for (let index = sourceCalls[0]!+1; index < messages.length; index += 1) {
    const message = memoryRecord(messages[index]);
    if (message?.role === "system") continue;
    if (message?.role !== "toolResult" || typeof message.toolCallId !== "string"
      || expected.get(message.toolCallId) !== message.toolName || completed.has(message.toolCallId)) return messages.length;
    if (message.toolCallId === stateToolCallId && message.isError !== false) return messages.length;
    completed.add(message.toolCallId);
    if (completed.size === expected.size) return index+1;
  }
  return messages.length;
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
  // A stable state source keeps its snapshot before later computations. Pi owns
  // custom-to-user conversion; no synthetic message is added to the raw archive.
  const projected: Array<T | MemoryMessage> = [...visible];
  projected.splice(snapshotInsertion(visible,checkpoint.stateToolCallId),0,memory);
  return {messages:projected,outcome:{status:"retained",removed_messages:0,
    retained_messages:visible.length,history_bytes:bytes,retained_history_bytes:bytes,
    snapshot_bytes:Buffer.byteLength(checkpoint.content,"utf8")}};
}

/** Only native trusted application results may admit snapshots. */
export class MemoryContextController {
  #checkpoint: MemoryCheckpoint | undefined;
  #epoch: {receipt:ContextCheckpointReceipt|undefined; checkpoint:MemoryCheckpoint} | undefined;
  #primaryMode = false;

  get primaryMode(): boolean {return this.#primaryMode;}

  accept(toolCallId: string, value: unknown, stableSource = true, receipt?:unknown): boolean {
    const envelope = parseMemoryEnvelope(value);
    if (!envelope || !CALL_ID.test(toolCallId)) return false;
    this.#primaryMode ||= envelope.version===PRIMARY_CONTEXT_MEMORY_VERSION;
    if (envelope.commit) {
      this.#checkpoint = {revision:envelope.revision,anchorToolCallId:toolCallId,stateToolCallId:stableSource ? toolCallId : undefined,content:envelope.content};
      this.#epoch = envelope.version===PRIMARY_CONTEXT_MEMORY_VERSION
        ? {receipt:stableSource ? parseContextCheckpoint(receipt) : undefined,checkpoint:this.#checkpoint} : undefined;
      return true;
    }
    // The admitted note's as-of baseline stays immutable throughout its epoch.
    // Fresh state and uncertain results remain in subsequent native interactions.
    if(this.#epoch) return true;
    if(envelope.version===PRIMARY_CONTEXT_MEMORY_VERSION && envelope.revision===null) return true;
    if (!this.#checkpoint) {
      if (envelope.version === LEGACY_VERSION) return false;
      this.#checkpoint = {revision:envelope.revision,stateToolCallId:stableSource ? toolCallId : undefined,content:envelope.content};
      return true;
    }
    // V2 is an authoritative current-state snapshot and can repair a withheld
    // note acknowledgement. V1 retains its original revision-bound refresh rule.
    if (envelope.version === LEGACY_VERSION && this.#checkpoint.revision !== envelope.revision) return false;
    this.#checkpoint = {...this.#checkpoint,revision:envelope.revision,stateToolCallId:stableSource ? toolCallId : undefined,content:envelope.content};
    return true;
  }

  project<T>(messages: readonly T[],archive?:NativeContextArchive): MemoryProjection<T> {
    if(this.#epoch) {
      const {checkpoint,receipt}=this.#epoch;
      let refusalReason:ContextRefusalReason='checkpoint-mismatch';
      const selected=receipt && receipt.source_tool_call_id===checkpoint.anchorToolCallId && receipt.notes_revision===checkpoint.revision
        ? primaryContextHistory(messages,archive,receipt,reason=>{refusalReason=reason;}) : undefined;
      if(!selected) {
        const fallback=projectMemoryContext(messages,checkpoint);
        return {...fallback,outcome:{...fallback.outcome,status:'primary-unavailable',refusal_reason:refusalReason}};
      }
      const memory:MemoryMessage={role:'custom',customType:CUSTOM_TYPE,content:checkpoint.content+'\n\n'+selected.catalog,display:false,timestamp:0};
      const projected=[...selected.messages] as Array<T|MemoryMessage>;
      projected.splice(selected.insertion,0,memory);
      return {messages:projected,outcome:{status:'primary',removed_messages:Math.max(0,messages.length-selected.messages.length),
        retained_messages:selected.messages.length,history_bytes:historyBytes(messages),retained_history_bytes:historyBytes(selected.messages),
        snapshot_bytes:Buffer.byteLength(memory.content,'utf8'),retired_complete_groups:selected.retired,protected_complete_groups:selected.protectedGroups}};
    }
    return projectMemoryContext(messages,this.#checkpoint);
  }
}
