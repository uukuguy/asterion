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
  readonly rlmDepth: number;
  readonly modelSelectorDigest: string;
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

export interface RlmDeleteProposal {
  readonly requestId: string;
  readonly childId: string;
}

export interface RlmDeleteResolution {
  readonly resolution: "admitted" | "rejected" | "uncertain";
  readonly childId: string;
}

export interface RlmHostBridgeOptions {
  readonly sessionId: string;
  readonly maxSpawnCount?: number;
  readonly admitSpawn: (proposal: RlmSpawnProposal) => Promise<RlmSpawnResolution>;
  readonly admitDelete?: (proposal: RlmDeleteProposal) => Promise<RlmDeleteResolution>;
  readonly admitMessage?: (proposal: RlmMessageProposal) => Promise<RlmMessageResolution>;
  readonly recordMessageDelivered?: (event: RlmMessageDelivery) => Promise<void>;
  readonly recordLifecycle?: (event: RlmHostLifecycleEvent) => Promise<void>;
}

export interface RlmMessageProposal {
  readonly requestId: string;
  readonly messageId: string;
  readonly senderId: string;
  readonly recipientId: string;
  readonly bodyText: string;
}

export interface RlmMessageResolution {
  readonly resolution: "admitted" | "rejected" | "uncertain";
  readonly messageId: string;
}

export interface RlmMessageDelivery {
  readonly messageId: string;
}

export type RlmHostLifecycleEvent =
  | Readonly<{
      readonly type: "rlm.child.started";
      readonly childId: string;
      readonly nativeIdentityDigest: string;
    }>
  | Readonly<{
      readonly type: "rlm.child.terminal";
      readonly childId: string;
      readonly status: "completed" | "failed" | "cancelled";
    }>
  | Readonly<{ readonly type: "rlm.child.deleted"; readonly childId: string }>;

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

function validDigest(value: unknown): value is string {
  return typeof value === "string" && /^[0-9a-f]{64}$/u.test(value);
}

function proposalDigest(proposal: RlmSpawnProposal): string {
  return createHash("sha256").update(JSON.stringify({
    child_id: proposal.childId,
    idempotency_key: proposal.idempotencyKey,
    goal_text: proposal.goalText,
    rlm_depth: proposal.rlmDepth,
    model_selector_digest: proposal.modelSelectorDigest,
    budget: proposal.budget,
  })).digest("hex");
}

function messageDigest(proposal: RlmMessageProposal): string {
  return createHash("sha256").update(JSON.stringify({
    message_id: proposal.messageId,
    sender_id: proposal.senderId,
    recipient_id: proposal.recipientId,
    body_digest: createHash("sha256").update(proposal.bodyText).digest("hex"),
  })).digest("hex");
}

export class RlmHostBridge {
  private readonly spawns = new Map<string, { readonly digest: string; readonly promise: Promise<RlmSpawnResolution> }>();
  private readonly spawnRequestsByChildId = new Map<string, string>();
  private readonly deletes = new Map<string, { readonly childId: string; readonly promise: Promise<RlmDeleteResolution> }>();
  private readonly messages = new Map<string, { readonly digest: string; readonly messageId: string; readonly promise: Promise<RlmMessageResolution>; delivered: boolean }>();
  private readonly messageRequestsById = new Map<string, string>();

  constructor(private readonly options: RlmHostBridgeOptions) {
    if (
      options.sessionId.length === 0
      || (options.maxSpawnCount !== undefined
        && (!Number.isSafeInteger(options.maxSpawnCount) || options.maxSpawnCount < 0))
    ) throw new TypeError("RLM bridge is invalid");
  }

  async proposeSpawn(proposal: RlmSpawnProposal): Promise<RlmSpawnResolution> {
    if (
      !OPAQUE_ID.test(proposal.requestId) ||
      !OPAQUE_ID.test(proposal.childId) ||
      !OPAQUE_ID.test(proposal.idempotencyKey) ||
      Buffer.byteLength(proposal.goalText, "utf8") > 1024 * 1024 ||
      !Number.isSafeInteger(proposal.rlmDepth) ||
      proposal.rlmDepth < 0 ||
      !validDigest(proposal.modelSelectorDigest) ||
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
    const priorRequestId = this.spawnRequestsByChildId.get(proposal.childId);
    if (priorRequestId !== undefined && priorRequestId !== proposal.requestId) {
      throw new TypeError("RLM proposal conflicts");
    }
    if (
      this.options.maxSpawnCount !== undefined
      && this.spawnRequestsByChildId.size >= this.options.maxSpawnCount
    ) {
      const promise = Promise.resolve(Object.freeze({ resolution: "rejected" as const, childId: proposal.childId }));
      this.spawns.set(proposal.requestId, { digest, promise });
      this.spawnRequestsByChildId.set(proposal.childId, proposal.requestId);
      return promise;
    }
    const promise = this.admit(proposal);
    this.spawns.set(proposal.requestId, { digest, promise });
    this.spawnRequestsByChildId.set(proposal.childId, proposal.requestId);
    return promise;
  }

  async proposeMessage(proposal: RlmMessageProposal): Promise<RlmMessageResolution> {
    if (
      this.options.admitMessage === undefined
      || !OPAQUE_ID.test(proposal.requestId)
      || !OPAQUE_ID.test(proposal.messageId)
      || !OPAQUE_ID.test(proposal.senderId)
      || !OPAQUE_ID.test(proposal.recipientId)
      || proposal.senderId === proposal.recipientId
      || Buffer.byteLength(proposal.bodyText, "utf8") > 1024 * 1024
    ) throw new TypeError("RLM message is invalid");
    const digest = messageDigest(proposal);
    const existing = this.messages.get(proposal.requestId);
    if (existing !== undefined) {
      if (existing.digest !== digest) throw new TypeError("RLM message conflicts");
      return existing.promise;
    }
    const priorRequestId = this.messageRequestsById.get(proposal.messageId);
    if (priorRequestId !== undefined && priorRequestId !== proposal.requestId) {
      throw new TypeError("RLM message conflicts");
    }
    const promise = this.options.admitMessage(Object.freeze({ ...proposal })).then((resolution) => {
      if (resolution.messageId !== proposal.messageId || !["admitted", "rejected", "uncertain"].includes(resolution.resolution)) throw new TypeError("RLM message admission is invalid");
      return Object.freeze({ ...resolution });
    });
    this.messages.set(proposal.requestId, { digest, messageId: proposal.messageId, promise, delivered: false });
    this.messageRequestsById.set(proposal.messageId, proposal.requestId);
    return promise;
  }

  async proposeDelete(proposal: RlmDeleteProposal): Promise<RlmDeleteResolution> {
    if (this.options.admitDelete === undefined || !OPAQUE_ID.test(proposal.requestId) || !OPAQUE_ID.test(proposal.childId)) throw new TypeError("RLM delete is invalid");
    const existing = this.deletes.get(proposal.requestId);
    if (existing !== undefined) {
      if (existing.childId !== proposal.childId) throw new TypeError("RLM delete conflicts");
      return existing.promise;
    }
    const promise = this.options.admitDelete(Object.freeze({ ...proposal })).then((resolution) => {
      if (resolution.childId !== proposal.childId || !["admitted", "rejected", "uncertain"].includes(resolution.resolution)) throw new TypeError("RLM delete admission is invalid");
      return Object.freeze({ ...resolution });
    });
    this.deletes.set(proposal.requestId, { childId: proposal.childId, promise });
    return promise;
  }

  async recordMessageDelivered(event: RlmMessageDelivery): Promise<void> {
    if (!isRecord(event) || !hasExactKeys(event, ["messageId"]) || !OPAQUE_ID.test(event.messageId)) throw new TypeError("RLM message delivery is invalid");
    const entry = [...this.messages.values()].find((candidate) => candidate.messageId === event.messageId);
    if (entry === undefined) throw new TypeError("RLM message is unknown");
    const resolution = await entry.promise;
    if (resolution.resolution !== "admitted" || resolution.messageId !== event.messageId) throw new TypeError("RLM message is unknown");
    if (this.options.recordMessageDelivered === undefined) throw new TypeError("RLM message is unavailable");
    if (entry.delivered) return;
    await this.options.recordMessageDelivered(Object.freeze({ ...event }));
    entry.delivered = true;
  }

  async recordLifecycle(event: RlmHostLifecycleEvent): Promise<void> {
    if (
      !isRecord(event)
      || !OPAQUE_ID.test(event.childId)
      || (event.type === "rlm.child.started" && !validDigest(event.nativeIdentityDigest))
      || (event.type !== "rlm.child.started" && event.type !== "rlm.child.deleted"
        && (event.type !== "rlm.child.terminal"
          || !["completed", "failed", "cancelled"].includes(event.status)))
    ) {
      throw new TypeError("RLM lifecycle is invalid");
    }
    if (this.options.recordLifecycle === undefined) return;
    await this.options.recordLifecycle(Object.freeze({ ...event }));
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
        if (!isRecord(value) || typeof value.type !== "string") throw new TypeError();
        if (value.type === "rlm.spawn.propose") {
          if (!hasExactKeys(value, ["type", "request_id", "child_id", "idempotency_key", "goal_text", "rlm_depth", "model_selector_digest", "budget"]) || typeof value.request_id !== "string" || typeof value.child_id !== "string" || typeof value.idempotency_key !== "string" || typeof value.goal_text !== "string" || !Number.isSafeInteger(value.rlm_depth) || Number(value.rlm_depth) < 0 || !validDigest(value.model_selector_digest) || !validBudget(value.budget)) throw new TypeError();
          void bridge.proposeSpawn({ requestId: value.request_id, childId: value.child_id, idempotencyKey: value.idempotency_key, goalText: value.goal_text, rlmDepth: Number(value.rlm_depth), modelSelectorDigest: value.model_selector_digest, budget: value.budget }).then((result) => socket.end(`${JSON.stringify(result)}\n`), () => socket.destroy());
        } else if (value.type === "rlm.delete.propose") {
          if (!hasExactKeys(value, ["type", "request_id", "child_id"]) || typeof value.request_id !== "string" || typeof value.child_id !== "string") throw new TypeError();
          void bridge.proposeDelete({ requestId: value.request_id, childId: value.child_id }).then((result) => socket.end(`${JSON.stringify(result)}\n`), () => socket.destroy());
        } else if (value.type === "rlm.message.propose") {
          if (!hasExactKeys(value, ["type", "request_id", "message_id", "sender_id", "recipient_id", "body_text"]) || typeof value.request_id !== "string" || typeof value.message_id !== "string" || typeof value.sender_id !== "string" || typeof value.recipient_id !== "string" || typeof value.body_text !== "string") throw new TypeError();
          void bridge.proposeMessage({ requestId: value.request_id, messageId: value.message_id, senderId: value.sender_id, recipientId: value.recipient_id, bodyText: value.body_text }).then((result) => socket.end(`${JSON.stringify(result)}\n`), () => socket.destroy());
        } else if (value.type === "rlm.message.delivered") {
          if (!hasExactKeys(value, ["type", "message_id"]) || typeof value.message_id !== "string") throw new TypeError();
          void bridge.recordMessageDelivered({ messageId: value.message_id }).then(() => socket.end(`${JSON.stringify({ resolution: "recorded", messageId: value.message_id })}\n`), () => socket.destroy());
        } else if (value.type === "rlm.child.started") {
          if (!hasExactKeys(value, ["type", "child_id", "native_identity_digest"]) || typeof value.child_id !== "string" || !validDigest(value.native_identity_digest)) throw new TypeError();
          void bridge.recordLifecycle({ type: "rlm.child.started", childId: value.child_id, nativeIdentityDigest: value.native_identity_digest }).then(() => socket.end(`${JSON.stringify({ resolution: "recorded", childId: value.child_id })}\n`), () => socket.destroy());
        } else if (value.type === "rlm.child.terminal") {
          if (!hasExactKeys(value, ["type", "child_id", "status"]) || typeof value.child_id !== "string" || typeof value.status !== "string" || !["completed", "failed", "cancelled"].includes(value.status)) throw new TypeError();
          void bridge.recordLifecycle({ type: "rlm.child.terminal", childId: value.child_id, status: value.status as "completed" | "failed" | "cancelled" }).then(() => socket.end(`${JSON.stringify({ resolution: "recorded", childId: value.child_id })}\n`), () => socket.destroy());
        } else {
          throw new TypeError();
        }
        } catch { socket.destroy(); }
        return;
      }
    });
  });
  await new Promise<void>((resolve, reject) => { server.once("error", reject); server.listen(path, resolve); });
  await chmod(path, 0o600);
  return Object.freeze({ close: async () => { await new Promise<void>((resolve) => server.close(() => resolve())); await unlink(path).catch(() => undefined); } });
}
