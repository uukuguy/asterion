function validChildId(value) {
  return typeof value === "string" && /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u.test(value);
}

function canonicalSpawn(options) {
  if (
    typeof options !== "object" ||
    options === null ||
    !validChildId(options.id) ||
    typeof options.prompt !== "string" ||
    !Number.isSafeInteger(options.rlmDepth) ||
    options.rlmDepth < 0 ||
    !isRecord(options.model) ||
    typeof options.model.provider !== "string" ||
    typeof options.model.id !== "string" ||
    !options.model.provider ||
    !options.model.id
  ) {
    throw new TypeError("Prime RLM spawn is invalid");
  }
  return Object.freeze({
    child_id: options.id,
    goal_text: options.prompt,
    rlm_depth: options.rlmDepth,
    model_selector_digest: createHash("sha256").update(options.model.provider).update("\0").update(options.model.id).digest("hex"),
  });
}

function canonicalHostContext(value) {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, ["idempotency_namespace", "budget"]) ||
    !validChildId(value.idempotency_namespace) ||
    !validBudget(value.budget)
  ) {
    throw new TypeError("Prime RLM host context is invalid");
  }
  return Object.freeze({
    idempotency_namespace: value.idempotency_namespace,
    budget: Object.freeze({ ...value.budget }),
  });
}

function idempotencyKey(namespace, childId) {
  return `rlm-${createHash("sha256").update(namespace).update("\0").update(childId).digest("hex").slice(0, 40)}`;
}

function isRecord(value) {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(value, expected) {
  const actual = Object.keys(value).sort();
  const sorted = [...expected].sort();
  return actual.length === sorted.length && actual.every((key, index) => key === sorted[index]);
}

function validBudget(value) {
  return isRecord(value) && hasExactKeys(value, ["controller_tokens", "application_tokens", "child_tokens", "aggregate_tokens", "cost_micros", "deadline_ms"]) && [value.controller_tokens, value.application_tokens, value.child_tokens, value.aggregate_tokens, value.cost_micros].every((item) => Number.isSafeInteger(item) && item >= 0) && Number.isSafeInteger(value.deadline_ms) && value.deadline_ms > 0;
}

function requestId(sessionId, idempotencyKey) {
  return `rlm-${createHash("sha256").update(sessionId).update("\0").update(idempotencyKey).digest("hex").slice(0, 40)}`;
}

function requestResponse(socketPath, discovery, proposal) {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let body = "";
    const timeout = setTimeout(() => socket.destroy(new Error("RLM host request timed out")), 5_000);
    socket.setEncoding("utf8");
    socket.once("connect", () => socket.write(`${JSON.stringify({ protocol: HOST_PROTOCOL, type: "authenticate", token: discovery.token, session_id: discovery.session_id })}\n${JSON.stringify({ type: "rlm.spawn.propose", request_id: requestId(discovery.session_id, proposal.idempotency_key), child_id: proposal.child_id, idempotency_key: proposal.idempotency_key, goal_text: proposal.goal_text, rlm_depth: proposal.rlm_depth, model_selector_digest: proposal.model_selector_digest, budget: proposal.budget })}\n`));
    socket.on("data", (chunk) => { body += chunk; });
    socket.once("error", (error) => { clearTimeout(timeout); reject(error); });
    socket.once("end", () => {
      clearTimeout(timeout);
      try { resolve(JSON.parse(body)); } catch { reject(new Error("RLM host response is invalid")); }
    });
  });
}

function lifecycleResponse(socketPath, discovery, event) {
  return new Promise((resolve, reject) => {
    const socket = createConnection(socketPath);
    let body = "";
    const timeout = setTimeout(() => socket.destroy(new Error("RLM host request timed out")), 5_000);
    socket.setEncoding("utf8");
    socket.once("connect", () => socket.write(`${JSON.stringify({ protocol: HOST_PROTOCOL, type: "authenticate", token: discovery.token, session_id: discovery.session_id })}\n${JSON.stringify(event)}\n`));
    socket.on("data", (chunk) => { body += chunk; });
    socket.once("error", (error) => { clearTimeout(timeout); reject(error); });
    socket.once("end", () => {
      clearTimeout(timeout);
      try { resolve(JSON.parse(body)); } catch { reject(new Error("RLM host response is invalid")); }
    });
  });
}

function messageResponse(socketPath, discovery, frame) {
  return lifecycleResponse(socketPath, discovery, frame);
}

function nativeIdentityDigest(runtime) {
  const session = runtime?.session;
  const identity = session?.sessionId;
  if (typeof identity !== "string" || !identity) throw new Error("Prime RLM native identity is invalid");
  return createHash("sha256").update(identity).digest("hex");
}

function canonicalNativeMessage(payload) {
  if (
    !isRecord(payload) ||
    !validChildId(payload.id) ||
    typeof payload.message !== "string" ||
    Buffer.byteLength(payload.message, "utf8") > 1024 * 1024 ||
    !isRecord(payload.from) ||
    !validChildId(payload.from.activeSessionId) ||
    !isRecord(payload.target) ||
    !validChildId(payload.target.activeSessionId) ||
    payload.from.activeSessionId === payload.target.activeSessionId
  ) {
    throw new Error("Prime RLM message is invalid");
  }
  return Object.freeze({
    request_id: payload.id,
    message_id: payload.id,
    sender_id: payload.from.activeSessionId,
    recipient_id: payload.target.activeSessionId,
    body_text: payload.message,
  });
}

export async function admitNativeRlmMessage(client, payload) {
  if (!client || typeof client.proposeMessage !== "function") {
    throw new TypeError("Prime RLM host shim is invalid");
  }
  const proposal = canonicalNativeMessage(payload);
  const admission = await client.proposeMessage(proposal);
  if (
    !isRecord(admission) ||
    admission.resolution !== "admitted" ||
    admission.message_id !== proposal.message_id
  ) {
    throw new Error("Prime RLM message was not admitted");
  }
}

export async function recordNativeRlmMessageDelivered(client, messageId) {
  if (!client || typeof client.recordMessageDelivered !== "function" || !validChildId(messageId)) {
    throw new TypeError("Prime RLM host shim is invalid");
  }
  await client.recordMessageDelivered(Object.freeze({ message_id: messageId }));
}

export async function createRlmHostClient(discoveryPath) {
  let discovery;
  try { discovery = JSON.parse(await readFile(discoveryPath, "utf8")); } catch { throw new Error("Prime RLM host discovery is unavailable"); }
  if (!isRecord(discovery) || !hasExactKeys(discovery, ["protocol", "socket_path", "token", "session_id", "budget"]) || discovery.protocol !== DISCOVERY_PROTOCOL || typeof discovery.socket_path !== "string" || discovery.socket_path.length === 0 || typeof discovery.session_id !== "string" || !validChildId(discovery.session_id) || typeof discovery.token !== "string" || !/^[0-9a-f]{64}$/u.test(discovery.token) || !validBudget(discovery.budget)) throw new Error("Prime RLM host discovery is invalid");
  const hostContext = canonicalHostContext({
    idempotency_namespace: discovery.session_id,
    budget: discovery.budget,
  });
  return Object.freeze({
    hostContext,
    async proposeSpawn(proposal) {
      if (!isRecord(proposal) || !hasExactKeys(proposal, ["child_id", "goal_text", "rlm_depth", "model_selector_digest", "idempotency_key", "budget"]) || !validChildId(proposal.child_id) || typeof proposal.goal_text !== "string" || !validChildId(proposal.idempotency_key) || !Number.isSafeInteger(proposal.rlm_depth) || proposal.rlm_depth < 0 || typeof proposal.model_selector_digest !== "string" || !/^[0-9a-f]{64}$/u.test(proposal.model_selector_digest) || !validBudget(proposal.budget)) throw new Error("Prime RLM spawn is invalid");
      const response = await requestResponse(discovery.socket_path, discovery, proposal);
      if (!isRecord(response) || !hasExactKeys(response, ["resolution", "childId"]) || response.childId !== proposal.child_id || !["admitted", "rejected", "uncertain"].includes(response.resolution)) throw new Error("Prime RLM host response is invalid");
      return Object.freeze({ resolution: response.resolution, child_id: response.childId });
    },
    async recordLifecycle(event) {
      if (!isRecord(event) || !validChildId(event.child_id) || (
        event.type === "rlm.child.started" &&
        (!hasExactKeys(event, ["type", "child_id", "native_identity_digest"]) || typeof event.native_identity_digest !== "string" || !/^[0-9a-f]{64}$/u.test(event.native_identity_digest))
      ) || (
        event.type === "rlm.child.terminal" &&
        (!hasExactKeys(event, ["type", "child_id", "status"]) || !["completed", "failed", "cancelled"].includes(event.status))
      ) || (event.type !== "rlm.child.started" && event.type !== "rlm.child.terminal")) throw new Error("Prime RLM lifecycle is invalid");
      const response = await lifecycleResponse(discovery.socket_path, discovery, event);
      if (!isRecord(response) || !hasExactKeys(response, ["resolution", "childId"]) || response.resolution !== "recorded" || response.childId !== event.child_id) throw new Error("Prime RLM host response is invalid");
      return Object.freeze({ child_id: response.childId });
    },
    async proposeMessage(proposal) {
      if (!isRecord(proposal) || !hasExactKeys(proposal, ["request_id", "message_id", "sender_id", "recipient_id", "body_text"]) || !validChildId(proposal.request_id) || !validChildId(proposal.message_id) || !validChildId(proposal.sender_id) || !validChildId(proposal.recipient_id) || proposal.sender_id === proposal.recipient_id || typeof proposal.body_text !== "string" || Buffer.byteLength(proposal.body_text, "utf8") > 1024 * 1024) throw new Error("Prime RLM message is invalid");
      const response = await messageResponse(discovery.socket_path, discovery, {
        type: "rlm.message.propose",
        request_id: proposal.request_id,
        message_id: proposal.message_id,
        sender_id: proposal.sender_id,
        recipient_id: proposal.recipient_id,
        body_text: proposal.body_text,
      });
      if (!isRecord(response) || !hasExactKeys(response, ["resolution", "messageId"]) || response.messageId !== proposal.message_id || !["admitted", "rejected", "uncertain"].includes(response.resolution)) throw new Error("Prime RLM host response is invalid");
      return Object.freeze({ resolution: response.resolution, message_id: response.messageId });
    },
    async recordMessageDelivered(event) {
      if (!isRecord(event) || !hasExactKeys(event, ["message_id"]) || !validChildId(event.message_id)) throw new Error("Prime RLM message is invalid");
      const response = await messageResponse(discovery.socket_path, discovery, { type: "rlm.message.delivered", message_id: event.message_id });
      if (!isRecord(response) || !hasExactKeys(response, ["resolution", "messageId"]) || response.resolution !== "recorded" || response.messageId !== event.message_id) throw new Error("Prime RLM host response is invalid");
      return Object.freeze({ message_id: response.messageId });
    },
  });
}

export function wrapSubagentRuntimeHost(delegate, client, hostContext) {
  if (
    typeof delegate !== "object" ||
    delegate === null ||
    typeof delegate.createRlmSubagentRuntime !== "function" ||
    typeof delegate.deleteRlmSubagentRuntime !== "function" ||
    typeof client !== "object" ||
    client === null ||
    typeof client.proposeSpawn !== "function" || typeof client.recordLifecycle !== "function"
  ) {
    throw new TypeError("Prime RLM host shim is invalid");
  }
  const context = canonicalHostContext(hostContext);
  return Object.freeze({
    ...delegate,
    async createRlmSubagentRuntime(options) {
      const spawn = canonicalSpawn(options);
      const admission = await client.proposeSpawn(Object.freeze({
        ...spawn,
        idempotency_key: idempotencyKey(
          context.idempotency_namespace,
          spawn.child_id,
        ),
        budget: context.budget,
      }));
      if (
        typeof admission !== "object" ||
        admission === null ||
        admission.resolution !== "admitted" ||
        admission.child_id !== options.id
      ) {
        throw new Error("Prime RLM child was not admitted");
      }
      const runtime = await delegate.createRlmSubagentRuntime(options);
      await client.recordLifecycle(Object.freeze({ type: "rlm.child.started", child_id: spawn.child_id, native_identity_digest: nativeIdentityDigest(runtime) }));
      return runtime;
    },
    async releaseRlmSubagentRuntime(runtime, options, status) {
      if (typeof delegate.releaseRlmSubagentRuntime !== "function" || !isRecord(options) || !validChildId(options.id)) throw new Error("Prime RLM release is invalid");
      const terminalStatus = status === "done" ? "completed" : status === "error" ? "failed" : status === "cancelled" ? "cancelled" : null;
      if (terminalStatus === null) throw new Error("Prime RLM release is invalid");
      await client.recordLifecycle(Object.freeze({ type: "rlm.child.terminal", child_id: options.id, status: terminalStatus }));
      return delegate.releaseRlmSubagentRuntime(runtime, options, status);
    },
    completeRlmSubagentRuntime(childId, session) {
      if (typeof delegate.completeRlmSubagentRuntime !== "function") return undefined;
      const completed = delegate.completeRlmSubagentRuntime(childId, session);
      if (completed === true && validChildId(childId)) {
        queueMicrotask(() => {
          Promise.resolve()
            .then(() => client.recordLifecycle(Object.freeze({ type: "rlm.child.terminal", child_id: childId, status: "completed" })))
            .catch(() => undefined);
        });
      }
      return completed;
    },
  });
}
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createConnection } from "node:net";

const DISCOVERY_PROTOCOL = "asterion.prime-rlm-host-discovery/v1";
const HOST_PROTOCOL = "asterion.prime-rlm-host/v1";
