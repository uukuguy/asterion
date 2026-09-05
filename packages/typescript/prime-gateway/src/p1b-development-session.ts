import { createHash } from "node:crypto";
import { inspect } from "node:util";

import {
  openPrimeP1DevelopmentSdkSession,
} from "./p1-development-session.js";
import type {
  PrimeP1DevelopmentResult,
  PrimeP1DevelopmentSessionOptions,
} from "./p1-development-session.js";

export interface PrimeP1BCompactionWitness {
  readonly compact_called: boolean;
  readonly succeeded: boolean;
  readonly start_count: number;
  readonly end_count: number;
  readonly message_count_before: number;
  readonly message_count_after: number;
  readonly tokens_before: number;
  readonly first_kept_entry_id_sha256: string;
}

/** A fixed two-prompt development session with one explicit, observed compaction. */
export class PrimeP1BDevelopmentSession {
  #state: "prompt1" | "compact" | "prompt2" | "close" | "cancelled" | "closed" = "prompt1";
  readonly #sdk: Awaited<ReturnType<typeof openPrimeP1DevelopmentSdkSession>>;

  private constructor(sdk: Awaited<ReturnType<typeof openPrimeP1DevelopmentSdkSession>>) {
    this.#sdk = sdk;
  }

  static async open(options: PrimeP1DevelopmentSessionOptions): Promise<PrimeP1BDevelopmentSession> {
    return new PrimeP1BDevelopmentSession(await openPrimeP1DevelopmentSdkSession(options, { model: 5, tool: 2 }, {
      retry: { enabled: false, provider: { maxRetries: 0 } },
      autoRefine: { enabled: false },
      compaction: { enabled: false, keepRecentTokens: 1, reserveTokens: 1536 },
    }));
  }

  async prompt(prompt: string): Promise<PrimeP1DevelopmentResult> {
    this.assertState("prompt1", "prompt2");
    await this.#sdk.session.prompt(prompt);
    await this.#sdk.session.waitForIdle();
    if (this.#state === "cancelled") return this.result("cancelled");
    this.#state = this.#state === "prompt1" ? "compact" : "close";
    return this.result("completed");
  }

  async compact(): Promise<PrimeP1BCompactionWitness> {
    this.assertState("compact");
    const messagesBefore = this.#sdk.session.agent.state.messages.length;
    let starts = 0;
    let ends = 0;
    const unsubscribe = this.#sdk.session.subscribe((event) => {
      if (!event || typeof event !== "object") return;
      const type = (event as { type?: unknown }).type;
      if (type === "compaction_start") starts += 1;
      if (type === "compaction_end") ends += 1;
    });
    try {
      const result = await this.#sdk.session.compact();
      if (this.#state === "cancelled") throw new Error("Prime P1B development session is cancelled");
      const safe = result as { firstKeptEntryId?: unknown; tokensBefore?: unknown };
      if (typeof safe.firstKeptEntryId !== "string" || typeof safe.tokensBefore !== "number") {
        throw new Error("Prime P1B development compaction returned an invalid result");
      }
      this.#state = "prompt2";
      return Object.freeze({
        compact_called: true, succeeded: true, start_count: starts, end_count: ends,
        message_count_before: messagesBefore,
        message_count_after: this.#sdk.session.agent.state.messages.length,
        tokens_before: safe.tokensBefore,
        first_kept_entry_id_sha256: createHash("sha256").update(safe.firstKeptEntryId).digest("hex"),
      });
    } finally {
      unsubscribe();
    }
  }

  async cancel(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "cancelled";
    this.#sdk.control.state = "cancelled";
    this.#sdk.session.requestAbort();
    await this.#sdk.session.abort();
  }

  async close(): Promise<void> {
    if (this.#state === "closed") return;
    this.#state = "closed";
    this.#sdk.control.state = "closed";
    try { await this.#sdk.session.disposeAsync(); } finally { this.#sdk.unregister(); }
  }

  private assertState(...allowed: Array<"prompt1" | "compact" | "prompt2">): void {
    if (this.#state === "cancelled") throw new Error("Prime P1B development session is cancelled");
    if (this.#state === "closed") throw new Error("Prime P1B development session is closed");
    if (!allowed.includes(this.#state as "prompt1" | "compact" | "prompt2")) throw new Error("Prime P1B development session has completed this phase");
  }

  private result(lifecycle: "completed" | "cancelled"): PrimeP1DevelopmentResult {
    const assistants = this.#sdk.session.agent.state.messages.filter((message) => !!message && typeof message === "object" && (message as { role?: unknown }).role === "assistant") as Array<{ stopReason?: unknown; usage?: Record<string, unknown> }>;
    const usage = assistants.reduce((total, message) => ({
      input_tokens: total.input_tokens + count(message.usage?.input),
      output_tokens: total.output_tokens + count(message.usage?.output),
      total_tokens: total.total_tokens + count(message.usage?.totalTokens),
    }), { input_tokens: 0, output_tokens: 0, total_tokens: 0 });
    const stopReason = assistants.at(-1)?.stopReason;
    return Object.freeze({ lifecycle, usage: Object.freeze(usage), assistant: Object.freeze({
      completed: lifecycle === "completed" && stopReason === "stop",
      stop_reason: lifecycle === "cancelled" ? "aborted" : safeStopReason(stopReason),
    }) });
  }

  [inspect.custom](): string { return "PrimeP1BDevelopmentSession { lifecycle: safe }"; }
}

function count(value: unknown): number { return typeof value === "number" && Number.isFinite(value) && value >= 0 ? value : 0; }
function safeStopReason(value: unknown): PrimeP1DevelopmentResult["assistant"]["stop_reason"] {
  return value === "stop" || value === "length" || value === "toolUse" || value === "error" || value === "aborted" ? value : "error";
}
