import { createHash, timingSafeEqual } from "node:crypto";
import { chmod, unlink } from "node:fs/promises";
import { createServer, type Server } from "node:net";

export const RLM_HOST_PROTOCOL = "asterion.prime-rlm-host/v1";

export function authenticateRlmHostFrame(
  bytes: Buffer,
  sessionId: string,
  token: string,
): boolean {
  try {
    if (!/^[0-9a-f]{64}$/u.test(token) || bytes.byteLength > 1024) return false;
    const value: unknown = JSON.parse(bytes.toString("utf8"));
    if (typeof value !== "object" || value === null || Array.isArray(value)) return false;
    const record = value as Record<string, unknown>;
    if (Object.keys(record).sort().join("\n") !== ["protocol", "session_id", "token", "type"].join("\n")) return false;
    if (record.protocol !== RLM_HOST_PROTOCOL || record.type !== "authenticate" || record.session_id !== sessionId || typeof record.token !== "string" || !/^[0-9a-f]{64}$/u.test(record.token)) return false;
    return timingSafeEqual(Buffer.from(record.token, "hex"), Buffer.from(token, "hex"));
  } catch {
    return false;
  }
}

export interface RlmSpawnProposal {
  readonly requestId: string;
  readonly childId: string;
  readonly idempotencyKey: string;
  readonly goalText: string;
  readonly budget: RlmSpawnBudget;
}

export interface RlmSpawnBudget {
  readonly controller_tokens: number;
  readonly application_tokens: number;
  readonly child_tokens: number;
  readonly aggregate_tokens: number;
  readonly cost_micros: number;
  readonly deadline_ms: number;
}

export interface RlmSpawnResolution {
  readonly resolution: "admitted" | "rejected" | "uncertain";
  readonly childId: string;
}

export interface RlmHostBridgeOptions {
  readonly sessionId: string;
  readonly admitSpawn: (proposal: RlmSpawnProposal) => Promise<RlmSpawnResolution>;
}

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value: Record<string, unknown>, expected: readonly string[]): boolean {
  const actual = Object.keys(value).sort();
  const sorted = [...expected].sort();
  return actual.length === sorted.length && actual.every((key, index) => key === sorted[index]);
}

function validBudget(value: unknown): value is RlmSpawnBudget {
  if (!isRecord(value) || !hasExactKeys(value, ["controller_tokens", "application_tokens", "child_tokens", "aggregate_tokens", "cost_micros", "deadline_ms"])) return false;
  return [value.controller_tokens, value.application_tokens, value.child_tokens, value.aggregate_tokens, value.cost_micros].every((item) => Number.isSafeInteger(item) && Number(item) >= 0) && Number.isSafeInteger(value.deadline_ms) && Number(value.deadline_ms) > 0;
}

function proposalDigest(proposal: RlmSpawnProposal): string {
  return createHash("sha256").update(JSON.stringify({
    child_id: proposal.childId,
    idempotency_key: proposal.idempotencyKey,
    goal_text: proposal.goalText,
    budget: proposal.budget,
  })).digest("hex");
}

export class RlmHostBridge {
  private readonly spawns = new Map<string, { readonly digest: string; readonly promise: Promise<RlmSpawnResolution> }>();

  constructor(private readonly options: RlmHostBridgeOptions) {
    if (options.sessionId.length === 0) throw new TypeError("RLM bridge is invalid");
  }

  async proposeSpawn(proposal: RlmSpawnProposal): Promise<RlmSpawnResolution> {
    if (
      !OPAQUE_ID.test(proposal.requestId) ||
      !OPAQUE_ID.test(proposal.childId) ||
      !OPAQUE_ID.test(proposal.idempotencyKey) ||
      Buffer.byteLength(proposal.goalText, "utf8") > 1024 * 1024 ||
      !validBudget(proposal.budget)
    ) {
      throw new TypeError("RLM proposal is invalid");
    }
    const digest = proposalDigest(proposal);
    const existing = this.spawns.get(proposal.requestId);
    if (existing !== undefined) {
      if (existing.digest !== digest) throw new TypeError("RLM proposal conflicts");
      return existing.promise;
    }
    const promise = this.admit(proposal);
    this.spawns.set(proposal.requestId, { digest, promise });
    return promise;
  }

  private async admit(proposal: RlmSpawnProposal): Promise<RlmSpawnResolution> {
    const resolution = await this.options.admitSpawn(Object.freeze({ ...proposal }));
    if (
      resolution.childId !== proposal.childId ||
      !["admitted", "rejected", "uncertain"].includes(resolution.resolution)
    ) {
      throw new TypeError("RLM admission is invalid");
    }
    return Object.freeze({ ...resolution });
  }
}

export async function listenRlmHostBridge(
  path: string,
  sessionId: string,
  token: string,
  bridge: RlmHostBridge,
): Promise<{ readonly close: () => Promise<void> }> {
  await unlink(path).catch(() => undefined);
  const server: Server = createServer((socket) => {
    let authenticated = false;
    let buffer = Buffer.alloc(0);
    socket.on("data", (chunk: Buffer) => {
      buffer = Buffer.concat([buffer, chunk]);
      while (true) {
        const newline = buffer.indexOf(0x0a);
        if (newline < 0) { if (buffer.byteLength > 64 * 1024) socket.destroy(); return; }
        if (newline > 64 * 1024) return socket.destroy();
        const line = buffer.subarray(0, newline);
        buffer = buffer.subarray(newline + 1);
        if (!authenticated) {
          authenticated = authenticateRlmHostFrame(line, sessionId, token);
          if (!authenticated) return socket.destroy();
          continue;
        }
        try {
        const value: unknown = JSON.parse(line.toString("utf8"));
        if (!isRecord(value) || !hasExactKeys(value, ["type", "request_id", "child_id", "idempotency_key", "goal_text", "budget"]) || value.type !== "rlm.spawn.propose" || typeof value.request_id !== "string" || typeof value.child_id !== "string" || typeof value.idempotency_key !== "string" || typeof value.goal_text !== "string" || !validBudget(value.budget)) throw new TypeError();
        void bridge.proposeSpawn({ requestId: value.request_id, childId: value.child_id, idempotencyKey: value.idempotency_key, goalText: value.goal_text, budget: value.budget }).then((result) => socket.end(`${JSON.stringify(result)}\n`), () => socket.destroy());
        } catch { socket.destroy(); }
        return;
      }
    });
  });
  await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(path, resolve); });
  await chmod(path, 0o600);
  return Object.freeze({ close: async () => { await new Promise<void>((resolve) => server.close(() => resolve())); await unlink(path).catch(() => undefined); } });
}
