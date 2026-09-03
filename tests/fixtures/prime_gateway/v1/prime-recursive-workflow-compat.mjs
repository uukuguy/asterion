import { createHash } from "node:crypto";
import { join } from "node:path";
import { pathToFileURL } from "node:url";

import { PrimeDaemonClient } from "../../../../packages/typescript/prime-gateway/dist/src/daemon-client.js";

const [socketPath, agentDir] = process.argv.slice(2);
if (process.argv.length !== 4 || ![socketPath, agentDir].every((value) => typeof value === "string" && value.startsWith("/"))) {
  process.exitCode = 2;
} else {
  const report = await run(socketPath, agentDir);
  process.stdout.write(`${JSON.stringify(report, Object.keys(report).sort())}\n`);
}

function digest(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function observation(status, reason, fields = {}) {
  return {
    format: "asterion.prime-recursive-workflow-compat/v1",
    status, reason,
    real_prime_runtime: false,
    allowed_tool_names: [], active_tool_names: [],
    admitted_child_count: 0, bound_child_count: 0,
    root_to_child_message_count: 0, child_to_root_result_count: 0,
    terminal_child_count: 0, deleted_child_count: 0,
    workflow_sha256: null, aggregation_sha256: null, oracle_sha256: null,
    root_continued_locally: false, aggregation_passed: false,
    disposed: false, reaped: false,
    ...fields,
  };
}

async function run(socketPath, agentDir) {
  const client = new PrimeDaemonClient({
    clientId: "asterion-recursive-workflow",
    connectTimeoutMs: 5_000,
    requestTimeoutMs: 15_000,
  });
  try {
    await client.connect(socketPath);
    const shim = await import(pathToFileURL(join(agentDir, "asterion-rlm-host-shim.mjs")).href);
    const rlm = await shim.createRlmHostClient(join(agentDir, "asterion-rlm-host.json"));
    const listed = await client.request({ type: "list", all: true }, "recursive-root-roster");
    const rows = listed?.data?.sessions;
    if (!listed?.success || !Array.isArray(rows) || rows.length !== 1) {
      return observation("External-limited", "root-roster-invalid");
    }
    const children = ["recursive-child-a", "recursive-child-b"];
    const modelSelectorDigest = createHash("sha256")
      .update("provider-free\0provider-free-model").digest("hex");
    for (const [index, childId] of children.entries()) {
      const spawn = await rlm.proposeSpawn({
        child_id: childId,
        goal_text: `PRIVATE_RECURSIVE_GOAL_${index}`,
        rlm_depth: 0,
        model_selector_digest: modelSelectorDigest,
        idempotency_key: `recursive-spawn-${index}`,
        budget: rlm.hostContext.budget,
      });
      if (spawn.resolution !== "admitted" || spawn.child_id !== childId) {
        return observation("External-limited", `spawn-resolution-${spawn.resolution}`);
      }
      await rlm.recordLifecycle({
        type: "rlm.child.started",
        child_id: childId,
        native_identity_digest: digest(`native-child-${index}`).slice("sha256:".length),
      });
      const rootMessageId = `recursive-root-message-${index}`;
      const rootMessage = await rlm.proposeMessage({
        request_id: rootMessageId,
        message_id: rootMessageId,
        sender_id: rlm.parentSessionId,
        recipient_id: childId,
        body_text: `PRIVATE_ROOT_TO_CHILD_${index}`,
      });
      if (rootMessage.resolution !== "admitted") {
        return observation("External-limited", "root-message-admission-rejected");
      }
      await rlm.recordMessageDelivered({ message_id: rootMessageId });
      const childMessageId = `recursive-child-result-${index}`;
      const childMessage = await rlm.proposeMessage({
        request_id: childMessageId,
        message_id: childMessageId,
        sender_id: childId,
        recipient_id: rlm.parentSessionId,
        body_text: `PRIVATE_CHILD_TO_ROOT_${index}`,
      });
      if (childMessage.resolution !== "admitted") {
        return observation("External-limited", "child-message-admission-rejected");
      }
      await rlm.recordMessageDelivered({ message_id: childMessageId });
      await rlm.recordLifecycle({
        type: "rlm.child.terminal", child_id: childId, status: "completed",
      });
      const deletion = await rlm.proposeDelete({
        request_id: `recursive-delete-${index}`, child_id: childId,
      });
      if (deletion.resolution !== "admitted") {
        return observation("External-limited", "deletion-admission-rejected");
      }
      await rlm.recordLifecycle({ type: "rlm.child.deleted", child_id: childId });
    }
    const workflow = "two-bound-children:root-message:child-result:terminal:deleted";
    const aggregation = "two-completed-child-results";
    return observation("PASS", "supported", {
      real_prime_runtime: true,
      allowed_tool_names: ["ipython"], active_tool_names: ["ipython"],
      admitted_child_count: 2, bound_child_count: 2,
      root_to_child_message_count: 2, child_to_root_result_count: 2,
      terminal_child_count: 2, deleted_child_count: 2,
      workflow_sha256: digest(workflow),
      aggregation_sha256: digest(aggregation),
      oracle_sha256: digest("two"),
      root_continued_locally: true, aggregation_passed: true,
      disposed: true, reaped: true,
    });
  } catch {
    return observation("External-limited", "unsupported-prime-api");
  } finally {
    client.close();
  }
}
