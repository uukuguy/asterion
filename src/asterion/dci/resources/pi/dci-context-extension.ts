export const PROFILE_CONTRACT_VERSION = "dci.context-profile/v1";
export const EXTENSION_VERSION = "0.2.0";
export const TRUNCATION_MARKER = "\n[DCI tool result truncated]";

export const PROFILE_DEFINITIONS = {
  level0: {
    profile: "level0",
    contract_version: PROFILE_CONTRACT_VERSION,
    tool_result_character_cap: null,
    compaction_character_trigger: null,
    retained_turns: null,
    summary_recent_token_target: null,
    summary_failure_limit: null,
  },
  level1: {
    profile: "level1",
    contract_version: PROFILE_CONTRACT_VERSION,
    tool_result_character_cap: 50_000,
    compaction_character_trigger: null,
    retained_turns: null,
    summary_recent_token_target: null,
    summary_failure_limit: null,
  },
  level2: {
    profile: "level2",
    contract_version: PROFILE_CONTRACT_VERSION,
    tool_result_character_cap: 20_000,
    compaction_character_trigger: null,
    retained_turns: null,
    summary_recent_token_target: null,
    summary_failure_limit: null,
  },
  level3: {
    profile: "level3",
    contract_version: PROFILE_CONTRACT_VERSION,
    tool_result_character_cap: 20_000,
    compaction_character_trigger: 240_000,
    retained_turns: 12,
    summary_recent_token_target: null,
    summary_failure_limit: null,
  },
  level4: {
    profile: "level4",
    contract_version: PROFILE_CONTRACT_VERSION,
    tool_result_character_cap: 20_000,
    compaction_character_trigger: 240_000,
    retained_turns: 12,
    summary_recent_token_target: 20_000,
    summary_failure_limit: 3,
  },
} as const;

export type ProfileName = keyof typeof PROFILE_DEFINITIONS;
export type ProfileDefinition = (typeof PROFILE_DEFINITIONS)[ProfileName];

interface TextContent {
  type: "text";
  text: string;
  [key: string]: unknown;
}

interface OtherContent {
  type: string;
  [key: string]: unknown;
}

type Content = TextContent | OtherContent;

interface Message {
  role: string;
  content?: unknown;
  [key: string]: unknown;
}

interface SessionEntry {
  id?: string;
  type: string;
  customType?: string;
  data?: unknown;
  message?: Message;
}

interface ExtensionContext {
  sessionManager: { getEntries(): SessionEntry[] };
  compact(options?: {
    onComplete?: (result: unknown) => void;
    onError?: (error: Error) => void;
  }): void;
}

interface ExtensionApi {
  registerFlag(
    name: string,
    options: { type: "string"; description: string },
  ): void;
  getFlag(name: string): unknown;
  on(name: string, handler: (event: any, context: ExtensionContext) => unknown): void;
  appendEntry(customType: string, data: unknown): void;
}

export interface PolicyState {
  accumulatedOriginalToolCharacters: number;
  truncatedResults: number;
  compactionCount: number;
  preservedTurns: number | null;
  compactionPending: boolean;
  summaryAttempts: number;
  summarySuccesses: number;
  consecutiveSummaryFailures: number;
  summarySuppressed: boolean;
}

interface PersistedState {
  schema: "dci.context-state/v2";
  profile: ProfileName;
  contractVersion: typeof PROFILE_CONTRACT_VERSION;
  state: PolicyState;
}

export function profileDefinition(name: string): ProfileDefinition {
  if (!Object.hasOwn(PROFILE_DEFINITIONS, name)) {
    throw new Error("DCI context profile is invalid");
  }
  return PROFILE_DEFINITIONS[name as ProfileName];
}

export function createPolicyState(): PolicyState {
  return {
    accumulatedOriginalToolCharacters: 0,
    truncatedResults: 0,
    compactionCount: 0,
    preservedTurns: null,
    compactionPending: false,
    summaryAttempts: 0,
    summarySuccesses: 0,
    consecutiveSummaryFailures: 0,
    summarySuppressed: false,
  };
}

export function truncateText(text: string, cap: number): string {
  if (text.length <= cap) return text;
  if (cap <= TRUNCATION_MARKER.length) return TRUNCATION_MARKER.slice(-cap);
  return text.slice(0, cap - TRUNCATION_MARKER.length) + TRUNCATION_MARKER;
}

function isTextContent(value: Content): value is TextContent {
  return value.type === "text" && typeof value.text === "string";
}

export function truncateToolResultContent(
  content: Content[],
  cap: number,
): { content: Content[]; originalCharacters: number; truncated: boolean } {
  const originalText = content
    .filter(isTextContent)
    .map((item) => item.text)
    .join("");
  if (originalText.length <= cap) {
    return { content, originalCharacters: originalText.length, truncated: false };
  }
  const truncatedText = truncateText(originalText, cap);
  let emitted = false;
  const transformed = content.map((item): Content => {
    if (!isTextContent(item)) return item;
    if (emitted) return { ...item, text: "" };
    emitted = true;
    return { ...item, text: truncatedText };
  });
  return {
    content: transformed,
    originalCharacters: originalText.length,
    truncated: true,
  };
}

function originalToolCharacters(content: Content[]): number {
  return content
    .filter(isTextContent)
    .reduce((total, item) => total + item.text.length, 0);
}

export function planCompaction(
  profile: ProfileDefinition,
  state: PolicyState,
): boolean {
  const trigger = profile.compaction_character_trigger;
  return (
    trigger !== null &&
    state.accumulatedOriginalToolCharacters > trigger &&
    !state.compactionPending
  );
}

export function recordSummaryResult(
  profile: ProfileDefinition,
  state: PolicyState,
  succeeded: boolean,
): PolicyState {
  if (profile.profile !== "level4") return { ...state, compactionPending: false };
  if (succeeded) {
    return {
      ...state,
      compactionPending: false,
      summaryAttempts: state.summaryAttempts + 1,
      summarySuccesses: state.summarySuccesses + 1,
      consecutiveSummaryFailures: 0,
      summarySuppressed: false,
    };
  }
  const failures = state.consecutiveSummaryFailures + 1;
  return {
    ...state,
    compactionPending: false,
    summaryAttempts: state.summaryAttempts + 1,
    consecutiveSummaryFailures: failures,
    summarySuppressed:
      profile.summary_failure_limit !== null && failures >= profile.summary_failure_limit,
  };
}

function pressureExceeded(profile: ProfileDefinition, state: PolicyState): boolean {
  const trigger = profile.compaction_character_trigger;
  return trigger !== null && state.accumulatedOriginalToolCharacters > trigger;
}

export function transformContext(
  messages: Message[],
  profile: ProfileDefinition,
  state: PolicyState,
): Message[] {
  if (!pressureExceeded(profile, state) || profile.retained_turns === null) {
    return messages.slice();
  }
  const userIndexes = messages
    .map((message, index) => (message.role === "user" ? index : -1))
    .filter((index) => index >= 0);
  if (userIndexes.length <= profile.retained_turns) return messages.slice();
  const firstKeptIndex = userIndexes[userIndexes.length - profile.retained_turns];
  if (firstKeptIndex === undefined) return messages.slice();
  return [
    ...messages.slice(0, firstKeptIndex).filter((message) => message.role === "system"),
    ...messages.slice(firstKeptIndex),
  ];
}

function validatePolicyState(value: unknown): PolicyState {
  if (typeof value !== "object" || value === null) {
    throw new Error("DCI context state is invalid");
  }
  const state = value as Record<string, unknown>;
  const keys = [
    "accumulatedOriginalToolCharacters",
    "truncatedResults",
    "compactionCount",
    "preservedTurns",
    "compactionPending",
    "summaryAttempts",
    "summarySuccesses",
    "consecutiveSummaryFailures",
    "summarySuppressed",
  ];
  if (Object.keys(state).sort().join("|") !== keys.slice().sort().join("|")) {
    throw new Error("DCI context state is invalid");
  }
  for (const key of keys.filter(
    (item) => item !== "compactionPending" && item !== "summarySuppressed" && item !== "preservedTurns",
  )) {
    const item = state[key];
    if (!Number.isInteger(item) || (item as number) < 0) {
      throw new Error("DCI context state is invalid");
    }
  }
  if (state.preservedTurns !== null &&
      (!Number.isInteger(state.preservedTurns) || (state.preservedTurns as number) < 0)) {
    throw new Error("DCI context state is invalid");
  }
  if (typeof state.compactionPending !== "boolean" || typeof state.summarySuppressed !== "boolean") {
    throw new Error("DCI context state is invalid");
  }
  return { ...(state as unknown as PolicyState) };
}

function firstEntryForRecentTurns(entries: SessionEntry[], retainedTurns: number): string | undefined {
  const userEntries = entries.filter(
    (entry) => entry.type === "message" && entry.message?.role === "user" && typeof entry.id === "string",
  );
  return userEntries.length > retainedTurns
    ? userEntries[userEntries.length - retainedTurns]?.id
    : undefined;
}

function preservedTurnsFrom(entries: SessionEntry[], firstKeptEntryId: string | undefined): number | null {
  if (firstKeptEntryId === undefined) return null;
  const first = entries.findIndex((entry) => entry.id === firstKeptEntryId);
  if (first < 0) return null;
  return entries
    .slice(first)
    .filter((entry) => entry.type === "message" && entry.message?.role === "user").length;
}

export default function dciContextExtension(pi: ExtensionApi): void {
  pi.registerFlag("dci-context-profile", {
    type: "string",
    description: "DCI paper context profile",
  });
  pi.registerFlag("dci-context-contract", {
    type: "string",
    description: "DCI context contract version",
  });

  let profile: ProfileDefinition | undefined;
  let state = createPolicyState();

  const persist = (event: string): void => {
    if (profile === undefined) throw new Error("DCI context profile is unavailable");
    pi.appendEntry("dci-context-telemetry", {
      schema: "dci.context-telemetry/v2",
      event,
      profile: profile.profile,
      contractVersion: PROFILE_CONTRACT_VERSION,
      extensionVersion: EXTENSION_VERSION,
      ...state,
    });
    const persisted: PersistedState = {
      schema: "dci.context-state/v2",
      profile: profile.profile,
      contractVersion: PROFILE_CONTRACT_VERSION,
      state: { ...state },
    };
    pi.appendEntry("dci-context-state", persisted);
  };

  pi.on("session_start", (event, context) => {
    const profileValue = pi.getFlag("dci-context-profile");
    const contractValue = pi.getFlag("dci-context-contract");
    if (typeof profileValue !== "string") throw new Error("DCI context profile is invalid");
    if (contractValue !== PROFILE_CONTRACT_VERSION) {
      throw new Error("DCI context contract is invalid");
    }
    profile = profileDefinition(profileValue);
    const prior = context.sessionManager
      .getEntries()
      .filter((entry) => entry.type === "custom" && entry.customType === "dci-context-state")
      .at(-1);
    if (prior !== undefined) {
      const data = prior.data as Partial<PersistedState> | undefined;
      if (
        data?.schema !== "dci.context-state/v2" ||
        data.profile !== profile.profile ||
        data.contractVersion !== PROFILE_CONTRACT_VERSION
      ) {
        throw new Error("DCI context state is invalid");
      }
      state = validatePolicyState(data.state);
    } else if (event.reason === "resume") {
      throw new Error("DCI context state is missing");
    }
    persist("startup");
  });

  pi.on("tool_result", (event) => {
    if (profile === undefined) throw new Error("DCI context profile is unavailable");
    const content = event.content as Content[];
    const originalCharacters = originalToolCharacters(content);
    state = {
      ...state,
      accumulatedOriginalToolCharacters:
        state.accumulatedOriginalToolCharacters + originalCharacters,
    };
    const cap = profile.tool_result_character_cap;
    if (cap === null) {
      persist("tool_result");
      return undefined;
    }
    const transformed = truncateToolResultContent(content, cap);
    if (transformed.truncated) {
      state = { ...state, truncatedResults: state.truncatedResults + 1 };
    }
    persist("tool_result");
    return transformed.truncated ? { content: transformed.content } : undefined;
  });

  pi.on("context", (event) => {
    if (profile === undefined) throw new Error("DCI context profile is unavailable");
    return { messages: transformContext(event.messages as Message[], profile, state) };
  });

  pi.on("turn_end", (_event, context) => {
    if (profile === undefined || !planCompaction(profile, state)) return;
    state = { ...state, compactionPending: true };
    const summaryWasSuppressed = profile.profile === "level4" && state.summarySuppressed;
    persist("compaction_requested");
    context.compact({
      onComplete: () => {
        if (profile?.profile === "level4" && !summaryWasSuppressed) {
          state = recordSummaryResult(profile, state, true);
        }
        else state = { ...state, compactionPending: false };
        persist("compaction_complete");
      },
      onError: () => {
        if (profile === undefined) return;
        state =
          profile.profile === "level4" && !summaryWasSuppressed
            ? recordSummaryResult(profile, state, false)
            : { ...state, compactionPending: false };
        persist("compaction_failed");
      },
    });
  });

  pi.on("session_before_compact", (event) => {
    if (profile === undefined) throw new Error("DCI context profile is unavailable");
    const branchEntries = event.branchEntries as SessionEntry[];
    if (profile.profile === "level4" && !state.summarySuppressed) {
      if (event.preparation?.settings?.keepRecentTokens !== 20_000) {
        throw new Error("DCI level4 requires a 20000-token compaction boundary");
      }
      state = {
        ...state,
        preservedTurns: preservedTurnsFrom(
          branchEntries,
          event.preparation.firstKeptEntryId,
        ),
      };
      return undefined;
    }
    if (
      (profile.profile !== "level3" &&
        !(profile.profile === "level4" && state.summarySuppressed)) ||
      profile.retained_turns === null
    ) {
      return undefined;
    }
    const firstKeptEntryId =
      firstEntryForRecentTurns(branchEntries, profile.retained_turns) ??
      event.preparation.firstKeptEntryId;
    state = {
      ...state,
      preservedTurns: preservedTurnsFrom(branchEntries, firstKeptEntryId),
    };
    return {
      compaction: {
        summary: "",
        firstKeptEntryId,
        tokensBefore: event.preparation.tokensBefore,
      },
    };
  });

  pi.on("session_compact", () => {
    if (profile === undefined) throw new Error("DCI context profile is unavailable");
    state = {
      ...state,
      accumulatedOriginalToolCharacters: 0,
      compactionPending: false,
      compactionCount: state.compactionCount + 1,
    };
    persist("session_compact");
  });
}
