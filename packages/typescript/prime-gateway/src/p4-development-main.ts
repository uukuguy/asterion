import { lstat, realpath } from "node:fs/promises";
import { isAbsolute, join } from "node:path";
import { pathToFileURL } from "node:url";
import process from "node:process";
import { writeSync } from "node:fs";

const fail = (): never => process.exit(1);
async function fixed(root: string, path: string): Promise<string> { const target = join(root, path); const [base, actual, stat] = await Promise.all([realpath(root), realpath(target), lstat(target)]); if (!stat.isFile() || stat.isSymbolicLink() || !actual.startsWith(`${base}/`)) fail(); return actual; }
let stage = "load";
const report = (value: string): void => { try { writeSync(3, `${value}\n`); } catch {} };
async function main(): Promise<void> {
  const [root, workspace, socketPath] = process.argv.slice(2);
  if (!root || !workspace || !socketPath || !isAbsolute(root) || !isAbsolute(workspace)) fail();
  const sourceRoot = root as string, workRoot = workspace as string, daemonSocket = socketPath as string;
  const daemonModule = await import(pathToFileURL(await fixed(sourceRoot, "node_modules/@earendil-works/pi-coding-agent/dist/modes/daemon/daemon-mode.js")).href) as Record<string, unknown>;
  const clientModule = await import(pathToFileURL(await fixed(sourceRoot, "node_modules/@earendil-works/pi-coding-agent/dist/modes/daemon/daemon-client.js")).href) as Record<string, unknown>;
  const sdk = await import(pathToFileURL(await fixed(sourceRoot, "node_modules/@earendil-works/pi-coding-agent/dist/index.js")).href) as Record<string, unknown>;
  if (typeof daemonModule.AgentDaemon !== "function" || typeof clientModule.DaemonClient !== "function" || typeof sdk.createAgentSessionServices !== "function" || typeof sdk.createAgentSessionFromServices !== "function") fail();
  const agentDir = join(workRoot, ".asterion-p4-development");
  const auth = (sdk.AuthStorage as { inMemory(): { setRuntimeApiKey(provider: string, key: string): void } }).inMemory();
  const registry = (sdk.ModelRegistry as { inMemory(auth: unknown): { registerProvider(provider: string, config: Record<string, unknown>): void; find(provider: string, model: string): unknown } }).inMemory(auth);
  const settings = (sdk.SettingsManager as { inMemory(settings: unknown): unknown }).inMemory({ retry: { enabled: false, provider: { maxRetries: 0 } }, compaction: { enabled: false } });
  const provider = "asterion-p4-development", modelId = "p4-development";
  auth.setRuntimeApiKey(provider, "in-memory-development-provider");
  registry.registerProvider(provider, { api: provider, baseUrl: "http://127.0.0.1:0", apiKey: "in-memory-development-provider", streamSimple: () => { throw new Error("P4 metadata smoke must not invoke a model"); }, models: [{ id: modelId, name: modelId, reasoning: false, input: ["text"], contextWindow: 16384, maxTokens: 1024, cost: { input: 0, output: 0, cacheRead: 0, cacheWrite: 0 } }] });
  const model = registry.find(provider, modelId); if (!model) fail();
  const createRuntime = async ({ cwd, agentDir: runtimeAgentDir, sessionManager, sessionStartEvent }: Record<string, unknown>) => {
    if (cwd !== workRoot || runtimeAgentDir !== agentDir || !sessionManager) throw new Error();
    stage = "runtime-services";
    const services = await (sdk.createAgentSessionServices as Function)({ cwd, agentDir, authStorage: auth, modelRegistry: registry, settingsManager: settings, telemetryDisabled: true, noBuiltinHerdrReporter: true, resourceLoaderOptions: { noExtensions: true, noSkills: true, noPromptTemplates: true, noThemes: true, noContextFiles: true, bundledSkillsDir: null } });
    stage = "runtime-session";
    const created = await (sdk.createAgentSessionFromServices as Function)({ services, sessionManager, sessionStartEvent, model, noTools: true, telemetryDisabled: true, prewarmIpythonKernel: false, serializedRefine: true });
    stage = "runtime-return";
    return { ...created, services, diagnostics: [] };
  };
  const daemon = new (daemonModule.AgentDaemon as any)(daemonSocket, { defaultSessionConfig: { cwd: workRoot, agentDir, sessionDir: agentDir, telemetryDisabled: true }, createRuntime });
  stage = "daemon-start"; report(stage); await daemon.start();
  const client = new (clientModule.DaemonClient as any)(daemonSocket);
  stage = "hello"; report(stage); await client.connect(); const hello = await client.waitForHello(); report("hello-ok");
  if (hello.protocol?.version !== 7 || hello.schemaId !== "protocol-7-schema-14-816309b1cd50" || hello.schemaRevision !== 14 || hello.appVersion !== "0.7.1" || typeof hello.runtime?.buildId !== "string" || !hello.runtime.buildId || typeof hello.clientId !== "string" || !hello.clientId || !["attach_snapshot", "event_sequence"].every((value) => hello.serverCapabilities?.includes(value)) || "supervisorGeneration" in hello) fail();
  const cursors: Array<{ generation: string; sequence: number }> = [];
  client.onMessage((message: any) => { const cursor = message?.meta?.cursor; if (typeof cursor?.generation === "string" && Number.isSafeInteger(cursor.sequence)) cursors.push({ generation: cursor.generation, sequence: cursor.sequence }); });
  stage = "create"; report(stage); const created = await client.request({ type: "create", continueRecent: false, noSession: false, name: "p4-smoke", lifecycle: "resident", config: {} }); report("create-response");
  const activeSessionId = created?.data?.activeSessionId;
  if (!created?.success || typeof activeSessionId !== "string" || !activeSessionId) fail();
  stage = "attach"; await client.request({ type: "attach", activeSessionId, supportsExtensionUi: false, clientId: "asterion-p4", capabilities: ["attach_snapshot", "event_sequence"], telemetryDisabled: true });
  const cursor = cursors.at(-1); if (!cursor) fail();
  stage = "detach"; await client.request({ type: "detach", activeSessionId });
  stage = "reattach"; const attached = await client.request({ type: "attach", activeSessionId, supportsExtensionUi: false, clientId: "asterion-p4", capabilities: ["attach_snapshot", "event_sequence"], resumeCursor: cursor, telemetryDisabled: true });
  if (!attached?.success || attached?.data?.activeSessionId !== activeSessionId) fail();
  await client.request({ type: "detach", activeSessionId }); client.close();
  process.stdout.write(JSON.stringify({ activeSessionId, cursor }) + "\n");
  process.kill(process.pid, "SIGTERM");
}
main().catch((error) => { report(`${stage}:error`); fail(); });
