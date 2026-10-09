/** Application-authored stale state views; native evidence is never changed. */
import {createHash} from "node:crypto";
import {memoryRecord} from "./context-memory.js";

export const TOOL_STATE_VIEW_VERSION = "asterion.prime-tool-state-view/v1";
const TEXT_CAP = 128 * 1024;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:|-]{0,255}$(?![\s\S])/;
const HASH = /^sha256:[0-9a-f]{64}$(?![\s\S])/;
interface StateProposal {
  version: typeof TOOL_STATE_VIEW_VERSION;
  state_key: string;
  replacement_text: string;
}
interface AdmittedStateView extends StateProposal {
  original_text_sha256: string;
  tool_call_id: string;
  tool_name: string;
}

function boundedText(value: unknown, maximum: number): value is string {
  return typeof value === "string" && value.length > 0
    && Buffer.byteLength(value,"utf8") <= maximum
    && Buffer.from(value,"utf8").toString("utf8") === value;
}

function exactKeys(value: Record<string,unknown>, keys: string[]): boolean {
  return Object.keys(value).sort().join(",") === keys.sort().join(",");
}

function proposal(value: unknown): StateProposal | undefined {
  const record = memoryRecord(value);
  if (!record || !exactKeys(record,["version","state_key","replacement_text"])
    || record.version !== TOOL_STATE_VIEW_VERSION
    || !boundedText(record.state_key,1024) || !boundedText(record.replacement_text,TEXT_CAP)) return undefined;
  return {version:TOOL_STATE_VIEW_VERSION,state_key:record.state_key,replacement_text:record.replacement_text};
}

function textHash(text: string): string {
  return "sha256:"+createHash("sha256").update(text,"utf8").digest("hex");
}

/** Called only at the trusted method-result edge, after its final visible text is formed. */
export function admitToolStateView(value: unknown, text: string, toolCallId: string,
  toolName: string): AdmittedStateView | undefined {
  const valid = proposal(value);
  if (!valid || !boundedText(text,TEXT_CAP) || !ID.test(toolCallId) || !ID.test(toolName)
    || Buffer.byteLength(valid.replacement_text,"utf8") >= Buffer.byteLength(text,"utf8")) return undefined;
  return {...valid,original_text_sha256:textHash(text),tool_call_id:toolCallId,tool_name:toolName};
}

function admitted(value: unknown): AdmittedStateView | undefined {
  const record = memoryRecord(value);
  if (!record || !exactKeys(record,["version","state_key","replacement_text","original_text_sha256",
    "tool_call_id","tool_name"])) return undefined;
  const {original_text_sha256,tool_call_id,tool_name,...raw} = record;
  const valid = proposal(raw);
  if (!valid || typeof original_text_sha256 !== "string" || !HASH.test(original_text_sha256)
    || typeof tool_call_id !== "string" || !ID.test(tool_call_id)
    || typeof tool_name !== "string" || !ID.test(tool_name)) return undefined;
  return {...valid,original_text_sha256,tool_call_id,tool_name};
}

interface NativePair {name: string; index: number; count: number}
function pairs(messages: readonly unknown[]): {
  calls: Map<string,NativePair>; results: Map<string,number>;
} {
  const calls = new Map<string,NativePair>();
  const results = new Map<string,number>();
  messages.forEach((raw,index) => {
    const message = memoryRecord(raw);
    if (message?.role === "assistant" && Array.isArray(message.content)) {
      for (const rawBlock of message.content) {
        const block = memoryRecord(rawBlock);
        if (block?.type !== "toolCall" || typeof block.id !== "string") continue;
        const previous = calls.get(block.id);
        calls.set(block.id,{name:String(block.name),index,count:(previous?.count ?? 0)+1});
      }
    } else if (message?.role === "toolResult" && typeof message.toolCallId === "string") {
      results.set(message.toolCallId,(results.get(message.toolCallId) ?? 0)+1);
    }
  });
  return {calls,results};
}

/** Replace only older, visible, uniquely paired successful results for one state key/tool. */
export function projectToolStateViewContext<T>(messages: readonly T[], branchMessages: readonly unknown[] = messages): {
  messages: T[]; outcome: {replaced_results: number; replaced_bytes: number};
} {
  const visiblePairs = pairs(messages);
  const branchPairs = pairs(branchMessages);
  const branchResults = new Map<string,{message:Record<string,unknown>;index:number}>();
  branchMessages.forEach((raw,index) => {
    const message = memoryRecord(raw);
    if (message?.role === "toolResult" && typeof message.toolCallId === "string")
      branchResults.set(message.toolCallId,{message,index});
  });
  const candidates: Array<{index:number;view:AdmittedStateView;scope:string}> = [];
  messages.forEach((raw,index) => {
    const message = memoryRecord(raw);
    if (message?.role !== "toolResult" || message.isError !== false
      || typeof message.toolCallId !== "string" || typeof message.toolName !== "string"
      || !Array.isArray(message.content) || message.content.length !== 1) return;
    const text = memoryRecord(message.content[0]);
    if (text?.type !== "text" || !boundedText(text.text,TEXT_CAP)) return;
    const source = branchResults.get(message.toolCallId);
    if (!source || source.message.isError !== false || source.message.toolName !== message.toolName
      || !Array.isArray(source.message.content) || source.message.content.length !== 1) return;
    const sourceText = memoryRecord(source.message.content[0]);
    if (sourceText?.type !== "text" || sourceText.text !== text.text) return;
    const view = admitted(memoryRecord(source.message.details)?.tool_state_view);
    if (!view || view.tool_call_id !== message.toolCallId || view.tool_name !== message.toolName
      || view.original_text_sha256 !== textHash(text.text)
      || Buffer.byteLength(view.replacement_text,"utf8") >= Buffer.byteLength(text.text,"utf8")) return;
    for (const [native,position] of [[visiblePairs,index],[branchPairs,source.index]] as const) {
      const call = native.calls.get(message.toolCallId);
      if (!call || call.count !== 1 || native.results.get(message.toolCallId) !== 1
        || call.name !== message.toolName || call.index >= position) return;
    }
    candidates.push({index,view,scope:JSON.stringify([message.toolName,view.state_key])});
  });
  const latest = new Map<string,number>();
  for (const candidate of candidates) latest.set(candidate.scope,candidate.index);
  const projected = [...messages];
  const outcome = {replaced_results:0,replaced_bytes:0};
  for (const candidate of candidates) {
    if (latest.get(candidate.scope) === candidate.index) continue;
    const message = memoryRecord(messages[candidate.index]);
    if (message) {
      projected[candidate.index] = {...message,content:[{type:"text",text:candidate.view.replacement_text}]} as T;
      const text = memoryRecord((message.content as unknown[])[0])?.text as string;
      outcome.replaced_results += 1;
      outcome.replaced_bytes += Buffer.byteLength(text,"utf8")-Buffer.byteLength(candidate.view.replacement_text,"utf8");
    }
  }
  return {messages:projected,outcome};
}

export function projectToolStateViews<T>(messages: readonly T[], branchMessages: readonly unknown[] = messages): T[] {
  return projectToolStateViewContext(messages,branchMessages).messages;
}
