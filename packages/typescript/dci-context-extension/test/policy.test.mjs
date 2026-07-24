import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

import { loadExtension, textMessage } from "./helpers.mjs";

const contractUrl = new URL(
  "../../../../src/asterion/dci/resources/context-profiles.json",
  import.meta.url,
);

test("profile definitions match the canonical Python resource", async () => {
  const extension = await loadExtension();
  const contract = JSON.parse(readFileSync(contractUrl, "utf8"));

  assert.equal(extension.PROFILE_CONTRACT_VERSION, contract.schema);
  assert.deepEqual(extension.PROFILE_DEFINITIONS, contract.profiles);
});

test("tool text truncation includes the marker inside the exact cap", async () => {
  const { TRUNCATION_MARKER, truncateText } = await loadExtension();

  assert.equal(truncateText("a".repeat(20_000), 20_000).length, 20_000);
  const truncated = truncateText("a".repeat(20_001), 20_000);
  assert.equal(truncated.length, 20_000);
  assert.equal(truncated.endsWith(TRUNCATION_MARKER), true);
});

test("tool content truncates across text blocks without removing images", async () => {
  const { truncateToolResultContent } = await loadExtension();
  const image = { type: "image", data: "SECRET-IMAGE" };

  const result = truncateToolResultContent(
    [{ type: "text", text: "a".repeat(12) }, image, { type: "text", text: "b".repeat(12) }],
    20,
  );

  assert.equal(result.originalCharacters, 24);
  assert.equal(result.truncated, true);
  assert.equal(result.content.includes(image), true);
  assert.equal(
    result.content.filter((item) => item.type === "text").reduce((n, item) => n + item.text.length, 0),
    20,
  );
});

test("L3 pressure retains system context and the latest twelve complete turns", async () => {
  const { createPolicyState, profileDefinition, transformContext } = await loadExtension();
  const messages = [textMessage("system", "system")];
  for (let turn = 1; turn <= 13; turn += 1) {
    messages.push(textMessage("user", `user-${turn}`));
    messages.push(textMessage("assistant", `assistant-${turn}`));
    messages.push(textMessage("toolResult", `tool-${turn}`, { toolCallId: `call-${turn}` }));
  }
  const state = {
    ...createPolicyState(),
    accumulatedOriginalToolCharacters: 240_001,
  };

  const transformed = transformContext(messages, profileDefinition("level3"), state);
  const retainedUsers = transformed
    .filter((message) => message.role === "user")
    .map((message) => message.content[0].text);

  assert.equal(transformed[0].role, "system");
  assert.equal(retainedUsers.includes("user-1"), false);
  assert.equal(retainedUsers.includes("user-2"), true);
  assert.equal(retainedUsers.length, 12);
});

test("L3 pressure is strict and L4 suppresses summaries after three failures", async () => {
  const { createPolicyState, planCompaction, profileDefinition, recordSummaryResult } =
    await loadExtension();
  const profile = profileDefinition("level4");
  const boundary = {
    ...createPolicyState(),
    accumulatedOriginalToolCharacters: 240_000,
  };

  assert.equal(planCompaction(profile, boundary), false);
  let state = { ...boundary, accumulatedOriginalToolCharacters: 240_001 };
  assert.equal(planCompaction(profile, state), true);
  state = recordSummaryResult(profile, state, false);
  state = recordSummaryResult(profile, state, false);
  state = recordSummaryResult(profile, state, false);
  assert.equal(state.consecutiveSummaryFailures, 3);
  assert.equal(state.summarySuppressed, true);
  assert.equal(planCompaction(profile, state), true);
  state = recordSummaryResult(profile, state, true);
  assert.equal(state.consecutiveSummaryFailures, 0);
  assert.equal(state.summarySuppressed, false);
});
