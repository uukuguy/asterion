import { createHash } from "node:crypto";

import type { SessionContextTreeNode } from "@dci/agent-runtime";

import type { PrimeDaemonResponse } from "./daemon-wire.js";

const OPAQUE_ID = /^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$/u;
const MAX_TREE_NODES = 100_000;
const MAX_PRIVATE_TEXT_BYTES = 1024 * 1024;

type TreeKind = SessionContextTreeNode["kind"];

export interface PrimeSessionTreeProjection {
  readonly nodes: readonly SessionContextTreeNode[];
  readonly leafId: string | null;
}

export class PrimeSessionTreeError extends Error {
  constructor() {
    super("Prime session tree projection failed");
    this.name = "PrimeSessionTreeError";
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function hasExactKeys(
  value: Record<string, unknown>,
  expected: readonly string[],
): boolean {
  const actual = Object.keys(value).sort();
  const wanted = [...expected].sort();
  return actual.length === wanted.length &&
    actual.every((key, index) => key === wanted[index]);
}

function hasOnlyKeys(
  value: Record<string, unknown>,
  allowed: readonly string[],
): boolean {
  const accepted = new Set(allowed);
  return Object.keys(value).every((key) => accepted.has(key));
}

function validId(value: unknown): value is string {
  return typeof value === "string" && OPAQUE_ID.test(value);
}

function validText(value: unknown): value is string {
  return typeof value === "string" &&
    Buffer.byteLength(value, "utf8") <= MAX_PRIVATE_TEXT_BYTES;
}

function safeCount(value: unknown): value is number {
  return Number.isSafeInteger(value) && Number(value) >= 0;
}

function finiteNonnegative(value: unknown): value is number {
  return typeof value === "number" && Number.isFinite(value) && value >= 0;
}

function validMessageTimestamp(value: unknown): value is number {
  return safeCount(value);
}

function validContent(value: unknown, allowString: boolean): boolean {
  return (allowString && validText(value)) || Array.isArray(value);
}

function usageTokens(value: unknown): number {
  if (
    !isRecord(value) ||
    !hasExactKeys(value, [
      "cacheRead",
      "cacheWrite",
      "cost",
      "input",
      "output",
      "totalTokens",
    ]) ||
    ![
      value.cacheRead,
      value.cacheWrite,
      value.input,
      value.output,
    ].every(finiteNonnegative) ||
    !safeCount(value.totalTokens) ||
    !isRecord(value.cost) ||
    !hasExactKeys(value.cost, [
      "cacheRead",
      "cacheWrite",
      "input",
      "output",
      "total",
    ]) ||
    !Object.values(value.cost).every(finiteNonnegative)
  ) {
    throw new PrimeSessionTreeError();
  }
  return value.totalTokens;
}

function projectMessage(value: unknown): Readonly<{
  kind: TreeKind;
  tokenCount: number;
}> {
  if (!isRecord(value) || typeof value.role !== "string") {
    throw new PrimeSessionTreeError();
  }
  if (value.role === "user") {
    if (
      !hasExactKeys(value, ["content", "role", "timestamp"]) ||
      !validContent(value.content, true) ||
      !validMessageTimestamp(value.timestamp)
    ) {
      throw new PrimeSessionTreeError();
    }
    return Object.freeze({ kind: "input", tokenCount: 0 });
  }
  if (value.role === "assistant") {
    if (
      !hasOnlyKeys(value, [
        "api",
        "content",
        "diagnostics",
        "errorMessage",
        "model",
        "provider",
        "responseId",
        "responseModel",
        "role",
        "stopReason",
        "stopReasonRaw",
        "timestamp",
        "usage",
      ]) ||
      ![
        "api",
        "content",
        "model",
        "provider",
        "stopReason",
        "timestamp",
        "usage",
      ].every((key) => Object.hasOwn(value, key)) ||
      !Array.isArray(value.content) ||
      ![value.api, value.model, value.provider, value.stopReason]
        .every((item) => typeof item === "string") ||
      !validMessageTimestamp(value.timestamp)
    ) {
      throw new PrimeSessionTreeError();
    }
    return Object.freeze({
      kind: "output",
      tokenCount: usageTokens(value.usage),
    });
  }
  if (value.role === "toolResult") {
    if (
      !hasOnlyKeys(value, [
        "content",
        "details",
        "isError",
        "role",
        "timestamp",
        "toolCallId",
        "toolName",
      ]) ||
      !["content", "isError", "timestamp", "toolCallId", "toolName"]
        .every((key) => Object.hasOwn(value, key)) ||
      !Array.isArray(value.content) ||
      typeof value.isError !== "boolean" ||
      !validMessageTimestamp(value.timestamp) ||
      ![value.toolCallId, value.toolName].every((item) => typeof item === "string")
    ) {
      throw new PrimeSessionTreeError();
    }
    return Object.freeze({ kind: "tool", tokenCount: 0 });
  }
  throw new PrimeSessionTreeError();
}

function requiredKeys(
  value: Record<string, unknown>,
  keys: readonly string[],
): boolean {
  return keys.every((key) => Object.hasOwn(value, key));
}

function projectEntry(value: unknown): Readonly<{
  entryId: string;
  parentId: string | null;
  kind: TreeKind;
  tokenCount: number;
}> {
  if (
    !isRecord(value) ||
    !validId(value.id) ||
    (value.parentId !== null && !validId(value.parentId)) ||
    !validText(value.timestamp) ||
    typeof value.type !== "string"
  ) {
    throw new PrimeSessionTreeError();
  }
  const common = ["id", "parentId", "timestamp", "type"];
  let kind: TreeKind;
  let tokenCount = 0;
  if (value.type === "message") {
    if (!hasExactKeys(value, [...common, "message"])) {
      throw new PrimeSessionTreeError();
    }
    ({ kind, tokenCount } = projectMessage(value.message));
  } else if (value.type === "compaction") {
    if (
      !hasOnlyKeys(value, [
        ...common,
        "customInstructions",
        "details",
        "firstKeptEntryId",
        "fromHook",
        "summary",
        "tokensBefore",
      ]) ||
      !requiredKeys(value, ["firstKeptEntryId", "summary", "tokensBefore"]) ||
      !validId(value.firstKeptEntryId) ||
      !validText(value.summary) ||
      !safeCount(value.tokensBefore)
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "compaction";
    tokenCount = value.tokensBefore;
  } else if (value.type === "branch_summary") {
    if (
      !hasOnlyKeys(value, [...common, "details", "fromHook", "fromId", "summary"]) ||
      !requiredKeys(value, ["fromId", "summary"]) ||
      !validId(value.fromId) ||
      !validText(value.summary)
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "summary";
  } else if (value.type === "custom") {
    if (
      !hasOnlyKeys(value, [...common, "customType", "data"]) ||
      !validText(value.customType)
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "custom";
  } else if (value.type === "custom_message") {
    if (
      !hasOnlyKeys(value, [...common, "content", "customType", "details", "display"]) ||
      !requiredKeys(value, ["content", "customType", "display"]) ||
      !validContent(value.content, true) ||
      !validText(value.customType) ||
      typeof value.display !== "boolean"
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "custom";
  } else if (value.type === "child_usage_attributed") {
    if (
      !hasOnlyKeys(value, [...common, "aggregateUsage", "childUsage", "origin", "targetId"]) ||
      !requiredKeys(value, ["aggregateUsage", "childUsage", "targetId"]) ||
      !validId(value.targetId) ||
      (Object.hasOwn(value, "origin") &&
        !["spawn_task", "agent_message", "direct_user"].includes(
          String(value.origin),
        ))
    ) {
      throw new PrimeSessionTreeError();
    }
    usageTokens(value.childUsage);
    usageTokens(value.aggregateUsage);
    kind = "system";
  } else if (value.type === "thinking_level_change") {
    if (!hasExactKeys(value, [...common, "thinkingLevel"]) || !validText(value.thinkingLevel)) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else if (value.type === "service_tier_change") {
    if (
      !hasExactKeys(value, [...common, "serviceTier"]) ||
      ![null, "auto", "default", "flex", "scale", "priority"].includes(
        value.serviceTier as null | string,
      )
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else if (value.type === "model_change") {
    if (
      !hasExactKeys(value, [...common, "modelId", "provider"]) ||
      !validText(value.modelId) ||
      !validText(value.provider)
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else if (value.type === "label") {
    if (
      !hasOnlyKeys(value, [...common, "label", "targetId"]) ||
      !requiredKeys(value, ["targetId"]) ||
      !validId(value.targetId) ||
      (Object.hasOwn(value, "label") && !validText(value.label))
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else if (value.type === "session_info") {
    if (
      !hasOnlyKeys(value, [...common, "name"]) ||
      (Object.hasOwn(value, "name") && !validText(value.name))
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else if (value.type === "session_state") {
    if (
      !hasExactKeys(value, [...common, "state"]) ||
      !isRecord(value.state) ||
      !hasExactKeys(value.state, ["status"]) ||
      !["active", "archived", "crash"].includes(String(value.state.status))
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else if (value.type === "agent_status") {
    if (
      !hasExactKeys(value, [...common, "status"]) ||
      !isRecord(value.status) ||
      !hasOnlyKeys(value.status, ["basedOnMessageCount", "summary", "taskState"]) ||
      !requiredKeys(value.status, ["basedOnMessageCount", "summary"]) ||
      !safeCount(value.status.basedOnMessageCount) ||
      !validText(value.status.summary) ||
      (Object.hasOwn(value.status, "taskState") &&
        !["needs_input", "completed"].includes(String(value.status.taskState)))
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else if (value.type === "git_state") {
    if (
      !hasExactKeys(value, [...common, "git"]) ||
      !isRecord(value.git) ||
      !hasOnlyKeys(value.git, ["repoUrl", "commit", "branch"]) ||
      Object.values(value.git).some((item) => typeof item !== "string")
    ) {
      throw new PrimeSessionTreeError();
    }
    kind = "system";
  } else {
    throw new PrimeSessionTreeError();
  }
  return Object.freeze({
    entryId: value.id,
    parentId: value.parentId,
    kind,
    tokenCount,
  });
}

function sha256(value: string): string {
  return createHash("sha256").update(value, "utf8").digest("hex");
}

function assertTopology(
  nodes: readonly SessionContextTreeNode[],
  leafId: string | null,
): void {
  const parents = new Map(nodes.map((node) => [node.entry_id, node.parent_id]));
  if (parents.size !== nodes.length) {
    throw new PrimeSessionTreeError();
  }
  if (nodes.length === 0) {
    if (leafId !== null) {
      throw new PrimeSessionTreeError();
    }
    return;
  }
  if ([...parents.values()].filter((parent) => parent === null).length !== 1) {
    throw new PrimeSessionTreeError();
  }
  if (leafId !== null && !parents.has(leafId)) {
    throw new PrimeSessionTreeError();
  }
  for (const entryId of parents.keys()) {
    const visited = new Set<string>();
    let current: string | null = entryId;
    while (current !== null) {
      if (visited.has(current) || !parents.has(current)) {
        throw new PrimeSessionTreeError();
      }
      visited.add(current);
      current = parents.get(current)!;
    }
  }
}

export function projectPrimeSessionTree(
  response: PrimeDaemonResponse,
): PrimeSessionTreeProjection {
  try {
    if (
      !isRecord(response) ||
      response.success !== true ||
      response.command !== "get_session_tree" ||
      !isRecord(response.data) ||
      !hasExactKeys(response.data, ["flatNodes", "leafId"]) ||
      !Array.isArray(response.data.flatNodes) ||
      response.data.flatNodes.length > MAX_TREE_NODES ||
      (response.data.leafId !== null && !validId(response.data.leafId))
    ) {
      throw new PrimeSessionTreeError();
    }
    const nodes = response.data.flatNodes.map((flatValue) => {
      if (
        !isRecord(flatValue) ||
        !hasOnlyKeys(flatValue, ["entry", "label", "labelTimestamp"]) ||
        !Object.hasOwn(flatValue, "entry") ||
        (Object.hasOwn(flatValue, "label") && !validText(flatValue.label)) ||
        (Object.hasOwn(flatValue, "labelTimestamp") &&
          !validText(flatValue.labelTimestamp))
      ) {
        throw new PrimeSessionTreeError();
      }
      const entry = projectEntry(flatValue.entry);
      return Object.freeze({
        entry_id: entry.entryId,
        parent_id: entry.parentId,
        kind: entry.kind,
        label_sha256: Object.hasOwn(flatValue, "label")
          ? sha256(flatValue.label as string)
          : null,
        token_count: entry.tokenCount,
      });
    }).sort((left, right) =>
      left.entry_id < right.entry_id
        ? -1
        : left.entry_id > right.entry_id
          ? 1
          : 0
    );
    assertTopology(nodes, response.data.leafId);
    return Object.freeze({
      nodes: Object.freeze(nodes),
      leafId: response.data.leafId,
    });
  } catch (error) {
    if (error instanceof PrimeSessionTreeError) {
      throw error;
    }
    throw new PrimeSessionTreeError();
  }
}
