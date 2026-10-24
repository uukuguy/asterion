const TRUNCATION_MARKER = "\n[tool result truncated]";
const COMPACTION_PLACEHOLDER = "[earlier tool result compacted]";
const FIELDS = [
  "compact_chars",
  "retain_turns",
  "summary_failures",
  "summary_tokens",
  "tool_result_chars",
];

export function parseContextPolicy(value) {
  let payload;
  try {
    payload = JSON.parse(value);
  } catch {
    throw new Error("context policy is invalid");
  }
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new Error("context policy is invalid");
  }
  const keys = Object.keys(payload).sort();
  if (keys.length === 0 || keys.some((key) => !FIELDS.includes(key))) {
    throw new Error("context policy is invalid");
  }
  const policy = {};
  for (const key of FIELDS) {
    if (!Object.hasOwn(payload, key)) continue;
    const item = payload[key];
    if (!Number.isInteger(item) || item <= 0) {
      throw new Error("context policy is invalid");
    }
    policy[key] = item;
  }
  const compact = Object.hasOwn(policy, "compact_chars");
  const retain = Object.hasOwn(policy, "retain_turns");
  const summary = Object.hasOwn(policy, "summary_tokens");
  const failures = Object.hasOwn(policy, "summary_failures");
  if (compact !== retain || summary !== failures || (summary && !compact)) {
    throw new Error("context policy is invalid");
  }
  if (!Object.hasOwn(policy, "tool_result_chars") && !compact) {
    throw new Error("context policy is invalid");
  }
  return policy;
}

export function truncateText(text, cap) {
  if (text.length <= cap) return text;
  if (cap <= TRUNCATION_MARKER.length) return TRUNCATION_MARKER.slice(-cap);
  return text.slice(0, cap - TRUNCATION_MARKER.length) + TRUNCATION_MARKER;
}

function textOf(content) {
  if (typeof content === "string") return content;
  if (!Array.isArray(content)) return "";
  return content
    .filter((item) => item?.type === "text" && typeof item.text === "string")
    .map((item) => item.text)
    .join("");
}

export function truncateToolResult(content, cap) {
  const original = textOf(content);
  if (original.length <= cap) {
    return { content, truncated: false, characters: original.length };
  }
  const text = truncateText(original, cap);
  let emitted = false;
  return {
    content: content.map((item) => {
      if (item?.type !== "text" || typeof item.text !== "string") return item;
      if (emitted) return { ...item, text: "" };
      emitted = true;
      return { ...item, text };
    }),
    truncated: true,
    characters: original.length,
  };
}

function firstKeptEntryId(entries, retainTurns) {
  const users = entries.filter(
    (entry) => entry.type === "message" && entry.message?.role === "user" && typeof entry.id === "string",
  );
  return users.length > retainTurns ? users[users.length - retainTurns].id : undefined;
}

function placeholderSummary(entries, firstKept) {
  if (firstKept === undefined) return "";
  const first = entries.findIndex((entry) => entry.id === firstKept);
  if (first <= 0) return "";
  return entries.slice(0, first).map((entry) => {
    const role = entry.message?.role ?? entry.type;
    if (role === "toolResult") return `toolResult: ${COMPACTION_PLACEHOLDER}`;
    return `${role}: ${textOf(entry.message?.content) || ""}`;
  }).join("\n");
}

export default function contextPolicyExtension(pi) {
  pi.registerFlag("context-policy", {
    type: "string",
    description: "Application context bounds",
  });
  let policy;
  let accumulated = 0;
  let pending = false;
  let summaryFailures = 0;
  let summarySuppressed = false;

  pi.on("session_start", () => {
    policy = parseContextPolicy(pi.getFlag("context-policy"));
  });

  pi.on("tool_result", (event) => {
    if (policy === undefined) throw new Error("context policy is unavailable");
    const content = Array.isArray(event.content) ? event.content : [];
    const characters = textOf(content).length;
    accumulated += characters;
    const cap = policy.tool_result_chars;
    if (cap === undefined) return undefined;
    const transformed = truncateToolResult(content, cap);
    return transformed.truncated ? { content: transformed.content } : undefined;
  });

  pi.on("turn_end", (_event, context) => {
    if (policy === undefined) throw new Error("context policy is unavailable");
    if (policy.compact_chars === undefined || pending || accumulated <= policy.compact_chars) {
      return;
    }
    pending = true;
    context.compact({
      onComplete: () => {
        pending = false;
        accumulated = 0;
        summaryFailures = 0;
        summarySuppressed = false;
      },
      onError: () => {
        pending = false;
        if (policy.summary_failures !== undefined) {
          summaryFailures += 1;
          summarySuppressed = summaryFailures >= policy.summary_failures;
        }
      },
    });
  });

  pi.on("session_before_compact", (event) => {
    if (policy === undefined) throw new Error("context policy is unavailable");
    if (policy.retain_turns === undefined) return undefined;
    const entries = event.branchEntries;
    const firstKept = firstKeptEntryId(entries, policy.retain_turns) ?? event.preparation?.firstKeptEntryId;
    if (policy.summary_tokens !== undefined && !summarySuppressed) return undefined;
    return {
      compaction: {
        summary: placeholderSummary(entries, firstKept),
        firstKeptEntryId: firstKept,
        tokensBefore: event.preparation?.tokensBefore,
      },
    };
  });
}
