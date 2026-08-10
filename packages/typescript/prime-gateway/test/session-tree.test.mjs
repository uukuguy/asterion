import assert from "node:assert/strict";
import test from "node:test";

import {
  PrimeSessionTreeError,
  projectPrimeSessionTree,
} from "../dist/src/session-tree.js";

function response(flatNodes, leafId = "entry-g") {
  return {
    success: true,
    command: "get_session_tree",
    data: { flatNodes, leafId },
  };
}

function baseEntry(type, id, parentId) {
  return { type, id, parentId, timestamp: "2026-08-10T00:00:00.000Z" };
}

function usage(totalTokens) {
  return {
    input: 1,
    output: 2,
    cacheRead: 3,
    cacheWrite: 4,
    totalTokens,
    cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 },
  };
}

function validNodes() {
  return [
    {
      entry: {
        ...baseEntry("message", "entry-b", "entry-a"),
        message: {
          role: "assistant",
          content: [{ type: "text", text: "SENTINEL_PRIVATE_OUTPUT" }],
          api: "messages",
          provider: "private-provider",
          model: "private-model",
          usage: usage(10),
          stopReason: "stop",
          timestamp: 1,
        },
      },
      label: "SENTINEL_PRIVATE_LABEL",
      labelTimestamp: "2026-08-10T00:00:00.000Z",
    },
    {
      entry: {
        ...baseEntry("message", "entry-a", null),
        message: {
          role: "user",
          content: "SENTINEL_PRIVATE_INPUT",
          timestamp: 0,
        },
      },
    },
    {
      entry: {
        ...baseEntry("message", "entry-c", "entry-b"),
        message: {
          role: "toolResult",
          toolCallId: "private-call",
          toolName: "private-tool",
          content: [{ type: "text", text: "SENTINEL_PRIVATE_TOOL" }],
          isError: false,
          timestamp: 2,
        },
      },
    },
    {
      entry: {
        ...baseEntry("compaction", "entry-d", "entry-c"),
        summary: "SENTINEL_PRIVATE_SUMMARY",
        firstKeptEntryId: "entry-b",
        tokensBefore: 20,
      },
    },
    {
      entry: {
        ...baseEntry("branch_summary", "entry-e", "entry-d"),
        fromId: "entry-c",
        summary: "SENTINEL_PRIVATE_BRANCH_SUMMARY",
      },
    },
    {
      entry: {
        ...baseEntry("custom", "entry-f", "entry-e"),
        customType: "private-extension",
        data: { secret: "SENTINEL_PRIVATE_CUSTOM" },
      },
    },
    {
      entry: {
        ...baseEntry("model_change", "entry-g", "entry-f"),
        provider: "private-provider",
        modelId: "private-model",
      },
    },
  ];
}

test("session tree projects a sorted closed body-free topology", () => {
  const projected = projectPrimeSessionTree(response(validNodes()));
  assert.deepEqual(projected, {
    nodes: [
      { entry_id: "entry-a", parent_id: null, kind: "input", label_sha256: null, token_count: 0 },
      { entry_id: "entry-b", parent_id: "entry-a", kind: "output", label_sha256: projected.nodes[1].label_sha256, token_count: 10 },
      { entry_id: "entry-c", parent_id: "entry-b", kind: "tool", label_sha256: null, token_count: 0 },
      { entry_id: "entry-d", parent_id: "entry-c", kind: "compaction", label_sha256: null, token_count: 20 },
      { entry_id: "entry-e", parent_id: "entry-d", kind: "summary", label_sha256: null, token_count: 0 },
      { entry_id: "entry-f", parent_id: "entry-e", kind: "custom", label_sha256: null, token_count: 0 },
      { entry_id: "entry-g", parent_id: "entry-f", kind: "system", label_sha256: null, token_count: 0 },
    ],
    leafId: "entry-g",
  });
  assert.match(projected.nodes[1].label_sha256, /^[0-9a-f]{64}$/);
  const encoded = JSON.stringify(projected);
  for (const sentinel of [
    "SENTINEL_PRIVATE_OUTPUT",
    "SENTINEL_PRIVATE_LABEL",
    "SENTINEL_PRIVATE_INPUT",
    "SENTINEL_PRIVATE_TOOL",
    "SENTINEL_PRIVATE_SUMMARY",
    "SENTINEL_PRIVATE_BRANCH_SUMMARY",
    "SENTINEL_PRIVATE_CUSTOM",
    "private-provider",
    "private-model",
  ]) {
    assert.equal(encoded.includes(sentinel), false);
  }
  assert.ok(Object.isFrozen(projected));
  assert.ok(Object.isFrozen(projected.nodes));
  assert.ok(projected.nodes.every(Object.isFrozen));
});

test("session tree sorting follows the shared Unicode scalar contract", () => {
  const projected = projectPrimeSessionTree(response([
    {
      entry: {
        ...baseEntry("message", "entry.1", "entry-1"),
        message: { role: "assistant", content: [], api: "a", provider: "p", model: "m", usage: usage(0), stopReason: "stop", timestamp: 2 },
      },
    },
    {
      entry: {
        ...baseEntry("message", "entry-1", null),
        message: { role: "user", content: "private", timestamp: 1 },
      },
    },
  ], "entry.1"));

  assert.deepEqual(projected.nodes.map(({ entry_id }) => entry_id), [
    "entry-1",
    "entry.1",
  ]);
});

test("session tree covers every pinned Prime metadata entry without exposing values", () => {
  const entries = [
    { ...baseEntry("thinking_level_change", "meta-1", null), thinkingLevel: "private-thinking" },
    { ...baseEntry("service_tier_change", "meta-2", "meta-1"), serviceTier: null },
    {
      ...baseEntry("child_usage_attributed", "meta-3", "meta-2"),
      targetId: "meta-1",
      childUsage: usage(1),
      aggregateUsage: usage(2),
      origin: "direct_user",
    },
    {
      ...baseEntry("custom_message", "meta-4", "meta-3"),
      customType: "private-custom-message",
      content: "SENTINEL_PRIVATE_CUSTOM_MESSAGE",
      details: { secret: "SENTINEL_PRIVATE_DETAILS" },
      display: false,
    },
    { ...baseEntry("label", "meta-5", "meta-4"), targetId: "meta-1", label: "private-label" },
    { ...baseEntry("session_info", "meta-6", "meta-5"), name: "private-name" },
    { ...baseEntry("session_state", "meta-7", "meta-6"), state: { status: "active" } },
    {
      ...baseEntry("agent_status", "meta-8", "meta-7"),
      status: { summary: "SENTINEL_PRIVATE_STATUS", taskState: "completed", basedOnMessageCount: 2 },
    },
    {
      ...baseEntry("git_state", "meta-9", "meta-8"),
      git: { repoUrl: "SENTINEL_PRIVATE_REPO", commit: "private-commit", branch: "private-branch" },
    },
  ];
  const projected = projectPrimeSessionTree(response(
    entries.map((entry) => ({ entry })),
    "meta-9",
  ));

  assert.deepEqual(projected.nodes.map(({ kind }) => kind), [
    "system",
    "system",
    "system",
    "custom",
    "system",
    "system",
    "system",
    "system",
    "system",
  ]);
  assert.equal(JSON.stringify(projected).includes("SENTINEL"), false);
  assert.equal(JSON.stringify(projected).includes("private-"), false);
});

test("session tree rejects malformed identities topology counts and raw drift", () => {
  const cases = [
    response([...validNodes(), validNodes()[0]]),
    response(validNodes().map((node) => node.entry.id === "entry-g"
      ? { ...node, entry: { ...node.entry, parentId: "missing" } }
      : node)),
    response(validNodes().map((node) => node.entry.id === "entry-a"
      ? { ...node, entry: { ...node.entry, parentId: "entry-g" } }
      : node)),
    response(validNodes(), "missing"),
    response(validNodes().map((node) => node.entry.id === "entry-d"
      ? { ...node, entry: { ...node.entry, tokensBefore: -1 } }
      : node)),
    response(validNodes().map((node) => node.entry.id === "entry-g"
      ? { ...node, entry: { ...node.entry, type: "future_entry" } }
      : node)),
    response(validNodes().map((node) => node.entry.id === "entry-g"
      ? { ...node, rawMessage: "SENTINEL_RAW_DRIFT" }
      : node)),
    response(validNodes().map((node) => node.entry.id === "entry-b"
      ? {
          ...node,
          entry: {
            ...baseEntry("service_tier_change", "entry-b", "entry-a"),
            serviceTier: "future-tier",
          },
        }
      : node)),
    response(validNodes().map((node) => node.entry.id === "entry-g"
      ? {
          ...node,
          entry: {
            ...baseEntry("git_state", "entry-g", "entry-f"),
            git: { privatePath: "/SENTINEL" },
          },
        }
      : node)),
    { success: true, command: "get_session_tree", data: { flatNodes: validNodes(), leafId: "entry-g", path: "/private" } },
  ];
  for (const value of cases) {
    assert.throws(() => projectPrimeSessionTree(value), PrimeSessionTreeError);
  }
});

test("session tree admits the exact empty Prime tree", () => {
  assert.deepEqual(projectPrimeSessionTree(response([], null)), {
    nodes: [],
    leafId: null,
  });
});
