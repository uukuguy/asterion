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

test("tool content truncates text while preserving images", async () => {
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
    result.content.filter((item) => item.type === "text").reduce((total, item) => total + item.text.length, 0),
    20,
  );
});

test("L3 preserves conversational structure and replaces old tool-result bodies", async () => {
  const { createPolicyState, profileDefinition, transformContext } = await loadExtension();
  const messages = [textMessage("system", "system")];
  for (let turn = 1; turn <= 13; turn += 1) {
    messages.push(textMessage("user", `user-${turn}`));
    messages.push(textMessage("assistant", `assistant-${turn}`));
    messages.push(textMessage("toolResult", `tool-${turn}`));
  }
  const transformed = transformContext(messages, profileDefinition("level3"), {
    ...createPolicyState(), accumulatedOriginalToolCharacters: 240_001,
  });
  assert.equal(transformed.length, messages.length);
  assert.equal(transformed.filter((message) => message.role === "user").length, 13);
  assert.equal(transformed.filter((message) => message.role === "assistant").length, 13);
  assert.equal(transformed[0].role, "system");
  assert.equal(transformed.some((message) => message.content?.[0]?.text === "user-1"), true);
  assert.equal(transformed.some((message) => message.content?.[0]?.text === "user-2"), true);
  assert.equal(transformed.find((message) => message.role === "toolResult").content[0].text, "[DCI tool result compacted]");
  assert.equal(transformed.at(-1).content[0].text, "tool-13");
});

test("L0-L2 expose exact cap and no-compaction boundaries", async () => {
  const { createPolicyState, needsCompaction, profileDefinition, truncateToolResultContent } = await loadExtension();
  for (const [name, length, expectedCap] of [["level0", 50_001, null], ["level1", 50_001, 50_000], ["level2", 20_001, 20_000]]) {
    const profile = profileDefinition(name);
    assert.equal(profile.compaction_character_trigger, null);
    assert.equal(needsCompaction(profile, { ...createPolicyState(), accumulatedOriginalToolCharacters: 240_001 }), false);
    if (expectedCap !== null) assert.equal(
      truncateToolResultContent([{ type: "text", text: "x".repeat(length) }], expectedCap).content[0].text.length,
      expectedCap,
    );
  }
});

test("compaction and L4 post-compaction summary thresholds are strict", async () => {
  const { createPolicyState, estimatePostCompactionTokens, needsCompaction, needsPostCompactionSummary, planCompaction, profileDefinition, recordSummaryResult } = await loadExtension();
  const level4 = profileDefinition("level4");
  assert.equal(needsCompaction(level4, { ...createPolicyState(), accumulatedOriginalToolCharacters: 240_000 }), false);
  assert.equal(needsCompaction(level4, { ...createPolicyState(), accumulatedOriginalToolCharacters: 240_001 }), true);
  assert.equal(planCompaction(level4, { ...createPolicyState(), accumulatedOriginalToolCharacters: 240_000 }), false);
  assert.equal(planCompaction(level4, { ...createPolicyState(), accumulatedOriginalToolCharacters: 240_001 }), true);
  assert.equal(needsPostCompactionSummary(level4, 20_000), false);
  assert.equal(needsPostCompactionSummary(level4, 20_001), true);
  assert.equal(estimatePostCompactionTokens({ settings: { keepRecentTokens: 20_000 }, turnPrefixMessages: [] }), 20_000);
  assert.equal(
    estimatePostCompactionTokens({
      settings: { keepRecentTokens: 20_000 },
      turnPrefixMessages: [{ role: "user", content: "12345" }],
    }),
    20_002,
  );
  let state = createPolicyState();
  state = recordSummaryResult(level4, state, false);
  state = recordSummaryResult(level4, state, false);
  state = recordSummaryResult(level4, state, false);
  assert.equal(state.summarySuppressed, true);
  assert.equal(planCompaction(level4, { ...state, accumulatedOriginalToolCharacters: 240_001 }), true);
  state = recordSummaryResult(level4, state, true);
  assert.equal(state.consecutiveSummaryFailures, 0);
  assert.equal(state.summarySuppressed, false);
});
