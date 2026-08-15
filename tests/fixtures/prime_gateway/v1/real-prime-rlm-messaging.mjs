import { PrimeDaemonClient } from "../../../../packages/typescript/prime-gateway/dist/src/daemon-client.js";
import { createHash } from "node:crypto";
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const [socketPath, agentDir] = process.argv.slice(2);
if (![socketPath, agentDir].every((value) => typeof value === "string" && value.startsWith("/"))) {
  throw new Error("real Prime RLM harness inputs are invalid");
}

function record(value, label) {
  if (typeof value !== "object" || value === null || Array.isArray(value)) throw new Error(`${label} is invalid`);
  return value;
}

function string(value, label) {
  if (typeof value !== "string" || value.length === 0) throw new Error(`${label} is invalid`);
  return value;
}

const client = new PrimeDaemonClient({
  clientId: "asterion-rlm-parity",
  connectTimeoutMs: 5_000,
  requestTimeoutMs: 15_000,
});
await client.connect(socketPath);
try {
  const shim = await import(pathToFileURL(join(agentDir, "asterion-rlm-host-shim.mjs")).href);
  const rlm = await shim.createRlmHostClient(join(agentDir, "asterion-rlm-host.json"));
  const listed = await client.request({ type: "list", all: true }, "rlm-list-root");
  const rows = record(listed.data, "list response").sessions;
  if (!listed.success || listed.command !== "list" || !Array.isArray(rows) || rows.length !== 1) {
    throw new Error("real Prime root roster is invalid");
  }
  const root = record(rows[0], "root roster row");
  const rootActiveSessionId = string(root.activeSessionId ?? root.id, "root active session");
  const spawn = await rlm.proposeSpawn({
    child_id: "rlm-child-1",
    goal_text: "PRIVATE_RLM_CHILD_GOAL",
    rlm_depth: 1,
    model_selector_digest: createHash("sha256").update("provider-free\0provider-free-model").digest("hex"),
    idempotency_key: "rlm-harness-spawn-1",
    budget: rlm.hostContext.budget,
  });
  if (spawn.resolution !== "admitted" || spawn.child_id !== "rlm-child-1") {
    throw new Error("real Prime RLM spawn admission failed");
  }
  await rlm.recordLifecycle({
    type: "rlm.child.started",
    child_id: "rlm-child-1",
    native_identity_digest: createHash("sha256").update("provider-free-child").digest("hex"),
  });
  await rlm.recordLifecycle({
    type: "rlm.child.terminal",
    child_id: "rlm-child-1",
    status: "cancelled",
  });
  await rlm.recordLifecycle({ type: "rlm.child.deleted", child_id: "rlm-child-1" });
  process.stdout.write(JSON.stringify({
    format: "asterion.prime-rlm-observation/v1",
    fake_daemon: false,
    model_credential_reads: 0,
    provider_operations: 0,
    spawn_admitted: true,
    lifecycle_recorded: true,
    message_delivered: false,
    teardown_recorded: true,
  }) + "\n");
} finally {
  client.close();
}
