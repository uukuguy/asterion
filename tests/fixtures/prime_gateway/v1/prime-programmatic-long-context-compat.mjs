import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

const [sourceRoot, workspace] = process.argv.slice(2);
if (process.argv.length !== 4 || ![sourceRoot, workspace].every((value) => typeof value === "string" && isAbsolute(value))) {
  process.exitCode = 2;
} else {
  const report = await run(sourceRoot, workspace);
  process.stdout.write(`${JSON.stringify(report, Object.keys(report).sort())}\n`);
}

function digest(value) {
  return `sha256:${createHash("sha256").update(value).digest("hex")}`;
}

function observation(status, reason, fields = {}) {
  return {
    format: "asterion.prime-programmatic-long-context-compat/v1",
    status, reason,
    real_prime_runtime: false,
    allowed_tool_names: [], active_tool_names: [],
    corpus_sha256: null, corpus_record_count: 0, selected_record_count: 0,
    program_sha256: null, aggregate_sha256: null, oracle_sha256: null,
    ipython_cell_executed: false, oracle_passed: false,
    disposed: false, reaped: false,
    ...fields,
  };
}

function moduleUrl(sourceRoot, relative) {
  return pathToFileURL(join(sourceRoot, relative)).href;
}

function localStreamFactory(EventStream) {
  return () => {
    const stream = new EventStream();
    const message = {
      role: "assistant", api: "asterion-local-framed", provider: "asterion-local",
      model: "compat-model", timestamp: 1, stopReason: "stop",
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      content: [{ type: "text", text: "local-only" }],
    };
    queueMicrotask(() => {
      stream.push({ type: "start", partial: { ...message, content: [] } });
      stream.push({ type: "done", reason: "stop", message });
      stream.end(message);
    });
    return stream;
  };
}

async function run(sourceRoot, workspace) {
  const coding = join(sourceRoot, "packages/coding-agent/dist");
  const required = ["core/sdk.js", "core/session-manager.js", "core/model-registry.js", "core/auth-storage.js", "core/tools/ipython.js"];
  if (!required.every((relative) => existsSync(join(coding, relative)))) return observation("External-limited", "missing-prerequisite");
  const records = [
    { id: "r1", include: true, value: 5, private: "CORPUS-SENTINEL" },
    { id: "r2", include: false, value: 11, private: "CORPUS-SENTINEL" },
    { id: "r3", include: true, value: 7, private: "CORPUS-SENTINEL" },
    { id: "r4", include: false, value: 13, private: "CORPUS-SENTINEL" },
  ];
  const corpus = JSON.stringify(records);
  const corpusPath = join(workspace, "corpus.json");
  const aggregatePath = join(workspace, "aggregate.json");
  writeFileSync(corpusPath, corpus, { encoding: "utf8", mode: 0o600 });
  const program = [
    "from pathlib import Path",
    "import hashlib, json",
    "records = json.loads(Path('corpus.json').read_text(encoding='utf-8'))",
    "selected = [record for record in records if record['include']]",
    "aggregate = {'count': len(selected), 'sum': sum(record['value'] for record in selected)}",
    "Path('aggregate.json').write_text(json.dumps(aggregate, sort_keys=True), encoding='utf-8')",
    "assert aggregate == {'count': 2, 'sum': 12}",
  ].join("\n");
  try {
    const [{ createAgentSession }, { SessionManager }, { ModelRegistry }, { AuthStorage }, { createAssistantMessageEventStream }] = await Promise.all([
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/sdk.js")),
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/session-manager.js")),
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/model-registry.js")),
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/auth-storage.js")),
      import(moduleUrl(sourceRoot, "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js")),
    ]);
    if (typeof createAgentSession !== "function" || typeof SessionManager.inMemory !== "function" || typeof ModelRegistry.inMemory !== "function") return observation("External-limited", "unsupported-prime-api");
    const auth = AuthStorage.inMemory();
    auth.setRuntimeApiKey("asterion-local", "local-only");
    const models = ModelRegistry.inMemory(auth);
    models.registerProvider("asterion-local", {
      api: "asterion-local-framed", baseUrl: "http://127.0.0.1:0", apiKey: "local-only",
      streamSimple: localStreamFactory(createAssistantMessageEventStream),
      models: [{ id: "compat-model", name: "compat-model", contextWindow: 16384, maxTokens: 4096, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
    });
    const model = models.find("asterion-local", "compat-model");
    if (!model) return observation("External-limited", "unsupported-prime-api");
    const created = await createAgentSession({ cwd: workspace, agentDir: join(workspace, "agent"), model, modelRegistry: models, authStorage: auth, sessionManager: SessionManager.inMemory(workspace), tools: ["ipython"], allowedToolNames: ["ipython"], initialActiveToolNames: ["ipython"], prewarmIpythonKernel: false });
    const session = created.session;
    const allowed = session._allowedToolNames ? [...session._allowedToolNames].sort() : undefined;
    const active = session.getActiveToolNames?.().sort();
    if (JSON.stringify(allowed) !== '["ipython"]' || JSON.stringify(active) !== '["ipython"]') {
      await session.disposeAsync();
      return observation("External-limited", "unsupported-prime-api");
    }
    const tool = session.getToolDefinition?.("ipython");
    if (!tool) { await session.disposeAsync(); return observation("External-limited", "unsupported-prime-api"); }
    let cell;
    try { cell = await tool.execute("programmatic-long-context", { code: program }, AbortSignal.timeout(5_000)); }
    catch { await session.disposeAsync(); return observation("External-limited", "missing-ipython"); }
    if (cell?.details?.status !== "ok" || cell.isError || !existsSync(aggregatePath)) {
      await session.disposeAsync();
      return observation("External-limited", "missing-ipython");
    }
    const aggregate = readFileSync(aggregatePath, "utf8");
    const expected = JSON.stringify({ count: 2, sum: 12 });
    const oraclePassed = aggregate === expected;
    await session.disposeAsync();
    if (!oraclePassed) return observation("External-limited", "unsupported-prime-api");
    return observation("PASS", "supported", {
      real_prime_runtime: true,
      allowed_tool_names: allowed, active_tool_names: active,
      corpus_sha256: digest(corpus), corpus_record_count: records.length,
      selected_record_count: 2, program_sha256: digest(program),
      aggregate_sha256: digest(aggregate), oracle_sha256: digest(expected),
      ipython_cell_executed: true, oracle_passed: true,
      disposed: true, reaped: true,
    });
  } catch {
    return observation("External-limited", "unsupported-prime-api");
  }
}
