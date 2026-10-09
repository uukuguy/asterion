/** Bounded numeric observation of the final extension view, never provider wire/tokens. */
import {closeSync, fstatSync, ftruncateSync, writeSync} from "node:fs";
import {contextMessageBytes, memoryRecord} from "./context-memory.js";

const METRICS_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_CONTEXT_METRICS_FD";
const SAMPLE_CAP = 1024;
const EXCLUDED_CUSTOM_TYPES = new Set(["session_slash_command","session_slash_command_result","compaction_outcome"]);
export interface ContextViewNumbers {
  readonly requests: number;
  readonly assistant_bytes: number;
  readonly current_snapshot_bytes: number;
  readonly tool_result_bytes: number;
  readonly other_bytes: number;
  readonly total_bytes: number;
  readonly peak_total_bytes: number;
  readonly cumulative_total_bytes: number;
  readonly unmeasurable_requests: number;
}
export interface ContextViewMetricsSink {
  (numbers: ContextViewNumbers): void;
  close(): void;
}

function boundedAdd(left: number, right: number): number {
  return left > Number.MAX_SAFE_INTEGER-right ? Number.MAX_SAFE_INTEGER : left+right;
}

/** The only retained state is numeric; each category is a sum of message JSON UTF-8 bytes. */
export class ContextViewTelemetry {
  #requests = 0;
  #peak = 0;
  #cumulative = 0;
  #unmeasurable = 0;

  observe(messages: readonly unknown[]): ContextViewNumbers {
    this.#requests = boundedAdd(this.#requests,1);
    let assistant = 0, snapshot = 0, tools = 0, other = 0;
    try {
      for (const raw of messages) {
        const message = memoryRecord(raw);
        if (message?.role === "custom" && EXCLUDED_CUSTOM_TYPES.has(String(message.customType))) continue;
        const bytes = contextMessageBytes(raw);
        if (message?.role === "assistant") assistant = boundedAdd(assistant,bytes);
        else if (message?.role === "custom" && message.customType === "asterion_context_memory") snapshot = boundedAdd(snapshot,bytes);
        else if (message?.role === "toolResult") tools = boundedAdd(tools,bytes);
        else other = boundedAdd(other,bytes);
      }
    } catch {
      // Incomplete/unknown native data must never become an execution fence.
      assistant = snapshot = tools = other = 0;
      this.#unmeasurable = boundedAdd(this.#unmeasurable,1);
    }
    const total = boundedAdd(boundedAdd(assistant,snapshot),boundedAdd(tools,other));
    this.#peak = Math.max(this.#peak,total);
    this.#cumulative = boundedAdd(this.#cumulative,total);
    return Object.freeze({requests:this.#requests,assistant_bytes:assistant,current_snapshot_bytes:snapshot,
      tool_result_bytes:tools,other_bytes:other,total_bytes:total,peak_total_bytes:this.#peak,
      cumulative_total_bytes:this.#cumulative,unmeasurable_requests:this.#unmeasurable});
  }
}

/** Consume an operator-owned regular-file descriptor; malformed/failed diagnostics stay silent. */
export function contextViewMetricsFromEnvironment(): ContextViewMetricsSink | undefined {
  const raw = process.env[METRICS_ENVIRONMENT];
  delete process.env[METRICS_ENVIRONMENT];
  if (raw === undefined || !/^[1-9][0-9]*$/.test(raw)) return;
  const descriptor = Number(raw);
  if (!Number.isSafeInteger(descriptor) || descriptor < 3) return;
  let closed = false;
  const close = (): void => {
    if (closed) return;
    closed = true;
    try {closeSync(descriptor);} catch {}
  };
  try {if (!fstatSync(descriptor).isFile()) {close(); return;}} catch {close(); return;}
  const samples: ContextViewNumbers[] = [];
  const sink = (numbers: ContextViewNumbers): void => {
    if (closed) return;
    try {
      // Copy exactly the closed numeric shape: callbacks cannot smuggle extra metadata.
      const latest = Object.freeze({requests:numbers.requests,assistant_bytes:numbers.assistant_bytes,
        current_snapshot_bytes:numbers.current_snapshot_bytes,tool_result_bytes:numbers.tool_result_bytes,
        other_bytes:numbers.other_bytes,total_bytes:numbers.total_bytes,peak_total_bytes:numbers.peak_total_bytes,
        cumulative_total_bytes:numbers.cumulative_total_bytes,unmeasurable_requests:numbers.unmeasurable_requests});
      if (Object.values(latest).some(value => !Number.isSafeInteger(value) || value < 0)) {close(); return;}
      if (samples.length < SAMPLE_CAP) samples.push(latest);
      const bytes = Buffer.from(JSON.stringify({version:"asterion.prime-context-view-metrics/v1",
        measurement:"extension-hook-json-utf8",latest,samples,samples_truncated:latest.requests>SAMPLE_CAP ? 1 : 0}),"utf8");
      let offset = 0;
      while (offset < bytes.length) {
        const written = writeSync(descriptor,bytes,offset,bytes.length-offset,offset);
        if (written <= 0) {close(); return;}
        offset += written;
      }
      ftruncateSync(descriptor,bytes.length);
    } catch {close();}
  };
  return Object.assign(sink,{close});
}
