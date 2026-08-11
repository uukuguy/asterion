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
    options.rlmDepth < 0
  ) {
    throw new TypeError("Prime RLM spawn is invalid");
  }
  return Object.freeze({
    child_id: options.id,
    goal_text: options.prompt,
    rlm_depth: options.rlmDepth,
  });
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
    socket.once("connect", () => socket.write(`${JSON.stringify({ protocol: HOST_PROTOCOL, type: "authenticate", token: discovery.token, session_id: discovery.session_id })}\n${JSON.stringify({ type: "rlm.spawn.propose", request_id: requestId(discovery.session_id, proposal.idempotency_key), child_id: proposal.child_id, idempotency_key: proposal.idempotency_key, goal_text: proposal.goal_text, budget: proposal.budget })}\n`));
    socket.on("data", (chunk) => { body += chunk; });
    socket.once("error", (error) => { clearTimeout(timeout); reject(error); });
    socket.once("end", () => {
      clearTimeout(timeout);
      try { resolve(JSON.parse(body)); } catch { reject(new Error("RLM host response is invalid")); }
    });
  });
}

export async function createRlmHostClient(discoveryPath) {
  let discovery;
  try { discovery = JSON.parse(await readFile(discoveryPath, "utf8")); } catch { throw new Error("Prime RLM host discovery is unavailable"); }
  if (!isRecord(discovery) || !hasExactKeys(discovery, ["protocol", "socket_path", "token", "session_id"]) || discovery.protocol !== DISCOVERY_PROTOCOL || typeof discovery.socket_path !== "string" || discovery.socket_path.length === 0 || typeof discovery.session_id !== "string" || !validChildId(discovery.session_id) || typeof discovery.token !== "string" || !/^[0-9a-f]{64}$/u.test(discovery.token)) throw new Error("Prime RLM host discovery is invalid");
  return Object.freeze({
    async proposeSpawn(proposal) {
      if (!isRecord(proposal) || !hasExactKeys(proposal, ["child_id", "goal_text", "rlm_depth", "idempotency_key", "budget"]) || !validChildId(proposal.child_id) || typeof proposal.goal_text !== "string" || !validChildId(proposal.idempotency_key) || !Number.isSafeInteger(proposal.rlm_depth) || proposal.rlm_depth < 0 || !validBudget(proposal.budget)) throw new Error("Prime RLM spawn is invalid");
      const response = await requestResponse(discovery.socket_path, discovery, proposal);
      if (!isRecord(response) || !hasExactKeys(response, ["resolution", "childId"]) || response.childId !== proposal.child_id || !["admitted", "rejected", "uncertain"].includes(response.resolution)) throw new Error("Prime RLM host response is invalid");
      return Object.freeze({ resolution: response.resolution, child_id: response.childId });
    },
  });
}

export function wrapSubagentRuntimeHost(delegate, client) {
  if (
    typeof delegate !== "object" ||
    delegate === null ||
    typeof delegate.createRlmSubagentRuntime !== "function" ||
    typeof delegate.deleteRlmSubagentRuntime !== "function" ||
    typeof client !== "object" ||
    client === null ||
    typeof client.proposeSpawn !== "function"
  ) {
    throw new TypeError("Prime RLM host shim is invalid");
  }
  return Object.freeze({
    ...delegate,
    async createRlmSubagentRuntime(options) {
      const admission = await client.proposeSpawn(canonicalSpawn(options));
      if (
        typeof admission !== "object" ||
        admission === null ||
        admission.resolution !== "admitted" ||
        admission.child_id !== options.id
      ) {
        throw new Error("Prime RLM child was not admitted");
      }
      return delegate.createRlmSubagentRuntime(options);
    },
  });
}
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import { createConnection } from "node:net";

const DISCOVERY_PROTOCOL = "asterion.prime-rlm-host-discovery/v1";
const HOST_PROTOCOL = "asterion.prime-rlm-host/v1";
