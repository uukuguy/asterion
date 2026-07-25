import assert from "node:assert/strict";
import test from "node:test";

import { FakePi, context, loadExtension, textMessage } from "./helpers.mjs";

function flags(extension, profile) {
  return { "dci-context-profile": profile, "dci-context-contract": extension.PROFILE_CONTRACT_VERSION };
}

function entries() {
  const result = [];
  for (let turn = 1; turn <= 13; turn += 1) {
    result.push({
      id: `user-${turn}`,
      type: "message",
      message: turn === 1
        ? { role: "user", content: "STRING-USER-CONTENT" }
        : textMessage("user", `user-${turn}`),
    });
    result.push({ id: `assistant-${turn}`, type: "message", message: textMessage("assistant", `assistant-${turn}`) });
    result.push({ id: `tool-${turn}`, type: "message", message: textMessage("toolResult", turn === 1 ? "SECRET-TOOL-BODY" : `tool-${turn}`) });
  }
  return result;
}

function start(pi, ctx) {
  pi.handlers.get("session_start")({ type: "session_start", reason: "startup" }, ctx);
}

test("extension registers closed flags", async () => {
  const extension = await loadExtension();
  const pi = new FakePi(flags(extension, "level5"));
  extension.default(pi);
  assert.deepEqual([...pi.flagDefinitions], [
    ["dci-context-profile", { type: "string", description: "DCI paper context profile" }],
    ["dci-context-contract", { type: "string", description: "DCI context contract version" }],
  ]);
  assert.throws(() => start(pi, context()), /context profile/);
});

test("tool telemetry is body-free", async () => {
  const extension = await loadExtension();
  const pi = new FakePi(flags(extension, "level2"));
  const ctx = context();
  extension.default(pi); start(pi, ctx);
  const result = pi.handlers.get("tool_result")({ content: [{ type: "text", text: `SECRET-${"x".repeat(20_000)}` }] }, ctx);
  assert.equal(result.content[0].text.length, 20_000);
  assert.equal(result.content[0].text.endsWith(extension.TRUNCATION_MARKER), true);
  assert.equal(pi.entries.some((entry) => entry.customType === "dci-context-state"), true);
  assert.equal(pi.entries.some((entry) => entry.customType === "dci-context-telemetry"), true);
  assert.equal(JSON.stringify(pi.entries).includes("SECRET-"), false);
});

test("L0-L2 hooks enforce exact caps without requesting compaction", async () => {
  const extension = await loadExtension();
  for (const [profile, inputLength, expected] of [["level0", 50_001, null], ["level1", 50_001, 50_000], ["level2", 20_001, 20_000]]) {
    const pi = new FakePi(flags(extension, profile)); const ctx = context(); extension.default(pi); start(pi, ctx);
    const result = pi.handlers.get("tool_result")({ content: [{ type: "text", text: "x".repeat(inputLength) }] }, ctx);
    assert.equal(ctx.compactCalls.length, 0);
    if (expected === null) assert.equal(result, undefined); else assert.equal(result.content[0].text.length, expected);
  }
});

test("L3 requests one compaction after pressure", async () => {
  const extension = await loadExtension(); const pi = new FakePi(flags(extension, "level3")); const ctx = context(); extension.default(pi); start(pi, ctx);
  pi.handlers.get("tool_result")({ content: [{ type: "text", text: "x".repeat(240_001) }] }, ctx);
  const messages = [textMessage("system", "system")];
  for (let turn = 1; turn <= 13; turn += 1) {
    messages.push(textMessage("user", `u-${turn}`));
    messages.push(textMessage("assistant", `a-${turn}`));
  }
  const transformed = pi.handlers.get("context")({ messages }, ctx);
  pi.handlers.get("turn_end")({}, ctx); pi.handlers.get("turn_end")({}, ctx);
  assert.equal(transformed.messages.filter((message) => message.role === "user").length, 13);
  assert.equal(ctx.compactCalls.length, 1);
});

test("L3 deterministic summary preserves conversation and redacts tool bodies", async () => {
  const extension = await loadExtension(); const pi = new FakePi(flags(extension, "level3")); const ctx = context(); extension.default(pi); start(pi, ctx);
  const result = pi.handlers.get("session_before_compact")({ preparation: { firstKeptEntryId: "built-in", tokensBefore: 50_000 }, branchEntries: entries() }, ctx);
  assert.equal(result.compaction.firstKeptEntryId, "user-2");
  assert.match(result.compaction.summary, /STRING-USER-CONTENT/); assert.match(result.compaction.summary, /assistant-1/);
  assert.match(result.compaction.summary, /\[DCI tool result compacted\]/); assert.doesNotMatch(result.compaction.summary, /SECRET-TOOL-BODY/);
  pi.handlers.get("session_compact")({}, ctx);
  const completed = pi.entries.filter((entry) => entry.customType === "dci-context-telemetry").at(-1);
  assert.equal(completed.data.event, "session_compact");
  assert.equal(completed.data.preservedTurns, 12);
});

test("L4 rejects a non-20000 preparation boundary", async () => {
  const extension = await loadExtension();
  const restored = {
    schema: "dci.context-state/v2", profile: "level4", contractVersion: extension.PROFILE_CONTRACT_VERSION,
    state: { ...extension.createPolicyState(), summaryAttempts: 2 },
  };
  const pi = new FakePi(flags(extension, "level4"));
  const ctx = context([{ type: "custom", customType: "dci-context-state", data: restored }]);
  extension.default(pi); pi.handlers.get("session_start")({ type: "session_start", reason: "resume" }, ctx);
  assert.throws(() => pi.handlers.get("session_before_compact")({ preparation: { settings: { keepRecentTokens: 19_999 } }, branchEntries: [] }, ctx), /20000/);
  const fallback = pi.handlers.get("session_before_compact")({
    preparation: { firstKeptEntryId: "entry", tokensBefore: 50_000, settings: { keepRecentTokens: 20_000 }, turnPrefixMessages: [] },
    branchEntries: [],
  }, ctx);
  assert.equal(fallback.compaction.firstKeptEntryId, "entry");
  pi.handlers.get("session_compact")({}, ctx);
  assert.equal(pi.entries.at(-2).data.preservedTurns, null);
  assert.equal(pi.entries.at(-2).data.summaryAttempts, 2);
});

test("L4 uses deterministic compaction at derived post pressure 20000", async () => {
  const extension = await loadExtension(); const pi = new FakePi(flags(extension, "level4")); const ctx = context(); extension.default(pi); start(pi, ctx);
  pi.handlers.get("tool_result")({ content: [{ type: "text", text: "x".repeat(240_001) }] }, ctx); pi.handlers.get("turn_end")({}, ctx);
  const result = pi.handlers.get("session_before_compact")({ preparation: { firstKeptEntryId: "built-in", tokensBefore: 50_000, settings: { keepRecentTokens: 20_000 }, turnPrefixMessages: [] }, branchEntries: entries() }, ctx);
  assert.match(result.compaction.summary, /STRING-USER-CONTENT/); assert.doesNotMatch(result.compaction.summary, /SECRET-TOOL-BODY/);
  ctx.compactCalls[0].onError(new Error("fallback"));
  assert.equal(pi.entries.at(-1).data.state.summaryAttempts, 0);
});

test("L4 permits built-in summary only when derived pressure exceeds 20000", async () => {
  const extension = await loadExtension(); const pi = new FakePi(flags(extension, "level4")); const ctx = context(); extension.default(pi); start(pi, ctx);
  pi.handlers.get("tool_result")({ content: [{ type: "text", text: "x".repeat(240_001) }] }, ctx); pi.handlers.get("turn_end")({}, ctx);
  assert.equal(pi.handlers.get("session_before_compact")({ preparation: { firstKeptEntryId: "built-in", tokensBefore: 50_000, settings: { keepRecentTokens: 20_000 }, turnPrefixMessages: [textMessage("assistant", "xxxx")] }, branchEntries: entries() }, ctx), undefined);
});

test("L4 suppresses summary attempts after three failures", async () => {
  const extension = await loadExtension(); const pi = new FakePi(flags(extension, "level4")); const ctx = context(); extension.default(pi); start(pi, ctx);
  pi.handlers.get("tool_result")({ content: [{ type: "text", text: "x".repeat(240_001) }] }, ctx);
  const preparation = { firstKeptEntryId: "built-in", tokensBefore: 50_000, settings: { keepRecentTokens: 20_000 }, turnPrefixMessages: [textMessage("assistant", "xxxx")] };
  for (let attempt = 0; attempt < 3; attempt += 1) { pi.handlers.get("turn_end")({}, ctx); pi.handlers.get("session_before_compact")({ preparation, branchEntries: entries() }, ctx); ctx.compactCalls.at(-1).onError(new Error("summary")); }
  pi.handlers.get("turn_end")({}, ctx);
  const fallback = pi.handlers.get("session_before_compact")({ preparation: { ...preparation, turnPrefixMessages: [] }, branchEntries: entries() }, ctx);
  assert.match(fallback.compaction.summary, /\[DCI tool result compacted\]/);
  ctx.compactCalls.at(-1).onError(new Error("fallback"));
  assert.equal(pi.entries.at(-1).data.state.summaryAttempts, 3);
  assert.equal(pi.entries.at(-1).data.state.summarySuppressed, true);
});

test("resumed suppressed L4 state keeps deterministic compaction without another summary attempt", async () => {
  const extension = await loadExtension();
  const suppressedState = {
    ...extension.createPolicyState(),
    accumulatedOriginalToolCharacters: 240_001,
    summaryAttempts: 3,
    consecutiveSummaryFailures: 3,
    summarySuppressed: true,
  };
  const pi = new FakePi(flags(extension, "level4"));
  const ctx = context([{
    type: "custom", customType: "dci-context-state",
    data: { schema: "dci.context-state/v2", profile: "level4", contractVersion: extension.PROFILE_CONTRACT_VERSION, state: suppressedState },
  }]);
  extension.default(pi);
  pi.handlers.get("session_start")({ type: "session_start", reason: "resume" }, ctx);
  pi.handlers.get("turn_end")({}, ctx);
  const compaction = pi.handlers.get("session_before_compact")({
    preparation: { firstKeptEntryId: "built-in", tokensBefore: 50_000, settings: { keepRecentTokens: 20_000 }, turnPrefixMessages: [] },
    branchEntries: entries(),
  }, ctx);
  ctx.compactCalls[0].onError(new Error("must not count as summary"));

  assert.equal(ctx.compactCalls.length, 1);
  assert.match(compaction.compaction.summary, /\[DCI tool result compacted\]/);
  assert.equal(pi.entries.at(-1).data.state.summaryAttempts, 3);
  assert.equal(pi.entries.at(-1).data.state.summarySuppressed, true);
});
