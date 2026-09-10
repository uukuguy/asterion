/** Provider-free G0 evidence from the actual locked compaction and RPC code. */
import assert from "node:assert/strict";
import { execFileSync, spawn } from "node:child_process";
import { readFileSync, realpathSync, writeSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { createInterface } from "node:readline";
import {
  canonicalEvidence, guardCompactionImports, loadContextCounter, sha256, verifyCompactionLock,
} from "./build_asterion_prime_compaction_lock.mjs";

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), "..");
const SETTINGS = Object.freeze({ enabled: false, reserveTokens: 4096, keepRecentTokens: 256 });
const PRICE = Object.freeze({ input_per_million: 2_000_000, output_per_million: 4_000_000 });
const INSTRUCTIONS = "Preserve the synthetic worker state.";
const PREVIOUS_SUMMARY = "Earlier synthetic checkpoint.";
const SUMMARY = "Synthetic checkpoint with worker state retained.";
const API = "asterion-provider-free-compaction-probe";
const MODEL = Object.freeze({ id: "synthetic", name: "synthetic", api: API, provider: API,
  baseUrl: "https://invalid.invalid", reasoning: false, input: ["text"],
  contextWindow: 16000, maxTokens: 3276, cost: { input: 2, output: 4, cacheRead: 0, cacheWrite: 0 } });

function assistant(text) {
  return { role: "assistant", content: [{ type: "text", text }], timestamp: 0,
    api: API, model: MODEL.id, provider: API, stopReason: "stop" };
}

function fixtureEntries(mainLength, prefixLength) {
  const values = [
    { type: "message", message: { role: "user", content: "M".repeat(mainLength), timestamp: 0 } },
    { type: "compaction", summary: PREVIOUS_SUMMARY, firstKeptEntryId: "e0", tokensBefore: 1 },
    { type: "message", message: assistant("Prior stage completed.") },
    { type: "message", message: { role: "user", content: "P".repeat(prefixLength), timestamp: 0 } },
    { type: "message", message: assistant("S".repeat(1024)) },
  ];
  return values.map((entry, i) => ({ ...entry, id: `e${i}`, parentId: i === 0 ? null : `e${i - 1}`,
    timestamp: "2000-01-01T00:00:00.000Z" }));
}

/** Reconstruct both exact requests using pinned serialization/templates. */
export function reconstructCompactionRequests(preparation, instructions, pinned) {
  const { compaction, messages, utils, turnPrefixPrompt } = pinned;
  const request = (conversation, instruction, previousSummary) => {
    let text = `<conversation>\n${utils.serializeConversation(messages.convertToLlm(conversation))}\n</conversation>\n\n`;
    if (previousSummary) text += `<previous-summary>\n${previousSummary}\n</previous-summary>\n\n`;
    text += instruction;
    return { systemPrompt: utils.SUMMARIZATION_SYSTEM_PROMPT,
      messages: [{ role: "user", content: [{ type: "text", text }], timestamp: 0 }] };
  };
  return [
    request(preparation.messagesToSummarize,
      compaction.buildSummarizationPrompt(instructions, preparation.previousSummary), preparation.previousSummary),
    preparation.isSplitTurn && preparation.turnPrefixMessages.length > 0
      ? request(preparation.turnPrefixMessages, turnPrefixPrompt) : null,
  ];
}

async function pinnedModules(verified) {
  const load = (name) => import(pathToFileURL(join(verified.root, name)).href);
  const compactionPath = "packages/coding-agent/dist/core/compaction/compaction.js";
  // This non-exported literal is read only after the whole module closure passes.
  // Reject interpolation/escapes so source text is exactly the evaluated constant.
  const source = readFileSync(join(verified.root, compactionPath), "utf8");
  const matches = [...source.matchAll(/const TURN_PREFIX_SUMMARIZATION_PROMPT = `([^`]+)`;/gu)];
  assert.equal(matches.length, 1);
  const turnPrefixPrompt = matches[0][1];
  assert(!turnPrefixPrompt.includes("${") && !turnPrefixPrompt.includes("\\"));
  return {
    compaction: await load(compactionPath),
    session: await load("packages/coding-agent/dist/core/session-manager.js"),
    messages: await load("packages/coding-agent/dist/core/messages.js"),
    utils: await load("packages/coding-agent/dist/core/compaction/utils.js"),
    agent: await load("packages/coding-agent/dist/core/agent-session.js"),
    ai: await load("packages/ai/dist/index.js"),
    rpc: await load("packages/coding-agent/dist/modes/rpc/rpc-mode.js"),
    turnPrefixPrompt,
  };
}

function maximalFixture(pinned, counter) {
  const sizes = (entries) => reconstructCompactionRequests(
    pinned.compaction.prepareCompaction(entries, SETTINGS), INSTRUCTIONS, pinned,
  ).map((request) => counter.countRebuiltContext(counter.projectPrimeContext(request.messages, request.systemPrompt)));
  // Only ASCII synthetic content changes: adding one character adds one unit.
  const initial = sizes(fixtureEntries(1, 1));
  assert(initial.every((size) => size < 4096));
  const lengths = initial.map((size) => 4096 - size + 1);
  const entries = fixtureEntries(...lengths);
  assert.deepEqual(sizes(entries), [4096, 4096]);
  assert.deepEqual(sizes(fixtureEntries(lengths[0] + 1, lengths[1] + 1)), [4097, 4097]);
  return entries;
}

function pythonQuote() {
  // The Python calculator is the sole arithmetic implementation. No JS price
  // formula or copied static total supplies the fixture's reservation facts.
  const stdout = execFileSync("uv", ["run", "--no-sync", "python", "-m", "asterion.agents.prime.compaction_budget"], {
    cwd: REPO_ROOT, encoding: "utf8", timeout: 15_000,
    input: JSON.stringify({ branch_input_caps: [4096, 4096], branch_output_caps: [3276, 3276], price: PRICE }),
    env: { PATH: process.env.PATH, LANG: "C.UTF-8" },
  });
  return JSON.parse(stdout);
}

async function rpcChild(root) {
  const counter = await loadContextCounter();
  const verified = verifyCompactionLock(root);
  const guard = guardCompactionImports(verified);
  const pinned = await pinnedModules(verified);
  const entries = maximalFixture(pinned, counter);
  const preparation = pinned.compaction.prepareCompaction(entries, SETTINGS);
  assert(preparation.messagesToSummarize.length > 0 && preparation.turnPrefixMessages.length > 0);
  assert(preparation.isSplitTurn);
  const expected = reconstructCompactionRequests(preparation, INSTRUCTIONS, pinned);
  const requestBytes = (context) => counter.canonicalJson(counter.projectPrimeContext(context.messages, context.systemPrompt));
  const captures = [];
  const hookOrder = [];
  const rpcOrder = [];
  const lifecycle = [];
  const complete = (model, context, options) => {
    assert.equal(model.api, API);
    assert.equal(hookOrder.at(-1), "session_before_compact");
    const index = captures.length;
    assert(index < 2);
    assert.equal(requestBytes(context), requestBytes(expected[index]));
    captures.push({ request_sha256: sha256(requestBytes(context)),
      request_asterion_units: Buffer.byteLength(requestBytes(context)), observed_max_tokens: options.maxTokens });
    lifecycle.push("summary-request");
    const stream = pinned.ai.createAssistantMessageEventStream();
    stream.push({ type: "done", reason: "stop", message: assistant(SUMMARY) });
    return stream;
  };
  // Register an in-memory sink under an impossible provider API. The real
  // completeSimple/compact functions execute; no network adapter is invoked.
  pinned.ai.clearApiProviders();
  pinned.ai.registerApiProvider({ api: API, stream: complete, streamSimple: complete }, API);
  const manager = pinned.session.SessionManager.inMemory(root);
  for (const entry of entries) {
    if (entry.type === "message") manager.appendMessage(entry.message);
    else manager.appendCompaction(entry.summary, manager.getEntries()[0].id, entry.tokensBefore);
  }
  const beforeContext = counter.projectPrimeContext(manager.buildSessionContext().messages);
  const actualPreparation = pinned.compaction.prepareCompaction(manager.getBranch(), SETTINGS);
  assert.deepEqual(reconstructCompactionRequests(actualPreparation, INSTRUCTIONS, pinned).map(requestBytes), expected.map(requestBytes));
  // Use the real compaction implementation with in-memory ownership services.
  // No AgentSession constructor/model-registry/worker/bootstrap is run.
  const session = Object.create(pinned.agent.AgentSession.prototype);
  session.sessionManager = manager;
  session.settingsManager = { getCompactionSettings: () => SETTINGS };
  session.agent = { state: { messages: manager.buildSessionContext().messages, thinkingLevel: "off" } };
  session._extensionRunner = {
    hasHandlers: () => true,
    async emit(event) {
      hookOrder.push(event.type);
      lifecycle.push(event.type);
      if (event.type === "session_before_compact") {
        assert.equal(captures.length, 0);
        assert(event.preparation.messagesToSummarize.length > 0 && event.preparation.turnPrefixMessages.length > 0);
        assert(Number.isSafeInteger(event.preparation.tokensBefore) && event.preparation.tokensBefore > 0);
        assert.deepEqual(reconstructCompactionRequests(event.preparation, event.customInstructions, pinned).map(requestBytes), expected.map(requestBytes));
        return undefined;
      }
      assert.equal(event.type, "session_compact");
      assert.equal(event.fromExtension, false);
      assert.equal(captures.length, 2);
      assert.equal(event.compactionEntry.firstKeptEntryId, actualPreparation.firstKeptEntryId);
      const rebuilt = pinned.session.buildSessionContext(manager.getBranch()).messages;
      const afterContext = counter.projectPrimeContext(rebuilt);
      assert(counter.countRebuiltContext(afterContext) < counter.countRebuiltContext(beforeContext));
      assert.deepEqual(session.agent.state.messages, rebuilt);
    },
  };
  session._mergeUnpersistedCompactionOutcomes = () => {};
  session._restoreLateIpythonSentAgentMessages = () => {};
  session._notifyKernelStateAfterCompaction = async () => {};
  session._reapDeletedRlmSubagentRuntimesAfterCompaction = async () => {};
  const connection = {
    subscribe: () => () => {},
    async prompt() { rpcOrder.push("prompt"); },
    async compact(instructions) {
      rpcOrder.push("compact");
      return session._performCompaction({ model: MODEL, customInstructions: instructions,
        apiKey: "synthetic-not-a-credential", signal: new AbortController().signal });
    },
    async waitForIdle() {},
    async dispose() {
      assert.deepEqual(lifecycle, ["session_before_compact", "summary-request", "summary-request", "session_compact"]);
      writeSync(3, `${canonicalEvidence({ captures, hookOrder, rpcOrder })}\n`);
      pinned.ai.clearApiProviders();
      guard.deregister();
    },
  };
  await pinned.rpc.runRpcModeWithConnection(connection);
}

async function observeRpc(root) {
  const child = spawn(process.execPath, [fileURLToPath(import.meta.url), root], {
    cwd: REPO_ROOT, stdio: ["pipe", "pipe", "pipe", "pipe"],
    env: { PATH: process.env.PATH, LANG: "C.UTF-8", ASTERION_COMPACTION_PROBE_CHILD: "1" },
  });
  let diagnostics = "";
  let evidence = "";
  child.stderr.on("data", (chunk) => { diagnostics += chunk; });
  child.stdio[3].on("data", (chunk) => { evidence += chunk; });
  const commands = [
    { id: "probe-1", type: "prompt", message: "synthetic stage one" },
    { id: "probe-2", type: "compact", customInstructions: INSTRUCTIONS },
    { id: "probe-3", type: "prompt", message: "synthetic stage two" },
  ];
  const lines = createInterface({ input: child.stdout });
  let cursor = 0;
  const failure = [];
  lines.on("line", (line) => {
    try {
      const response = JSON.parse(line);
      assert.equal(response.type, "response");
      assert.equal(response.id, commands[cursor].id);
      assert.equal(response.command, commands[cursor].type);
      assert.equal(response.success, true);
      cursor += 1;
      if (cursor === commands.length) child.stdin.end();
      else child.stdin.write(`${JSON.stringify(commands[cursor])}\n`);
    } catch (error) { failure.push(error); child.kill("SIGTERM"); }
  });
  const timer = setTimeout(() => { failure.push(new Error("probe deadline")); child.kill("SIGKILL"); }, 30_000);
  try {
    child.stdin.write(`${JSON.stringify(commands[0])}\n`);
    const status = await new Promise((resolve, reject) => { child.on("error", reject); child.on("close", resolve); });
    assert.equal(status, 0, diagnostics);
    assert.equal(diagnostics, "");
    assert.equal(failure.length, 0);
    assert.equal(cursor, 3);
    return JSON.parse(evidence);
  } finally { clearTimeout(timer); lines.close(); if (child.exitCode === null) child.kill("SIGKILL"); }
}

async function main() {
  assert.equal(process.argv.length, 3);
  const root = process.argv[2];
  if (process.env.ASTERION_COMPACTION_PROBE_CHILD === "1") return rpcChild(root);
  const verified = verifyCompactionLock(root);
  const observed = await observeRpc(root);
  const quote = pythonQuote();
  const branches = ["main-summary", "turn-prefix-summary"];
  assert.equal(observed.captures.length, 2);
  const evidence = {
    branches,
    branch_evidence: branches.map((branch, index) => ({
      branch, ...observed.captures[index], input_cap: 4096, output_cap: 3276,
      price: PRICE, rounding: "ceil-each-input-output-component-before-summing",
      ...quote.branch_quotes[index],
    })),
    hook_order: observed.hookOrder,
    input_caps: [4096, 4096],
    output_caps: [3276, 3276],
    internal_module_beneath_locked_root: true,
    pi_version: verified.pkg.version,
    public_prepare_compaction_exported: verified.lock.public_exports.includes("prepareCompaction"),
    rpc_order: observed.rpcOrder,
    settings: { autoCompact: SETTINGS.enabled, keepRecentTokens: SETTINGS.keepRecentTokens, reserveTokens: SETTINGS.reserveTokens },
    worst_case_cost_micro_units: quote.cost_micro_units,
    worst_case_reserved_tokens: quote.reserved_tokens,
  };
  process.stdout.write(`${canonicalEvidence(evidence)}\n`);
}

if (process.argv[1] && pathToFileURL(realpathSync(process.argv[1])).href === import.meta.url) {
  main().catch(() => { process.stderr.write("Pi compaction probe failed\n"); process.exitCode = 1; });
}
