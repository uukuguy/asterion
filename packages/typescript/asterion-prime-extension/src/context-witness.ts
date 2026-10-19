import { constants as bufferConstants } from "node:buffer";
import { createHash, randomBytes } from "node:crypto";
import { closeSync, fstatSync } from "node:fs";
import { Socket } from "node:net";
import { TextDecoder } from "node:util";
import { canonicalJson, nonnegativeSafeInteger, projectPrimeContext, type PrimeContextProjectionV1 } from "./context-projection.js";
import { countRebuiltContext } from "./context-counter.js";

export const CONTEXT_WITNESS_PROTOCOL = "asterion.prime-context-witness/v1";
export const SUMMARIZATION_MATERIAL_VERSION = "asterion.prime-summarization/v1";
const STRUCTURAL_FRAME_MAX = Math.min(0xffffffff, bufferConstants.MAX_LENGTH - 4);
const DEFAULT_POLICY: Readonly<PrimeCompactionPolicy> = Object.freeze({
  max_total_tokens: 262144, max_frame_bytes: 16777216, max_material_bytes: 65536 });
const POLICY_KEYS = ["max_total_tokens", "max_frame_bytes", "max_material_bytes"];
const CONFIG_SOURCES = ["framework-default", "application", "operator", "authority"] as const;
const POLICY_ENV = "ASTERION_PRIME_IPYTHON_COMPACTION_POLICY";
const NONCE = /^[0-9a-f]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const SETTINGS = Object.freeze({ enabled: false, reserveTokens: 16384, keepRecentTokens: 256 });
const CODE_SUMMARY_VERSION = "asterion.prime-code-summary/v1";
const NATIVE_SUMMARY_MARKERS = [
  "## Goal", "## Constraints & Preferences", "## Progress", "## Key Decisions",
  "## Next Steps", "## Critical Context",
];

function isNativeGenericSummary(text: string): boolean {
  return NATIVE_SUMMARY_MARKERS.some(marker => text.includes(marker));
}

function isDedicatedCodeSummary(text: unknown): text is string {
  return typeof text === "string"
    && text.startsWith(`${CODE_SUMMARY_VERSION}\n`)
    && text.includes("\nbelow_native_threshold: true\n")
    && !isNativeGenericSummary(text);
}
const BASE_KEYS = ["authority_sha256", "command_nonce", "launch_nonce", "phase", "protocol"];
const ARM_KEYS = [...BASE_KEYS, "summarization", "compaction_policy"];
// Pi host mechanics this pinned source may not import for itself: the source is
// validated to contain only `node:` specifiers and is loaded from a data: URL,
// where the host package cannot resolve. The Asterion loader is a real module in
// the host's own resolution scope and supplies these native mechanics.
const DEPENDENCY_KEYS = ["buildSessionContext", "convertToLlm", "getCurrentSystemMessage", "serializeConversation"];
const SUMMARIZATION_KEYS = ["conversation_block", "initial_instruction", "previous_summary_block",
  "system_prompt", "turn_prefix_instruction", "update_instruction", "user_instructions_template", "version"];
const CONVERSATION_MARKER = "{conversation}";
const PREVIOUS_MARKER = "{previous_summary}";
const INSTRUCTIONS_MARKER = "{instructions}";
// Each template carries exactly one marker of its own and no other template's
// marker, so a substitution can never rescan text it just inserted.
const MARKERS: Record<string, readonly string[]> = Object.freeze({
  conversation_block: [CONVERSATION_MARKER],
  previous_summary_block: [PREVIOUS_MARKER],
  user_instructions_template: [INSTRUCTIONS_MARKER],
});
const ALL_MARKERS = [CONVERSATION_MARKER, PREVIOUS_MARKER, INSTRUCTIONS_MARKER];
// The host accepts exactly these entry fields, rejects any other, and digests
// the entry it receives. Pi's own entry additionally carries token accounting
// (`usage.cost`) whose values are floats: the integer-only wire canonical form
// cannot express them, and the host would reject the key outright. The wire
// therefore carries the contract fields, and the digest covers what was sent.
const WIRE_ENTRY_KEYS = ["type", "id", "parentId", "timestamp", "firstKeptEntryId", "summary",
  "tokensBefore", "fromHook"] as const;

function projectedEntry(entry: RecordValue): RecordValue {
  const projected: RecordValue = {};
  for (const key of WIRE_ENTRY_KEYS) projected[key] = entry[key];
  if (entry.systemMessage !== undefined) {
    projected.systemMessage = projectPrimeContext([entry.systemMessage]).messages[0];
  }
  return projected;
}

type RecordValue = Record<string, unknown>;
export interface ContextDependencies {
  buildSessionContext(entries: unknown[]): { messages: unknown[] };
  convertToLlm(messages: unknown[]): unknown;
  getCurrentSystemMessage(messages: unknown[]): unknown;
  serializeConversation(messages: unknown): string;
}

export interface SummarizationMaterial {
  readonly version: string;
  readonly system_prompt: string;
  readonly conversation_block: string;
  readonly previous_summary_block: string;
  readonly initial_instruction: string;
  readonly update_instruction: string;
  readonly user_instructions_template: string;
  readonly turn_prefix_instruction: string;
}

export interface ContextExtensionApi {
  on(event: string, handler: (event: unknown, context: unknown) => Promise<unknown> | void): void;
}

export interface PrimeCompactionPolicy {
  readonly max_total_tokens: number;
  readonly max_frame_bytes: number;
  readonly max_material_bytes: number;
}
export type ConfigSource = typeof CONFIG_SOURCES[number];
interface LimitDiagnostic {
  readonly limit_code: "witness-frame-limit" | "summarization-material-limit";
  readonly phase: "admission" | "settlement";
  readonly action: "rejected" | "recovery-required";
  readonly observed: number;
  readonly limit: number;
  readonly unit: "bytes";
  readonly measurement: "exact";
  readonly config_source: ConfigSource;
}
class ResourceLimitError extends Error {
  constructor(readonly diagnostic: Readonly<LimitDiagnostic>) { super("resource limit exceeded"); }
}
function resourceLimit(code: LimitDiagnostic["limit_code"], observed: number, limit: number,
                       source: ConfigSource): never {
  throw new ResourceLimitError(Object.freeze({limit_code: code, phase: "admission", action: "rejected",
    observed: integer(observed), limit: integer(limit), unit: "bytes", measurement: "exact", config_source: source}));
}
function configSource(raw: unknown): ConfigSource {
  const value = string(raw);
  if (!CONFIG_SOURCES.includes(value as ConfigSource)) fail();
  return value as ConfigSource;
}
function validatePolicy(raw: unknown): Readonly<PrimeCompactionPolicy> {
  const value = object(raw);
  keys(value, POLICY_KEYS);
  const total = integer(value.max_total_tokens), frame = integer(value.max_frame_bytes),
    material = integer(value.max_material_bytes);
  if (total < 1 || frame < 1 || frame > STRUCTURAL_FRAME_MAX || material < 1 || material >= frame) fail();
  return Object.freeze({max_total_tokens: total, max_frame_bytes: frame, max_material_bytes: material});
}
function transportedPolicy(raw: unknown): {policy: Readonly<PrimeCompactionPolicy>; source: ConfigSource} {
  const value = object(raw);
  keys(value, [...POLICY_KEYS, "config_source"]);
  return {policy: validatePolicy({max_total_tokens:value.max_total_tokens,
    max_frame_bytes:value.max_frame_bytes,max_material_bytes:value.max_material_bytes}),
    source:configSource(value.config_source)};
}
function effectivePolicy(options: ContextWitnessOptions): Readonly<PrimeCompactionPolicy> {
  let policy = validatePolicy(options.policy ?? DEFAULT_POLICY);
  if (options.maxFrameBytes !== undefined) {
    const alias = integer(options.maxFrameBytes);
    if (options.policy !== undefined && alias !== policy.max_frame_bytes) fail();
    policy = validatePolicy({...policy, max_frame_bytes:alias});
  }
  return policy;
}

export interface ContextWitnessOptions {
  descriptor: number;
  launchNonce: string;
  maxFrameBytes?: number;
  policy?: Readonly<PrimeCompactionPolicy>;
  configSource?: ConfigSource;
  timeoutMs?: number;
}

function unavailable(): Error { return new Error("Asterion context witness is unavailable"); }
function fail(): never { throw unavailable(); }
function object(value: unknown): RecordValue {
  if (value === null || typeof value !== "object" || Array.isArray(value)) fail();
  return value as RecordValue;
}
function string(value: unknown): string {
  if (typeof value !== "string") fail();
  canonicalJson(value);
  return value;
}
function integer(value: unknown): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 0) fail();
  return value;
}
function array(value: unknown): unknown[] { if (!Array.isArray(value)) fail(); return value; }
function keys(value: RecordValue, expected: readonly string[]): void {
  if (JSON.stringify(Object.keys(value).sort()) !== JSON.stringify([...expected].sort())) fail();
}
function sha(value: string): string { return createHash("sha256").update(value, "utf8").digest("hex"); }
function digest(value: unknown): string { return sha(canonicalJson(value)); }
function optionalString(value: unknown): string | null { return value === undefined || value === null ? null : string(value); }
function identifier(value: unknown): string { const text = string(value); if (!ID.test(text)) fail(); return text; }
function nonce(value: unknown): string { const text = string(value); if (!NONCE.test(text)) fail(); return text; }

/** The generic pinned loader owns module loading and its guard lifetime. */
function dependencies(value: unknown): ContextDependencies {
  const selected = object(value);
  keys(selected, DEPENDENCY_KEYS);
  if (!Object.isFrozen(selected)) fail();
  for (const key of DEPENDENCY_KEYS) {
    if (typeof selected[key] !== "function") fail();
  }
  return selected as unknown as ContextDependencies;
}

/** Validate inherited templates; their equality does not prove native request parity. */
function summarization(value: unknown, policy: Readonly<PrimeCompactionPolicy>, source: ConfigSource): SummarizationMaterial {
  const material = object(value);
  keys(material, SUMMARIZATION_KEYS);
  if (material.version !== SUMMARIZATION_MATERIAL_VERSION) fail();
  for (const key of SUMMARIZATION_KEYS) {
    if (string(material[key]).length === 0) fail();
  }
  const size = Buffer.byteLength(canonicalJson(material), "utf8");
  if (size > policy.max_material_bytes) resourceLimit("summarization-material-limit", size, policy.max_material_bytes, source);
  for (const key of SUMMARIZATION_KEYS) {
    const text = material[key] as string;
    const expected = MARKERS[key] ?? [];
    for (const marker of ALL_MARKERS) {
      const head = text.indexOf(marker);
      const present = head >= 0;
      if (present !== expected.includes(marker)) fail();
      if (present && text.indexOf(marker, head + marker.length) >= 0) fail();
    }
  }
  return Object.freeze({
    version: material.version as string,
    system_prompt: material.system_prompt as string,
    conversation_block: material.conversation_block as string,
    previous_summary_block: material.previous_summary_block as string,
    initial_instruction: material.initial_instruction as string,
    update_instruction: material.update_instruction as string,
    user_instructions_template: material.user_instructions_template as string,
    turn_prefix_instruction: material.turn_prefix_instruction as string,
  });
}

/** Substitute once, never rescanning the inserted value: `replace` semantics would. */
function fill(template: string, marker: string, value: string): string {
  const head = template.indexOf(marker);
  if (head < 0 || template.indexOf(marker, head + marker.length) >= 0) fail();
  return template.slice(0, head) + value + template.slice(head + marker.length);
}

/** Select the initial or update instruction and append the optional user block. */
export function summarizeInstruction(material: SummarizationMaterial, customInstructions: string | null,
                                     previousSummary: string | null): string {
  let instruction = previousSummary ? material.update_instruction : material.initial_instruction;
  if (customInstructions) instruction += fill(material.user_instructions_template, INSTRUCTIONS_MARKER, customInstructions);
  return instruction;
}

/** Apply the one assembly rule over an already serialized conversation. */
export function composeSummarizationRequest(material: SummarizationMaterial, conversation: string,
                                            instruction: string, previousSummary: string | null): string {
  let text = fill(material.conversation_block, CONVERSATION_MARKER, conversation);
  if (previousSummary) text += fill(material.previous_summary_block, PREVIOUS_MARKER, previousSummary);
  return canonicalJson(projectPrimeContext([{ role: "user", content: [{ type: "text", text: text + instruction }] }],
    material.system_prompt));
}

class FramedSocket {
  readonly #socket: Socket;
  readonly #cap: number;
  readonly #timeout: number;
  readonly #source: ConfigSource;
  #pending = Buffer.alloc(0);
  #frame: RecordValue | undefined;
  #waiting: { resolve(value: RecordValue): void; reject(error: Error): void } | undefined;
  #closed = false;

  constructor(options: ContextWitnessOptions) {
    const descriptor = integer(options.descriptor);
    this.#cap = effectivePolicy(options).max_frame_bytes;
    this.#source = configSource(options.configSource ?? "framework-default");
    this.#timeout = integer(options.timeoutMs ?? 5000);
    if (descriptor < 3 || this.#timeout < 1 || this.#timeout > 60000) fail();
    if (!fstatSync(descriptor).isSocket()) fail();
    this.#socket = new Socket({ fd: descriptor, readable: true, writable: true });
    this.#socket.on("error", () => this.close());
    this.#socket.on("end", () => this.close());
    this.#socket.on("close", () => this.close());
    this.#socket.on("data", (chunk: Buffer) => this.#data(chunk));
  }

  get closed(): boolean { return this.#closed; }

  close(): void {
    if (this.#closed) return;
    this.#closed = true;
    this.#pending.fill(0);
    this.#pending = Buffer.alloc(0);
    this.#frame = undefined;
    this.#waiting?.reject(unavailable());
    this.#waiting = undefined;
    this.#socket.destroy();
  }

  #data(chunk: Buffer): void {
    try {
      if (this.#closed || this.#frame !== undefined || this.#pending.length + chunk.length > this.#cap + 4) fail();
      // Inspect a split or complete unsigned header before copying any body.
      if (this.#pending.length < 4 && this.#pending.length + chunk.length >= 4) {
        const header = Buffer.alloc(4);
        try {
          this.#pending.copy(header);
          chunk.copy(header, this.#pending.length, 0, 4 - this.#pending.length);
          const declared = header.readUInt32BE(0);
          if (declared === 0 || declared > this.#cap) fail();
        } finally { header.fill(0); }
      }
      const combined = Buffer.concat([this.#pending, chunk]);
      this.#pending.fill(0);
      chunk.fill(0);
      this.#pending = combined;
      if (combined.length < 4) return;
      const size = combined.readUInt32BE(0);
      if (size === 0 || size > this.#cap || combined.length > size + 4) fail();
      if (combined.length < size + 4) return;
      const text = new TextDecoder("utf-8", { fatal: true }).decode(combined.subarray(4));
      const frame = object(JSON.parse(text));
      // Canonical wire JSON rejects duplicate keys and non-integer metadata.
      if (canonicalJson(frame) !== text) fail();
      this.#pending.fill(0);
      this.#pending = Buffer.alloc(0);
      const waiting = this.#waiting;
      this.#waiting = undefined;
      if (waiting) waiting.resolve(frame);
      else this.#frame = frame;
    } catch { this.close(); }
    finally { chunk.fill(0); }
  }

  async #bounded<T>(operation: Promise<T>): Promise<T> {
    let timer: ReturnType<typeof setTimeout> | undefined;
    try {
      return await Promise.race([operation, new Promise<never>((_, reject) => {
        timer = setTimeout(() => { this.close(); reject(unavailable()); }, this.#timeout);
      })]);
    } finally { if (timer !== undefined) clearTimeout(timer); }
  }

  async read(): Promise<RecordValue> {
    if (this.#closed || this.#waiting) fail();
    if (this.#frame) { const frame = this.#frame; this.#frame = undefined; return frame; }
    return await this.#bounded(new Promise((resolve, reject) => { this.#waiting = { resolve, reject }; }));
  }

  async write(value: RecordValue): Promise<void> {
    if (this.#closed || this.#frame || this.#pending.length) fail();
    const text = canonicalJson(value);
    const size = Buffer.byteLength(text, "utf8");
    if (size > this.#cap) resourceLimit("witness-frame-limit", size, this.#cap, this.#source);
    const raw = Buffer.from(text, "utf8");
    let wire: Buffer | undefined;
    try {
      if (raw.length === 0 || raw.length > this.#cap) fail();
      wire = Buffer.alloc(raw.length + 4);
      wire.writeUInt32BE(raw.length);
      raw.copy(wire, 4);
      await this.#bounded(new Promise<void>((resolve, reject) => {
        this.#socket.write(wire!, (error?: Error | null) => error ? reject(unavailable()) : resolve());
      }));
      if (this.#closed) fail();
    } finally { raw.fill(0); wire?.fill(0); }
  }
}

function realSource(projection: PrimeContextProjectionV1): boolean {
  return projection.messages.some(message => {
    if (message.role === "system") return false;
    if (message.role === "branchSummary" || message.role === "compactionSummary") return Boolean(message.summary.trim());
    if (message.role === "bashExecution") return Boolean(message.command.trim() || message.output.trim());
    return message.content.some(block => block.type === "toolCall" ||
      (block.type === "image" ? block.byte_length > 0 : block.type === "text" ? Boolean(block.text.trim()) : Boolean(block.thinking.trim())));
  });
}

function requests(preparation: RecordValue, instructions: string | null, deps: ContextDependencies,
                  material: SummarizationMaterial): [string, string | null] {
  const previous = optionalString(preparation.previousSummary);
  const history = (conversation: unknown[]): string => composeSummarizationRequest(material,
    deps.serializeConversation(deps.convertToLlm(conversation)),
    summarizeInstruction(material, instructions, previous), previous);
  return [
    history(array(preparation.messagesToSummarize)),
    preparation.isSplitTurn === true && array(preparation.turnPrefixMessages).length > 0
      ? composeSummarizationRequest(material,
          deps.serializeConversation(deps.convertToLlm(array(preparation.turnPrefixMessages))),
          material.turn_prefix_instruction, null) : null,
  ];
}

function preparedMaterial(preparation: RecordValue, branch: unknown[], systemPrompt: string, instructions: string | null,
                          deps: ContextDependencies): RecordValue {
  const firstKept = identifier(preparation.firstKeptEntryId);
  if (!branch.length || branch.filter(raw => object(raw).id === firstKept).length !== 1) fail();
  const covered = identifier(object(branch.at(-1)).id);
  const messages = projectPrimeContext(array(preparation.messagesToSummarize));
  const prefix = projectPrimeContext(array(preparation.turnPrefixMessages));
  if (!realSource(messages) && !realSource(prefix)) fail();
  if (typeof preparation.isSplitTurn !== "boolean") fail();
  // Public buildSessionContext supplies both the retained material and its raw
  // presentation boundary. The preview is never appended to Pi's session.
  // Use the same native reducer as appendCompaction, never a parallel replay
  // of system-section/tool-delta semantics in the witness or Python host.
  const systemMessage = deps.getCurrentSystemMessage(deps.buildSessionContext(branch).messages);
  const preview = { type: "compaction", id: randomBytes(16).toString("hex"), parentId: covered,
    timestamp: "2000-01-01T00:00:00.000Z", firstKeptEntryId: firstKept, summary: "", tokensBefore: 0,
    customInstructions: instructions ?? undefined,
    ...(systemMessage === undefined ? {} : { systemMessage }) };
  const rebuilt = deps.buildSessionContext([...branch, preview]).messages;
  const summaryIndex = systemMessage === undefined ? 0 : 1;
  const summary = object(rebuilt[summaryIndex]);
  if (summary.role !== "compactionSummary") fail();
  const systemProjection = systemMessage === undefined ? undefined : projectPrimeContext([systemMessage]);
  if (systemProjection !== undefined && (systemProjection.messages[0]?.role !== "system" ||
      canonicalJson(projectPrimeContext(rebuilt.slice(0, 1))) !== canonicalJson(systemProjection))) fail();
  return {
    first_kept_entry_id: firstKept, covered_leaf_id: covered,
    messages_to_summarize: messages, turn_prefix_messages: prefix,
    is_split_turn: preparation.isSplitTurn, previous_summary: optionalString(preparation.previousSummary),
    custom_instructions: instructions,
    ...(systemProjection === undefined ? {} : { system_context_projection: systemProjection }),
    retained_context_projection: projectPrimeContext(rebuilt.slice(summaryIndex + 1), systemPrompt),
    // Pi states retention by `firstKeptEntryId` and never emits a retained
    // count, so a witness proposal declares null. Only a real producer (the
    // takeover shape, D-2026-09-16-01) supplies one. This mirrors
    // `projectPrimeContext`, which already tolerates the same absence.
    retained_message_count: summary.retainedMessageCount === undefined || summary.retainedMessageCount === null
      ? null : nonnegativeSafeInteger(summary.retainedMessageCount),
  };
}

export class ContextWitness {
  readonly #channel: FramedSocket;
  readonly #deps: ContextDependencies;
  readonly #launch: string;
  readonly #policy: Readonly<PrimeCompactionPolicy>;
  readonly #source: ConfigSource;
  readonly #seen = new Set<string>();
  #identity: RecordValue | undefined;
  #proposal: RecordValue | undefined;
  #branch: unknown[] | undefined;
  #active = false;

  constructor(deps: ContextDependencies, options: ContextWitnessOptions) {
    this.#policy = effectivePolicy(options);
    this.#source = configSource(options.configSource ?? "framework-default");
    this.#deps = dependencies(deps);
    this.#launch = nonce(options.launchNonce);
    this.#channel = new FramedSocket(options);
  }

  get closed(): boolean { return this.#channel.closed; }
  close(): void { this.#channel.close(); this.#proposal = this.#branch = this.#identity = undefined; }

  #authenticate(frame: RecordValue, phase: string, expectedKeys: readonly string[]): void {
    keys(frame, expectedKeys);
    if (frame.protocol !== CONTEXT_WITNESS_PROTOCOL || frame.phase !== phase || nonce(frame.launch_nonce) !== this.#launch) fail();
    nonce(frame.command_nonce); nonce(frame.authority_sha256);
    if (this.#identity && (frame.command_nonce !== this.#identity.command_nonce || frame.authority_sha256 !== this.#identity.authority_sha256)) fail();
  }

  async #refuseLimit(error: unknown, settled: boolean): Promise<boolean> {
    if (!(error instanceof ResourceLimitError) || !this.#identity || this.closed) return false;
    const diagnostic = settled ? Object.freeze({...error.diagnostic,
      phase: "settlement", action: "recovery-required"}) : error.diagnostic;
    try {
      // Complete arm admission leaves room for this tiny, authenticated refusal.
      await this.#channel.write({...this.#identity, phase:"limit", limit_diagnostic:diagnostic});
      return true;
    } catch { return false; }
  }

  async before(rawEvent: unknown, rawContext: unknown): Promise<
    undefined | { cancel: true } | {
      compaction: { summary: string; firstKeptEntryId: string; tokensBefore: number };
    }
  > {
    try {
      if (this.closed || this.#active || this.#proposal) fail();
      this.#active = true;
      const arm = await this.#channel.read();
      this.#authenticate(arm, "arm", ARM_KEYS);
      const configured = transportedPolicy(arm.compaction_policy);
      if (canonicalJson(configured.policy) !== canonicalJson(this.#policy) || configured.source !== this.#source) fail();
      if (this.#seen.has(string(arm.command_nonce))) fail();
      this.#seen.add(string(arm.command_nonce));
      this.#identity = { protocol: CONTEXT_WITNESS_PROTOCOL, launch_nonce: this.#launch,
        command_nonce: arm.command_nonce, authority_sha256: arm.authority_sha256 };
      const summaryMaterial = summarization(arm.summarization, this.#policy, this.#source);
      const event = object(rawEvent), context = object(rawContext);
      if (event.type !== "session_before_compact") fail();
      const signal = event.signal as AbortSignal | undefined;
      if (signal?.aborted) fail();
      const branch = array(event.branchEntries);
      if (new Set(branch.map(raw => identifier(object(raw).id))).size !== branch.length) fail();
      for (let index = 1; index < branch.length; index++) if (object(branch[index]).parentId !== object(branch[index - 1]).id) fail();
      const preparation = object(event.preparation);
      if (canonicalJson(preparation.settings) !== canonicalJson(SETTINGS)) fail();
      if (typeof context.getSystemPrompt !== "function") fail();
      const systemPrompt = string(context.getSystemPrompt());
      const instructions = optionalString(event.customInstructions);
      // A version-prefixed native template is not a code summary. Refuse it
      // before Pi's summarizer can persist Goal/Constraints sections.
      if (typeof instructions === "string" && instructions.startsWith(`${CODE_SUMMARY_VERSION}\n`)
          && !isDedicatedCodeSummary(instructions)) fail();
      const tokensBefore = integer(preparation.tokensBefore);
      if (tokensBefore === 0) fail();
      const proposed = preparedMaterial(preparation, branch, systemPrompt, instructions, this.#deps);
      const pre = projectPrimeContext(this.#deps.buildSessionContext(branch).messages, systemPrompt);
      const [main, prefix] = requests(preparation, instructions, this.#deps, summaryMaterial);
      // The request embeds the serialized conversation being summarized, so a
      // real one exceeds any small constant; the transport frame cap is the
      // only non-arbitrary limit, and the channel write enforces the total.
      const preJson = canonicalJson(pre);
      this.#proposal = { ...this.#identity, phase: "proposal", first_kept_entry_id: proposed.first_kept_entry_id,
        covered_leaf_id: proposed.covered_leaf_id, preparation: proposed, preparation_sha256: digest(proposed),
        source_kind: array(object(proposed.messages_to_summarize).messages).length ? "messages" : "turn-prefix",
        pre_context_projection: pre, pre_context_json: preJson, pre_context_sha256: sha(preJson),
        main_summary_request: main, turn_prefix_summary_request: prefix, pre_units: countRebuiltContext(pre),
        private_diagnostics: { tokensBefore } };
      this.#branch = JSON.parse(JSON.stringify(branch)) as unknown[];
      await this.#channel.write(this.#proposal);
      const decision = await this.#channel.read();
      this.#authenticate(decision, "decision", [...BASE_KEYS, "status"]);
      if (decision.status === "reject") {
        this.#proposal = this.#branch = this.#identity = undefined;
        return { cancel: true };
      }
      if (decision.status !== "approve" || signal?.aborted || this.closed) fail();
      // Supplying the summary here makes Pi persist it and skip the native
      // summarizer. The persisted entry then carries fromHook.
      if (isDedicatedCodeSummary(instructions)) {
        return {
          compaction: {
            summary: instructions,
            firstKeptEntryId: identifier(preparation.firstKeptEntryId),
            tokensBefore,
          },
        };
      }
      return undefined;
    } catch (error) {
      const refused = await this.#refuseLimit(error, false);
      // Pi's extension runner can swallow exceptions. Positive cancellation is
      // required here to prevent its built-in summary or append from running.
      if (refused) this.#proposal = this.#branch = this.#identity = undefined;
      else this.close();
      return { cancel: true };
    } finally { this.#active = false; }
  }

  async persisted(rawEvent: unknown, rawContext: unknown): Promise<void> {
    try {
      if (this.closed || this.#active || !this.#proposal || !this.#branch || !this.#identity) fail();
      this.#active = true;
      const event = object(rawEvent), context = object(rawContext);
      if (event.type !== "session_compact") fail();
      // Pi persists this entry as JSON; optional undefined fields have no bytes.
      const entry = object(JSON.parse(JSON.stringify(event.compactionEntry)));
      const proposal = this.#proposal;
      const proposedInstructions = optionalString(object(proposal.preparation).custom_instructions);
      const dedicated = isDedicatedCodeSummary(proposedInstructions);
      if (dedicated) {
        if (event.fromExtension !== true) fail();
      } else if (event.fromExtension !== false) fail();
      if (entry.type !== "compaction" || entry.firstKeptEntryId !== proposal.first_kept_entry_id ||
          entry.parentId !== proposal.covered_leaf_id) fail();
      if (dedicated) {
        if (entry.fromHook !== true) fail();
      } else if (entry.fromHook !== false) fail();
      const summary = string(entry.summary);
      if (!summary.trim()) fail();
      if (dedicated && (summary !== proposedInstructions || isNativeGenericSummary(summary))) fail();
      const manager = object(context.sessionManager);
      if (typeof manager.getBranch !== "function" || typeof context.getSystemPrompt !== "function") fail();
      const branch = array(manager.getBranch());
      if (object(branch.at(-1)).id !== entry.id || JSON.stringify(branch.slice(0, -1)) !== JSON.stringify(this.#branch)) fail();
      const post = projectPrimeContext(this.#deps.buildSessionContext(branch).messages, string(context.getSystemPrompt()));
      const expected = projectPrimeContext(this.#deps.buildSessionContext([...this.#branch, entry]).messages,
        string(object(proposal.pre_context_projection).system_prompt));
      // The projection equality already binds the rebuild to Pi's retained tail
      // plus the summary, so the only free quantity is the summary's own size —
      // which is Pi's to choose. A byte bound on it refused legitimate
      // compactions: markdown-heavy summaries cost more JSON bytes per token
      // than the conversation they replace, and measured runs landed on both
      // sides of it (five points, the closest by 23 bytes).
      if (canonicalJson(post) !== canonicalJson(expected)) fail();
      const postJson = canonicalJson(post);
      const wire = projectedEntry(entry);
      const preparation = object(proposal.preparation);
      const systemProjection = preparation.system_context_projection;
      if (systemProjection === undefined) {
        if (wire.systemMessage !== undefined) fail();
      } else if (wire.systemMessage === undefined || canonicalJson(wire.systemMessage) !==
          canonicalJson(array(object(systemProjection).messages)[0])) fail();
      await this.#channel.write({ ...this.#identity, phase: "persisted", first_kept_entry_id: proposal.first_kept_entry_id,
        covered_leaf_id: proposal.covered_leaf_id, preparation_sha256: proposal.preparation_sha256,
        compaction_entry: wire, compaction_entry_sha256: digest(wire), summary, summary_sha256: sha(summary),
        post_context_projection: post, post_context_json: postJson, post_context_sha256: sha(postJson) });
      const ack = await this.#channel.read();
      this.#authenticate(ack, "ack", BASE_KEYS);
      this.#proposal = this.#branch = this.#identity = undefined;
    } catch (error) {
      await this.#refuseLimit(error, true);
      this.close();
      // The owner observes EOF/missing persisted acknowledgement and fences even
      // when Pi catches an extension error after its session already mutated.
      throw unavailable();
    } finally { this.#active = false; }
  }
}

export function registerContextWitness(pi: ContextExtensionApi, deps: ContextDependencies,
                                       options: ContextWitnessOptions): ContextWitness {
  let witness: ContextWitness | undefined;
  try {
    if (typeof pi.on !== "function") fail();
    witness = new ContextWitness(deps, options);
    const selected = witness;
    pi.on("session_before_compact", (event, context) => selected.before(event, context));
    pi.on("session_compact", (event, context) => selected.persisted(event, context));
    pi.on("session_shutdown", () => selected.close());
    return selected;
  } catch {
    if (witness) witness.close();
    else { try { if (Number.isSafeInteger(options.descriptor) && options.descriptor >= 3) closeSync(options.descriptor); } catch {} }
    throw unavailable();
  }
}

/** Only the host-injected existing extension binding may enable the witness. */
export function discardContextWitnessEnvironment(): void {
  const fd = process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD;
  delete process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD;
  delete process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE;
  delete process.env[POLICY_ENV];
  try {
    if (fd !== undefined && /^[1-9][0-9]*$/.test(fd) && Number.isSafeInteger(Number(fd)) && Number(fd) >= 3) closeSync(Number(fd));
  } catch {}
}

export function registerContextWitnessFromEnvironment(pi: unknown, deps: unknown): ContextWitness | undefined {
  const fd = process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD;
  const launch = process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE;
  const bootstrap = process.env[POLICY_ENV];
  delete process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD;
  delete process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE;
  delete process.env[POLICY_ENV];
  // Only the existing host binding supplies this private transport, never .env.
  if (fd === undefined && launch === undefined && bootstrap === undefined) return;
  try {
    if (fd === undefined || !/^[1-9][0-9]*$/.test(fd) || launch === undefined ||
        bootstrap === undefined || Buffer.byteLength(bootstrap, "utf8") > 512) fail();
    const raw = JSON.parse(bootstrap);
    if (canonicalJson(raw) !== bootstrap) fail();
    const configured = transportedPolicy(raw);
    return registerContextWitness(pi as ContextExtensionApi, deps as ContextDependencies,
      {descriptor:Number(fd), launchNonce:launch, policy:configured.policy, configSource:configured.source});
  } catch {
    try { if (fd !== undefined && /^[1-9][0-9]*$/.test(fd) && Number.isSafeInteger(Number(fd)) && Number(fd) >= 3) closeSync(Number(fd)); } catch {}
    fail();
  }
}
