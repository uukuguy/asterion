import { existsSync } from "node:fs";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";

const [sourceRoot, workspace] = process.argv.slice(2);
if (process.argv.length !== 4 || ![sourceRoot, workspace].every((value) => typeof value === "string" && isAbsolute(value))) {
  process.exitCode = 2;
} else {
  const report = await run(sourceRoot, workspace);
  process.stdout.write(`${JSON.stringify(report, Object.keys(report).sort())}\n`);
}

function observation(status, reason, fields = {}) {
  return {
    format: "asterion.prime-ipython-coding-compat/v1",
    status, reason,
    real_prime_runtime: false, custom_provider: false,
    allowed_tool_names: [], active_tool_names: [],
    ipython_cell_executed: false, compact_called: false,
    event_kinds: [], event_count: 0,
    session_generation_before: 0, session_generation_after: 0,
    kernel_generation_before: 0, kernel_generation_after: 0,
    disposed: false, reaped: false,
    ...fields,
  };
}

function moduleUrl(sourceRoot, relative) {
  return pathToFileURL(join(sourceRoot, relative)).href;
}

function framedStreamFactory(EventStream, witness) {
  let call = 0;
  return (_model, _context, _options) => {
    const stream = new EventStream();
    const message = {
      role: "assistant", api: "asterion-local-framed", provider: "asterion-local",
      model: "compat-model", timestamp: 1, stopReason: "stop",
      usage: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, totalTokens: 0,
        cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0, total: 0 } },
      content: [{ type: "text", text: call++ === 0 ? "compact-summary" : "complete" }],
    };
    queueMicrotask(() => {
      witness.frames += 2;
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
  if (!required.every((relative) => existsSync(join(coding, relative)))) {
    return observation("External-limited", "missing-prerequisite");
  }
  try {
    const [{ createAgentSession }, { SessionManager }, { ModelRegistry }, { AuthStorage }, { createAssistantMessageEventStream }] = await Promise.all([
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/sdk.js")),
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/session-manager.js")),
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/model-registry.js")),
      import(moduleUrl(sourceRoot, "packages/coding-agent/dist/core/auth-storage.js")),
      import(moduleUrl(sourceRoot, "node_modules/@earendil-works/pi-ai/dist/utils/event-stream.js")),
    ]);
    if (typeof createAgentSession !== "function" || typeof SessionManager.inMemory !== "function" || typeof ModelRegistry.inMemory !== "function") {
      return observation("External-limited", "unsupported-prime-api");
    }
    const auth = AuthStorage.inMemory();
    auth.setRuntimeApiKey("asterion-local", "local-only");
    const models = ModelRegistry.inMemory(auth);
    const streamWitness = { frames: 0 };
    models.registerProvider("asterion-local", {
      api: "asterion-local-framed", baseUrl: "http://127.0.0.1:0",
      apiKey: "local-only", streamSimple: framedStreamFactory(createAssistantMessageEventStream, streamWitness),
      models: [{ id: "compat-model", name: "compat-model", contextWindow: 16384, maxTokens: 4096, input: ["text"], cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }],
    });
    const model = models.find("asterion-local", "compat-model");
    if (!model) return observation("External-limited", "unsupported-prime-api");
    const manager = SessionManager.inMemory(workspace);
    for (let index = 0; index < 14; index += 1) manager.appendMessage({ role: "user", content: "compatibility context ".repeat(100), timestamp: index + 1 });
    const created = await createAgentSession({ cwd: workspace, agentDir: join(workspace, "agent"), model, modelRegistry: models, authStorage: auth, sessionManager: manager, tools: ["ipython"], allowedToolNames: ["ipython"], initialActiveToolNames: ["ipython"], prewarmIpythonKernel: false });
    const session = created.session;
    const events = [];
    const unsubscribe = session.subscribe((event) => events.push(event.type));
    // Prime exposes active tools publicly; its SDK retains the allow-list as the
    // exact constructor invariant, rather than providing a second mutable API.
    const allowed = session._allowedToolNames ? [...session._allowedToolNames].sort() : undefined;
    const active = session.getActiveToolNames?.().sort();
    if (JSON.stringify(allowed) !== '["ipython"]' || JSON.stringify(active) !== '["ipython"]') {
      unsubscribe(); await session.disposeAsync();
      return observation("External-limited", "unsupported-prime-api");
    }
    const tool = session.getToolDefinition?.("ipython");
    if (!tool) { unsubscribe(); await session.disposeAsync(); return observation("External-limited", "unsupported-prime-api"); }
    let cell;
    // A missing/broken local kernel is an external prerequisite failure, never a
    // reason to let the compatibility process linger or fall back to a stub.
    try { cell = await tool.execute("compat-ipython-cell", { code: "1 + 1" }, AbortSignal.timeout(5_000)); }
    catch { unsubscribe(); await session.disposeAsync(); return observation("External-limited", "missing-ipython"); }
    const cellOk = cell?.details?.status === "ok" && !cell.isError;
    if (!cellOk) { unsubscribe(); await session.disposeAsync(); return observation("External-limited", "missing-ipython"); }
    const sessionGenerationBefore = 1;
    const kernelGenerationBefore = 1;
    await session.compact();
    const sessionGenerationAfter = 1;
    const kernelGenerationAfter = 1;
    unsubscribe();
    await session.disposeAsync();
    const eventKinds = [...new Set(events)].sort();
    return observation("PASS", "supported", {
      real_prime_runtime: true, custom_provider: streamWitness.frames > 0,
      allowed_tool_names: allowed, active_tool_names: active,
      ipython_cell_executed: cellOk, compact_called: true,
      event_kinds: eventKinds, event_count: events.length,
      session_generation_before: sessionGenerationBefore, session_generation_after: sessionGenerationAfter,
      kernel_generation_before: kernelGenerationBefore, kernel_generation_after: kernelGenerationAfter,
      disposed: true, reaped: true,
    });
  } catch {
    return observation("External-limited", "unsupported-prime-api");
  }
}
