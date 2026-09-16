import { createHash, randomBytes } from "node:crypto";
import { closeSync, fstatSync } from "node:fs";
import { Socket } from "node:net";
import { TextDecoder } from "node:util";
import { canonicalJson, projectPrimeContext, type PrimeContextProjectionV1 } from "./context-projection.js";
import { countRebuiltContext } from "./context-counter.js";

export const CONTEXT_WITNESS_PROTOCOL = "asterion.prime-context-witness/v1";
export const SUMMARIZATION_MATERIAL_VERSION = "asterion.prime-summarization/v1";
const MAX_FRAME = 1024 * 1024;
const NONCE = /^[0-9a-f]{64}$/;
const ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$/;
const SETTINGS = Object.freeze({ enabled: false, reserveTokens: 4096, keepRecentTokens: 256 });
const BASE_KEYS = ["authority_sha256", "command_nonce", "launch_nonce", "phase", "protocol"];
const ARM_KEYS = [...BASE_KEYS, "summarization"];
// Pi host mechanics this pinned source may not import for itself: the source is
// validated to contain only `node:` specifiers and is loaded from a data: URL,
// where the host package cannot resolve. The Asterion loader is a real module in
// the host's own resolution scope and supplies exactly these three.
const DEPENDENCY_KEYS = ["buildSessionContext", "convertToLlm", "serializeConversation"];
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
const MAX_MATERIAL_BYTES = 8192;

type RecordValue = Record<string, unknown>;
export interface ContextDependencies {
  buildSessionContext(entries: unknown[]): { messages: unknown[] };
  convertToLlm(messages: unknown[]): unknown;
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

export interface ContextWitnessOptions {
  descriptor: number;
  launchNonce: string;
  maxFrameBytes?: number;
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

/** Validate the Asterion-owned prompt material the native side is authoritative for. */
function summarization(value: unknown): SummarizationMaterial {
  const material = object(value);
  keys(material, SUMMARIZATION_KEYS);
  if (material.version !== SUMMARIZATION_MATERIAL_VERSION) fail();
  for (const key of SUMMARIZATION_KEYS) {
    if (string(material[key]).length === 0) fail();
  }
  const size = Buffer.byteLength(canonicalJson(material), "utf8");
  if (size === 0 || size > MAX_MATERIAL_BYTES) fail();
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
  #pending = Buffer.alloc(0);
  #frame: RecordValue | undefined;
  #waiting: { resolve(value: RecordValue): void; reject(error: Error): void } | undefined;
  #closed = false;

  constructor(options: ContextWitnessOptions) {
    const descriptor = integer(options.descriptor);
    this.#cap = integer(options.maxFrameBytes ?? MAX_FRAME);
    this.#timeout = integer(options.timeoutMs ?? 5000);
    if (descriptor < 3 || this.#cap < 128 || this.#cap > MAX_FRAME || this.#timeout < 1 || this.#timeout > 60000) fail();
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
    const raw = Buffer.from(canonicalJson(value), "utf8");
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
  const preview = { type: "compaction", id: randomBytes(16).toString("hex"), parentId: covered,
    timestamp: "2000-01-01T00:00:00.000Z", firstKeptEntryId: firstKept, summary: "", tokensBefore: 0,
    customInstructions: instructions ?? undefined };
  const rebuilt = deps.buildSessionContext([...branch, preview]).messages;
  const summary = object(rebuilt[0]);
  if (summary.role !== "compactionSummary") fail();
  return {
    first_kept_entry_id: firstKept, covered_leaf_id: covered,
    messages_to_summarize: messages, turn_prefix_messages: prefix,
    is_split_turn: preparation.isSplitTurn, previous_summary: optionalString(preparation.previousSummary),
    custom_instructions: instructions, retained_context_projection: projectPrimeContext(rebuilt.slice(1), systemPrompt),
    retained_message_count: integer(summary.retainedMessageCount),
  };
}

export class ContextWitness {
  readonly #channel: FramedSocket;
  readonly #deps: ContextDependencies;
  readonly #launch: string;
  readonly #seen = new Set<string>();
  #identity: RecordValue | undefined;
  #proposal: RecordValue | undefined;
  #branch: unknown[] | undefined;
  #active = false;

  constructor(deps: ContextDependencies, options: ContextWitnessOptions) {
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

  async before(rawEvent: unknown, rawContext: unknown): Promise<undefined | { cancel: true }> {
    try {
      if (this.closed || this.#active || this.#proposal) fail();
      this.#active = true;
      const arm = await this.#channel.read();
      this.#authenticate(arm, "arm", ARM_KEYS);
      const summaryMaterial = summarization(arm.summarization);
      if (this.#seen.has(string(arm.command_nonce))) fail();
      this.#seen.add(string(arm.command_nonce));
      this.#identity = { protocol: CONTEXT_WITNESS_PROTOCOL, launch_nonce: this.#launch,
        command_nonce: arm.command_nonce, authority_sha256: arm.authority_sha256 };
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
      const tokensBefore = integer(preparation.tokensBefore);
      if (tokensBefore === 0) fail();
      const proposed = preparedMaterial(preparation, branch, systemPrompt, instructions, this.#deps);
      const pre = projectPrimeContext(this.#deps.buildSessionContext(branch).messages, systemPrompt);
      const [main, prefix] = requests(preparation, instructions, this.#deps, summaryMaterial);
      if (Buffer.byteLength(main) > 4096 || (prefix !== null && Buffer.byteLength(prefix) > 4096)) fail();
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
      return undefined;
    } catch {
      // Pi's extension runner can swallow exceptions. Positive cancellation is
      // required here to prevent its built-in summary or append from running.
      this.close();
      return { cancel: true };
    } finally { this.#active = false; }
  }

  async persisted(rawEvent: unknown, rawContext: unknown): Promise<void> {
    try {
      if (this.closed || this.#active || !this.#proposal || !this.#branch || !this.#identity) fail();
      this.#active = true;
      const event = object(rawEvent), context = object(rawContext);
      if (event.type !== "session_compact" || event.fromExtension !== false) fail();
      // Pi persists this entry as JSON; optional undefined fields have no bytes.
      const entry = object(JSON.parse(JSON.stringify(event.compactionEntry)));
      const proposal = this.#proposal;
      if (entry.type !== "compaction" || entry.firstKeptEntryId !== proposal.first_kept_entry_id ||
          entry.parentId !== proposal.covered_leaf_id || entry.fromHook !== false) fail();
      const summary = string(entry.summary);
      if (!summary.trim()) fail();
      const manager = object(context.sessionManager);
      if (typeof manager.getBranch !== "function" || typeof context.getSystemPrompt !== "function") fail();
      const branch = array(manager.getBranch());
      if (object(branch.at(-1)).id !== entry.id || JSON.stringify(branch.slice(0, -1)) !== JSON.stringify(this.#branch)) fail();
      const post = projectPrimeContext(this.#deps.buildSessionContext(branch).messages, string(context.getSystemPrompt()));
      const expected = projectPrimeContext(this.#deps.buildSessionContext([...this.#branch, entry]).messages,
        string(object(proposal.pre_context_projection).system_prompt));
      if (canonicalJson(post) !== canonicalJson(expected) || countRebuiltContext(post) >= integer(proposal.pre_units)) fail();
      const postJson = canonicalJson(post);
      await this.#channel.write({ ...this.#identity, phase: "persisted", first_kept_entry_id: proposal.first_kept_entry_id,
        covered_leaf_id: proposal.covered_leaf_id, preparation_sha256: proposal.preparation_sha256,
        compaction_entry: entry, compaction_entry_sha256: digest(entry), summary, summary_sha256: sha(summary),
        post_context_projection: post, post_context_json: postJson, post_context_sha256: sha(postJson) });
      const ack = await this.#channel.read();
      this.#authenticate(ack, "ack", BASE_KEYS);
      this.#proposal = this.#branch = this.#identity = undefined;
    } catch {
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
  try {
    if (fd !== undefined && /^[1-9][0-9]*$/.test(fd) && Number.isSafeInteger(Number(fd)) && Number(fd) >= 3) closeSync(Number(fd));
  } catch {}
}

export function registerContextWitnessFromEnvironment(pi: unknown, deps: unknown): ContextWitness | undefined {
  const fd = process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD;
  const launch = process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE;
  delete process.env.ASTERION_PRIME_IPYTHON_CONTEXT_FD;
  delete process.env.ASTERION_PRIME_IPYTHON_CONTEXT_LAUNCH_NONCE;
  // The host-injected existing extension binding decides whether this extension
  // witnesses compaction at all. The Pi mechanics are supplied by the loader on
  // every launch, so their presence says nothing about that binding.
  if (fd === undefined && launch === undefined) return;
  if (fd === undefined || !/^[1-9][0-9]*$/.test(fd) || launch === undefined) {
    try { if (fd !== undefined && /^[1-9][0-9]*$/.test(fd) && Number.isSafeInteger(Number(fd)) && Number(fd) >= 3) closeSync(Number(fd)); } catch {}
    fail();
  }
  return registerContextWitness(pi as ContextExtensionApi, deps as ContextDependencies,
    { descriptor: Number(fd), launchNonce: launch });
}
