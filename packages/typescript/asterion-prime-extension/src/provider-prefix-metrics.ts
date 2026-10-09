/** Numeric observation only: JSON byte prefixes are not provider token/cache prefixes. */
import {closeSync, fstatSync, ftruncateSync, writeSync} from "node:fs";
import {memoryRecord} from "./context-memory.js";

const FD_ENVIRONMENT = "ASTERION_PRIME_IPYTHON_PREFIX_METRICS_FD";
const INPUT_CAP = 8 * 1024 * 1024;
const SAMPLE_CAP = 1024;
export interface ProviderPrefixNumbers {
  readonly requests: number;
  readonly input_bytes: number;
  readonly previous_input_bytes: number;
  readonly common_prefix_bytes: number;
  readonly common_prefix_items: number;
  readonly input_items: number;
  readonly previous_input_items: number;
  readonly system_changed: number;
  readonly cache_key_changed: number;
  readonly tools_changed: number;
  readonly unmeasurable_requests: number;
  readonly peak_input_bytes: number;
}
export interface ProviderPrefixMetricsSink {
  (numbers: ProviderPrefixNumbers): void;
  close(): void;
}
interface InputBaseline {
  input: Buffer;
  itemLengths: number[];
  system: Buffer;
  cacheKey: Buffer;
  tools: Buffer;
}
function increment(value: number): number {return Math.min(Number.MAX_SAFE_INTEGER,value+1);}
function invalid(): never {throw new Error("unmeasurable provider input");}
function jsonBytes(value: unknown): Buffer {
  const serialized = JSON.stringify(value);
  if (typeof serialized !== "string" || Buffer.byteLength(serialized,"utf8") > INPUT_CAP) invalid();
  return Buffer.from(serialized,"utf8");
}
function baseline(value: unknown): InputBaseline {
  const payload = memoryRecord(value);
  if (!payload || !Array.isArray(payload.input)
    || payload.input.some(item => !memoryRecord(item))
    || (payload.instructions !== undefined && payload.instructions !== null && typeof payload.instructions !== "string")
    || (payload.prompt_cache_key !== undefined && payload.prompt_cache_key !== null && typeof payload.prompt_cache_key !== "string")
    || (payload.tools !== undefined && payload.tools !== null && !Array.isArray(payload.tools))) invalid();
  const input = jsonBytes(payload.input);
  // Use the actual JSON representation (including its key order); toJSON and
  // undefined fields must not make item boundaries disagree with the input bytes.
  const items = JSON.parse(input.toString("utf8")) as unknown[];
  if (items.some(item => !memoryRecord(item))) {input.fill(0); invalid();}
  const itemLengths = items.map(item => Buffer.byteLength(JSON.stringify(item),"utf8"));
  const system = jsonBytes({instructions:payload.instructions,
    system_items:items.filter(item => ["system","developer"].includes(String(memoryRecord(item)?.role)))});
  const cacheKey = jsonBytes({prompt_cache_key:payload.prompt_cache_key});
  const tools = jsonBytes({tools:payload.tools});
  if (input.length+system.length+cacheKey.length+tools.length > INPUT_CAP) {
    for (const bytes of [input,system,cacheKey,tools]) bytes.fill(0);
    invalid();
  }
  return {input,itemLengths,system,cacheKey,tools};
}
function clear(value?: InputBaseline): void {
  if (value) for (const bytes of [value.input,value.system,value.cacheKey,value.tools]) bytes.fill(0);
}

/** Retain one bounded transient input; only fixed numeric observations leave this class. */
export class ProviderPrefixTelemetry {
  #previous: InputBaseline | undefined;
  #requests = 0;
  #unmeasurable = 0;
  #peak = 0;

  close(): void {clear(this.#previous);this.#previous = undefined;}

  observe(payload: unknown): ProviderPrefixNumbers {
    this.#requests = increment(this.#requests);
    let current: InputBaseline | undefined;
    try {current = baseline(payload);} catch {this.#unmeasurable = increment(this.#unmeasurable);}
    const previous = current ? this.#previous : undefined;
    let commonBytes = 0, commonItems = 0;
    if (previous && current) {
      const limit = Math.min(previous.input.length,current.input.length);
      while (commonBytes < limit && previous.input[commonBytes] === current.input[commonBytes]) commonBytes += 1;
      let previousOffset = 1, currentOffset = 1;
      while (commonItems < Math.min(previous.itemLengths.length,current.itemLengths.length)) {
        const previousLength = previous.itemLengths[commonItems]!, currentLength = current.itemLengths[commonItems]!;
        if (previousLength !== currentLength || !previous.input.subarray(previousOffset,previousOffset+previousLength)
          .equals(current.input.subarray(currentOffset,currentOffset+currentLength))) break;
        previousOffset += previousLength+1;currentOffset += currentLength+1;commonItems += 1;
      }
    }
    this.#peak = Math.max(this.#peak,current?.input.length ?? 0);
    const numbers = Object.freeze({requests:this.#requests,input_bytes:current?.input.length ?? 0,
      previous_input_bytes:previous?.input.length ?? 0,common_prefix_bytes:commonBytes,common_prefix_items:commonItems,
      input_items:current?.itemLengths.length ?? 0,previous_input_items:previous?.itemLengths.length ?? 0,
      system_changed:previous && current && !previous.system.equals(current.system) ? 1 : 0,
      cache_key_changed:previous && current && !previous.cacheKey.equals(current.cacheKey) ? 1 : 0,
      tools_changed:previous && current && !previous.tools.equals(current.tools) ? 1 : 0,
      unmeasurable_requests:this.#unmeasurable,peak_input_bytes:this.#peak});
    clear(this.#previous);this.#previous = current;
    return numbers;
  }
}

/** Observe actual Pi payloads without returning a replacement or an execution fence. */
export function registerProviderPrefixMetrics(pi: unknown,
  sink: ((numbers: ProviderPrefixNumbers) => void) & {close?: () => void}): boolean {
  const api = memoryRecord(pi);
  if (!api || typeof api.on !== "function") return false;
  const observer = new ProviderPrefixTelemetry();
  let active = true;
  const close = (): void => {active = false;observer.close();try {sink.close?.();} catch {}};
  try {
    const on = api.on.bind(pi) as (event: string, handler: (event: unknown) => void) => unknown;
    on("before_provider_request",raw => {
      if (!active) return;
      const event = memoryRecord(raw);
      if (event?.type !== "before_provider_request") return;
      try {sink(observer.observe(event.payload));} catch {}
      // Undefined tells Pi to retain its original provider payload verbatim.
    });
    on("session_shutdown",close);
    return true;
  } catch {close();return false;}
}

/** Same operator-owned regular-file boundary as context metrics; no independent IPC protocol. */
export function providerPrefixMetricsFromEnvironment(): ProviderPrefixMetricsSink | undefined {
  const raw = process.env[FD_ENVIRONMENT];delete process.env[FD_ENVIRONMENT];
  if (raw === undefined || !/^[1-9][0-9]*$/.test(raw)) return;
  const descriptor = Number(raw);
  if (!Number.isSafeInteger(descriptor) || descriptor < 3) return;
  // An unvalidated FD may have been reused by Node: rejection never closes it.
  try {if (!fstatSync(descriptor).isFile()) return;} catch {return;}
  let closed = false;
  const close = (): void => {if (closed) return;closed = true;try {closeSync(descriptor);} catch {}};
  const samples: ProviderPrefixNumbers[] = [];
  const sink = (numbers: ProviderPrefixNumbers): void => {
    if (closed) return;
    try {
      const latest = Object.freeze({requests:numbers.requests,input_bytes:numbers.input_bytes,
        previous_input_bytes:numbers.previous_input_bytes,common_prefix_bytes:numbers.common_prefix_bytes,
        common_prefix_items:numbers.common_prefix_items,input_items:numbers.input_items,
        previous_input_items:numbers.previous_input_items,system_changed:numbers.system_changed,
        cache_key_changed:numbers.cache_key_changed,tools_changed:numbers.tools_changed,
        unmeasurable_requests:numbers.unmeasurable_requests,peak_input_bytes:numbers.peak_input_bytes});
      if (Object.values(latest).some(value => !Number.isSafeInteger(value) || value < 0)
        || [latest.system_changed,latest.cache_key_changed,latest.tools_changed].some(value => value > 1)) {close();return;}
      if (samples.length < SAMPLE_CAP) samples.push(latest);
      const bytes = Buffer.from(JSON.stringify({version:"asterion.prime-provider-prefix-metrics/v1",
        measurement:"provider-hook-responses-input-json-utf8",latest,samples,
        samples_truncated:latest.requests>SAMPLE_CAP ? 1 : 0}),"utf8");
      let offset = 0;
      while (offset < bytes.length) {
        const count = writeSync(descriptor,bytes,offset,bytes.length-offset,offset);
        if (count <= 0) {close();return;}offset += count;
      }
      ftruncateSync(descriptor,bytes.length);
    } catch {close();}
  };
  return Object.assign(sink,{close});
}
