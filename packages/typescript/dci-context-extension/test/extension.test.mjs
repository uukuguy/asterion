import assert from "node:assert/strict";
import test from "node:test";

import { FakePi, context, loadExtension, textMessage } from "./helpers.mjs";

test("extension registers closed flags and rejects an unknown startup profile", async () => {
  const extension = await loadExtension();
  const pi = new FakePi({
    "dci-context-profile": "level5",
    "dci-context-contract": extension.PROFILE_CONTRACT_VERSION,
  });
  extension.default(pi);

  assert.deepEqual([...pi.flagDefinitions], [
    ["dci-context-profile", { type: "string", description: "DCI paper context profile" }],
    ["dci-context-contract", { type: "string", description: "DCI context contract version" }],
  ]);
  assert.throws(
    () => pi.handlers.get("session_start")({ type: "session_start", reason: "startup" }, context()),
    /context profile/,
  );
});

test("startup and tool-result hooks emit body-free state and exact truncation", async () => {
  const extension = await loadExtension();
  const pi = new FakePi({
    "dci-context-profile": "level2",
    "dci-context-contract": extension.PROFILE_CONTRACT_VERSION,
  });
  extension.default(pi);
  pi.handlers.get("session_start")({ type: "session_start", reason: "startup" }, context());

  const result = pi.handlers.get("tool_result")(
    {
      type: "tool_result",
      toolName: "read",
      toolCallId: "call-1",
      input: {},
      content: [{ type: "text", text: `SECRET-${"x".repeat(20_000)}` }],
      isError: false,
      details: undefined,
    },
    context(),
  );

  assert.equal(result.content[0].text.length, 20_000);
  assert.equal(result.content[0].text.endsWith(extension.TRUNCATION_MARKER), true);
  assert.equal(pi.entries.some((entry) => entry.customType === "dci-context-state"), true);
  assert.equal(pi.entries.some((entry) => entry.customType === "dci-context-telemetry"), true);
  assert.equal(JSON.stringify(pi.entries).includes("SECRET-"), false);
});

test("context and turn-end hooks retain twelve turns and trigger one compaction", async () => {
  const extension = await loadExtension();
  const pi = new FakePi({
    "dci-context-profile": "level3",
    "dci-context-contract": extension.PROFILE_CONTRACT_VERSION,
  });
  extension.default(pi);
  const ctx = context();
  pi.handlers.get("session_start")({ type: "session_start", reason: "startup" }, ctx);
  pi.handlers.get("tool_result")(
    {
      type: "tool_result",
      toolName: "read",
      toolCallId: "call-pressure",
      input: {},
      content: [{ type: "text", text: "x".repeat(240_001) }],
      isError: false,
      details: undefined,
    },
    ctx,
  );

  const messages = [textMessage("system", "system")];
  for (let turn = 1; turn <= 13; turn += 1) {
    messages.push(textMessage("user", `u-${turn}`));
    messages.push(textMessage("assistant", `a-${turn}`));
  }
  const transformed = pi.handlers.get("context")({ type: "context", messages }, ctx);
  pi.handlers.get("turn_end")({ type: "turn_end", turnIndex: 1 }, ctx);
  pi.handlers.get("turn_end")({ type: "turn_end", turnIndex: 2 }, ctx);

  assert.equal(transformed.messages.filter((message) => message.role === "user").length, 12);
  assert.equal(ctx.compactCalls.length, 1);
});

test("L3 compaction keeps twelve user-led entries with no summary", async () => {
  const extension = await loadExtension();
  const pi = new FakePi({
    "dci-context-profile": "level3",
    "dci-context-contract": extension.PROFILE_CONTRACT_VERSION,
  });
  extension.default(pi);
  pi.handlers.get("session_start")({ type: "session_start", reason: "startup" }, context());
  const branchEntries = [];
  for (let turn = 1; turn <= 13; turn += 1) {
    branchEntries.push({ id: `user-${turn}`, type: "message", message: { role: "user" } });
    branchEntries.push({ id: `assistant-${turn}`, type: "message", message: { role: "assistant" } });
  }

  const result = pi.handlers.get("session_before_compact")(
    {
      reason: "threshold",
      preparation: { firstKeptEntryId: "built-in", tokensBefore: 50_000, settings: { keepRecentTokens: 20_000 } },
      branchEntries,
    },
    context(),
  );

  assert.deepEqual(result, {
    compaction: { summary: "", firstKeptEntryId: "user-2", tokensBefore: 50_000 },
  });
  pi.handlers.get("session_compact")({}, context());
  const completed = pi.entries
    .filter((entry) => entry.customType === "dci-context-telemetry")
    .at(-1);
  assert.equal(completed.data.event, "session_compact");
  assert.equal(completed.data.preservedTurns, 12);
});

test("L4 accepts only a 20000-token preparation and restores matching state", async () => {
  const extension = await loadExtension();
  const restored = {
    schema: "dci.context-state/v2",
    profile: "level4",
    contractVersion: extension.PROFILE_CONTRACT_VERSION,
    state: { ...extension.createPolicyState(), summaryAttempts: 2 },
  };
  const pi = new FakePi({
    "dci-context-profile": "level4",
    "dci-context-contract": extension.PROFILE_CONTRACT_VERSION,
  });
  extension.default(pi);
  const ctx = context([{ type: "custom", customType: "dci-context-state", data: restored }]);
  pi.handlers.get("session_start")({ type: "session_start", reason: "resume" }, ctx);

  assert.throws(
    () =>
      pi.handlers.get("session_before_compact")(
        {
          reason: "threshold",
          preparation: { firstKeptEntryId: "entry", tokensBefore: 50_000, settings: { keepRecentTokens: 19_999 } },
          branchEntries: [],
        },
        ctx,
      ),
    /20000/,
  );
  assert.equal(
    pi.handlers.get("session_before_compact")(
      {
        reason: "threshold",
        preparation: { firstKeptEntryId: "entry", tokensBefore: 50_000, settings: { keepRecentTokens: 20_000 } },
        branchEntries: [],
      },
      ctx,
    ),
    undefined,
  );
  pi.handlers.get("session_compact")({}, ctx);
  assert.equal(pi.entries.at(-2).data.preservedTurns, null);
  assert.equal(pi.entries.at(-2).data.summaryAttempts, 2);
});

test("suppressed L4 keeps L3 compaction without another summary attempt", async () => {
  const extension = await loadExtension();
  const suppressedState = {
    ...extension.createPolicyState(),
    accumulatedOriginalToolCharacters: 240_001,
    summaryAttempts: 3,
    consecutiveSummaryFailures: 3,
    summarySuppressed: true,
  };
  const pi = new FakePi({
    "dci-context-profile": "level4",
    "dci-context-contract": extension.PROFILE_CONTRACT_VERSION,
  });
  extension.default(pi);
  const ctx = context([
    {
      type: "custom",
      customType: "dci-context-state",
      data: {
        schema: "dci.context-state/v2",
        profile: "level4",
        contractVersion: extension.PROFILE_CONTRACT_VERSION,
        state: suppressedState,
      },
    },
  ]);
  pi.handlers.get("session_start")({ type: "session_start", reason: "resume" }, ctx);
  const branchEntries = [];
  for (let turn = 1; turn <= 13; turn += 1) {
    branchEntries.push({ id: `user-${turn}`, type: "message", message: { role: "user" } });
    branchEntries.push({ id: `assistant-${turn}`, type: "message", message: { role: "assistant" } });
  }

  pi.handlers.get("turn_end")({ type: "turn_end", turnIndex: 1 }, ctx);
  const compaction = pi.handlers.get("session_before_compact")(
    {
      reason: "threshold",
      preparation: { firstKeptEntryId: "built-in", tokensBefore: 50_000, settings: { keepRecentTokens: 19_999 } },
      branchEntries,
    },
    ctx,
  );
  ctx.compactCalls[0].onError(new Error("must not count as summary"));

  assert.equal(ctx.compactCalls.length, 1);
  assert.deepEqual(compaction, {
    compaction: { summary: "", firstKeptEntryId: "user-2", tokensBefore: 50_000 },
  });
  assert.equal(pi.entries.at(-1).data.state.summaryAttempts, 3);
  assert.equal(pi.entries.at(-1).data.state.summarySuppressed, true);
});
