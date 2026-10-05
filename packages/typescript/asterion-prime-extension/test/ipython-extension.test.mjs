import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
  mkdirSync,
  mkdtempSync,
  openSync,
  readFileSync,
  rmSync,
  unlinkSync,
  writeFileSync,
} from "node:fs";
import { createServer, createConnection } from "node:net";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { pathToFileURL } from "node:url";
import test from "node:test";
import { IsSchema } from "typebox";

import register, {
  PROTOCOL,
  canonicalJson,
  composeSummarizationRequest,
  createAppLevelTools,
  createLegacyAppLevelTools,
  P7_WORKSPACE_PARAMETERS,
  P7_EXECUTE_PLAN_PARAMETERS,
  createIpythonBridge,
  registerContextWitness,
  summarizeInstruction,
  toolNames,
} from "../dist/ipython-extension.mjs";

const artifactPath = resolve("dist/ipython-extension.mjs");
// The native side owns the prompt material and delivers it on the arm frame.
// The shared fixture is the same record both languages are held to.
const material = JSON.parse(readFileSync(
  resolve("../../../tests/fixtures/asterion_prime_p1/v1/summarization-parity.json"))).material;
const loaderPath = resolve(
  "../../../src/asterion/runtimes/resources/asterion_pi_extension_loader.mjs",
);

async function socketPair() {
  const root = mkdtempSync(join(tmpdir(), "asterion-ipython-bridge-"));
  const socketPath = join(root, "bridge.sock");
  const server = createServer();
  await new Promise((resolveReady, reject) => {
    server.once("error", reject);
    server.listen(socketPath, resolveReady);
  });
  const accepted = new Promise((resolveAccepted) => server.once("connection", resolveAccepted));
  const client = createConnection(socketPath);
  await new Promise((resolveReady, reject) => {
    client.once("connect", resolveReady);
    client.once("error", reject);
  });
  const peer = await accepted;
  // The bridge consumes the client descriptor with fs.read(). Pause the
  // net.Socket wrapper so its own stream reader cannot race that consumer.
  client.pause();
  // Node 24 leaves the native handle reading after pause when the stream was
  // never flowing. Stop it explicitly before handing the FD to fs.read;
  // otherwise responses silently accumulate in client.readableLength.
  client._handle.readStop();
  client._handle.reading = false;
  return {
    descriptor: client._handle.fd,
    client,
    peer,
    close() {
      client.destroy();
      peer.destroy();
      server.close();
      rmSync(root, { recursive: true, force: true });
    },
  };
}

function runInheritedBridge(pair, payload) {
  const source = `
    import { createIpythonBridge } from ${JSON.stringify(pathToFileURL(artifactPath).href)};
    const payload = JSON.parse(process.argv[1]);
    const bridge = createIpythonBridge(3, payload.options);
    const controller = new AbortController();
    if (payload.abort) controller.abort();
    try {
      const result = await bridge.execute(payload.requestId, payload.code, controller.signal);
      process.stdout.write(JSON.stringify({ ok: true, result }));
    } catch (error) {
      process.stdout.write(JSON.stringify({ ok: false, message: error instanceof Error ? error.message : "invalid" }));
    }
  `;
  const child = spawn(process.execPath, ["--input-type=module", "-e", source, JSON.stringify(payload)], {
    stdio: ["ignore", "pipe", "pipe", pair.client],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (value) => { stdout += value; });
  child.stderr.on("data", (value) => { stderr += value; });
  return {
    child,
    result: new Promise((resolveResult, reject) => {
      child.once("error", reject);
      child.once("exit", (code) => {
        if (code !== 0 || stderr !== "") {
          reject(new Error("bridge child failed"));
          return;
        }
        resolveResult(JSON.parse(stdout));
      });
    }),
  };
}

function runInheritedSequence(pair, payload) {
  const source = `
    import { createIpythonBridge } from ${JSON.stringify(pathToFileURL(artifactPath).href)};
    const payload = JSON.parse(process.argv[1]);
    const bridge = createIpythonBridge(3, payload.options);
    const controller = new AbortController();
    if (payload.abortAfterMs !== undefined) {
      setTimeout(() => controller.abort(), payload.abortAfterMs);
    }
    const attempt = async (requestId, code, signal) => {
      try {
        const result = await bridge.execute(requestId, code, signal);
        return { ok: true, result };
      } catch (error) {
        return { ok: false, message: error instanceof Error ? error.message : "invalid" };
      }
    };
    const code = payload.codeBytes === undefined ? payload.code : "x".repeat(payload.codeBytes);
    const first = await attempt(payload.requestId, code, controller.signal);
    const second = await attempt("followup", "print(1)", undefined);
    process.stdout.write(JSON.stringify({ first, second }));
  `;
  const child = spawn(process.execPath, ["--input-type=module", "-e", source, JSON.stringify(payload)], {
    stdio: ["ignore", "pipe", "pipe", pair.client],
  });
  let stdout = "";
  let stderr = "";
  child.stdout.setEncoding("utf8");
  child.stderr.setEncoding("utf8");
  child.stdout.on("data", (value) => { stdout += value; });
  child.stderr.on("data", (value) => { stderr += value; });
  return new Promise((resolveResult, reject) => {
    child.once("error", reject);
    child.once("exit", (code) => {
      if (code !== 0 || stderr !== "") {
        reject(new Error("bridge child failed"));
        return;
      }
      resolveResult(JSON.parse(stdout));
    });
  });
}

function readJsonLine(socket) {
  return new Promise((resolveLine, reject) => {
    let buffered = Buffer.alloc(0);
    const onData = (chunk) => {
      buffered = Buffer.concat([buffered, chunk]);
      const newline = buffered.indexOf(10);
      if (newline < 0) return;
      socket.off("data", onData);
      try {
        resolveLine(JSON.parse(buffered.subarray(0, newline).toString("utf8")));
      } catch (error) {
        reject(error);
      }
    };
    socket.on("data", onData);
    socket.once("error", reject);
  });
}

test("registers the ipython and P7 application tools", async () => {
  const registered = [];
  process.env.ASTERION_PRIME_IPYTHON_FD = "7";
  register({ registerTool: (tool) => registered.push(tool) });
  const expectedNames = ["ipython", "p7_execute_plan", "p7_workspace"];
  assert.deepEqual(toolNames(), expectedNames);
  assert.deepEqual(registered.map((tool) => tool.name), expectedNames);
  assert.deepEqual(
    registered.slice(1).map((tool) => tool.executionMode),
    registered.slice(1).map(() => "sequential"),
  );
  assert.match(registered.find((tool) => tool.name === "p7_execute_plan").description, /unique Broker.*stops the suffix/);
  assert.match(registered.find((tool) => tool.name === "p7_workspace").description, /Publishing never dispatches actions/);
  assert.equal(registered[0].label, "ipython");
  assert.equal(
    registered[0].description,
    "Execute one bounded persistent Python cell using only the symbols and imports permitted by the active application.",
  );
  assert.doesNotMatch(registered[0].description, /p7_client|puzzle/i);
  assert.equal(registered[0].executionMode, "sequential");
  assert.equal(IsSchema(registered[0].parameters), true);
  assert.deepEqual(registered[0].parameters.required, ["code"]);
  await assert.rejects(registered[0].execute("bad", null), {
    message: "Asterion ipython bridge is unavailable",
  });
  assert.equal(process.env.ASTERION_PRIME_IPYTHON_FD, undefined);
});

test("wraps application tool results for the Pi AgentToolResult contract", async () => {
  const calls = [];
  const fakeBridge = { callMethod: async (...args) => {
    calls.push(args);
    return { available: true, current_level: 2 };
  } };
  const tool = createLegacyAppLevelTools(fakeBridge).find((candidate) => candidate.name === "p7_mechanics_prior");
  assert.ok(tool);
  assert.equal(IsSchema(tool.parameters), true);
  assert.deepEqual(tool.parameters.properties, {});
  assert.equal(tool.parameters.additionalProperties, false);
  assert.match(tool.description, /evidence/i);
  assert.match(tool.description, /not a route/i);
  assert.deepEqual(await tool.execute("mechanics-1", {}), {
    content: [{ type: "text", text: '{"available":true,"current_level":2}' }],
    details: { available: true, current_level: 2 },
  });
  assert.deepEqual(calls, [["mechanics-1", "mechanics_prior", {} , undefined]]);
});

test("passes cognition operations directly through the method bridge", async () => {
  const calls = [];
  const tool = createLegacyAppLevelTools({
    callMethod: async (...args) => {
      calls.push(args);
      return { status: "ok" };
    },
  }).find((candidate) => candidate.name === "p7_cognition_update");
  assert.ok(tool);
  assert.deepEqual(tool.parameters.required, ["op"]);
  assert.deepEqual(await tool.execute("cognition-1", { op: "snapshot" }), {
    content: [{ type: "text", text: '{"status":"ok"}' }],
    details: { status: "ok" },
  });
  assert.deepEqual(calls, [["cognition-1", "cognition_update", { op: "snapshot" }, undefined]]);
});

test("level queries and hypothesis registration expose the Python bridge contract", () => {
  const tools = createLegacyAppLevelTools({ callMethod: async () => ({}) });
  for (const name of ["p7_playbook", "p7_tried_actions", "p7_last_outcome_summary"]) {
    const schema = tools.find((tool) => tool.name === name).parameters;
    assert.equal(schema.required, undefined, name);
    assert.equal(schema.properties.level.anyOf[0].type, "integer", name);
  }
  const hypothesis = tools.find((tool) => tool.name === "p7_record_hypothesis").parameters;
  assert.deepEqual(hypothesis.properties.value.required, ["mechanism", "probe", "dependencies"]);
  assert.equal(hypothesis.properties.value.additionalProperties, false);
});

test("rejects malformed requests before writing", async () => {
  const pair = await socketPair();
  try {
    const bridge = createIpythonBridge(pair.descriptor);
    await assert.rejects(
      bridge.handle({
        protocol: PROTOCOL,
        request_id: "r1",
        type: "execute",
        code: "",
      }),
      { message: "Asterion ipython bridge is unavailable" },
    );
  } finally {
    pair.close();
  }
});

test("uses one strict request and matching result over the descriptor", async () => {
  const pair = await socketPair();
  try {
    const running = runInheritedBridge(pair, {
      requestId: "call-1",
      code: "print(42)",
      options: {},
    });
    const request = await readJsonLine(pair.peer);
    assert.deepEqual(request, {
      code: "print(42)",
      protocol: PROTOCOL,
      request_id: "call-1",
      type: "execute",
    });
    pair.peer.write(
      JSON.stringify({
        protocol: PROTOCOL,
        request_id: "call-1",
        type: "result",
        status: "ok",
        output: "42\n",
      }) + "\n",
    );
    assert.deepEqual(await running.result, {
      ok: true,
      result: {
        content: [{ type: "text", text: "42\n" }],
        details: {},
      },
    });
  } finally {
    pair.close();
  }
});

test("serializes method calls over the single bridge descriptor", async () => {
  const pair = await socketPair();
  try {
    const bridge = createIpythonBridge(pair.descriptor);
    const first = bridge.callMethod("method-1", "observe", {});
    assert.deepEqual(await readJsonLine(pair.peer), {
      method: "observe",
      params: {},
      protocol: PROTOCOL,
      request_id: "method-1",
      type: "method_call",
    });
    const second = bridge.callMethod("method-2", "status", {});
    let secondSettled = false;
    void second.then(() => { secondSettled = true; });
    await new Promise((resolve) => setTimeout(resolve, 20));
    assert.equal(secondSettled, false);
    await new Promise((resolve) => setTimeout(resolve, 100));
    pair.peer.write(JSON.stringify({
      protocol: PROTOCOL,
      request_id: "method-1",
      type: "method_result",
      status: "ok",
      output: '{"first":true}',
    }) + "\n");
    assert.deepEqual(await first, { first: true });
    assert.deepEqual(await readJsonLine(pair.peer), {
      method: "status",
      params: {},
      protocol: PROTOCOL,
      request_id: "method-2",
      type: "method_call",
    });
    await new Promise((resolve) => setTimeout(resolve, 100));
    pair.peer.write(JSON.stringify({
      protocol: PROTOCOL,
      request_id: "method-2",
      type: "method_result",
      status: "ok",
      output: '{"second":true}',
    }) + "\n");
    assert.deepEqual(await second, { second: true });
  } finally {
    pair.close();
  }
});

test("recoverable method errors do not poison the bridge", async () => {
  const pair = await socketPair();
  try {
    const bridge = createIpythonBridge(pair.descriptor);
    const rejected = bridge.callMethod("method-error", "cognition_update", { bad: true });
    assert.deepEqual(await readJsonLine(pair.peer), {
      method: "cognition_update",
      params: { bad: true },
      protocol: PROTOCOL,
      request_id: "method-error",
      type: "method_call",
    });
    await new Promise((resolve) => setTimeout(resolve, 100));
    pair.peer.write(JSON.stringify({
      protocol: PROTOCOL,
      request_id: "method-error",
      type: "method_result",
      status: "error",
      output: "invalid cognition payload",
    }) + "\n");
    await assert.rejects(rejected, { message: "invalid cognition payload" });

    const recovered = bridge.callMethod("method-recovered", "cognition_update", { op: "snapshot" });
    assert.deepEqual(await readJsonLine(pair.peer), {
      method: "cognition_update",
      params: { op: "snapshot" },
      protocol: PROTOCOL,
      request_id: "method-recovered",
      type: "method_call",
    });
    await new Promise((resolve) => setTimeout(resolve, 100));
    pair.peer.write(JSON.stringify({
      protocol: PROTOCOL,
      request_id: "method-recovered",
      type: "method_result",
      status: "ok",
      output: '{"recovered":true}',
    }) + "\n");
    assert.deepEqual(await recovered, { recovered: true });
  } finally {
    pair.close();
  }
});

test("uncertain worker results are redacted and permanently poison the bridge", async (t) => {
  for (const status of ["uncertain"]) {
    await t.test(status, async () => {
      const pair = await socketPair();
      try {
        const running = runInheritedSequence(pair, {
          requestId: `call-${status}`,
          code: "p7_client.act([])",
          options: {},
        });
        await readJsonLine(pair.peer);
        pair.peer.write(JSON.stringify({
          protocol: PROTOCOL,
          request_id: `call-${status}`,
          type: "result",
          status,
          output: "SENTINEL-RAW-WORKER /private/path",
        }) + "\n");
        const result = await running;
        assert.deepEqual(result, {
          first: { ok: false, message: "Asterion ipython bridge is unavailable" },
          second: { ok: false, message: "Asterion ipython bridge is unavailable" },
        });
        assert.equal(JSON.stringify(result).includes("SENTINEL"), false);
        assert.equal(JSON.stringify(result).includes("/private/path"), false);
      } finally {
        pair.close();
      }
    });
  }
});

test("settled Python errors and kernel loss preserve the actor bridge", async () => {
  for (const status of ["python-error", "interrupted", "lost"]) {
  const pair = await socketPair();
  try {
    const running = runInheritedSequence(pair, {requestId: "python-error", code: "raise ValueError()", options: {deadlineMs: 2000}});
    await readJsonLine(pair.peer);
    const error = {execution_status: status, generation: "g1", stdout: "ValueError", stdout_truncated: false, kernel_exports: []};
    pair.peer.write(JSON.stringify({protocol: PROTOCOL, request_id: "python-error", type: "result", status: "error", output: JSON.stringify(error)}) + "\n");
    const next = await Promise.race([readJsonLine(pair.peer),
      new Promise((_resolve, reject) => setTimeout(() => reject(new Error("settled error poisoned bridge")), 2000))]);
    assert.equal(next.request_id, "followup");
    pair.peer.write(JSON.stringify({protocol: PROTOCOL, request_id: "followup", type: "result", status: "ok", output: "1"}) + "\n");
    const result = await running;
    assert.equal(result.first.ok, true);
    assert.equal(JSON.parse(result.first.result.content[0].text).execution_status, status);
    assert.equal(result.second.ok, true);
  } finally { pair.close(); }
  }
});

test("bounded output survives envelope JSON escaping at the output cap", async () => {
  const pair = await socketPair();
  try {
    const running = runInheritedBridge(pair, {requestId: "escaped-output", code: "print(1)", options: {deadlineMs: 2000}});
    await readJsonLine(pair.peer);
    const output = '"'.repeat(64 * 1024);
    pair.peer.write(JSON.stringify({protocol: PROTOCOL, request_id: "escaped-output", type: "result", status: "ok", output}) + "\n");
    const result = await running.result;
    assert.equal(result.ok, true);
    assert.equal(result.result.content[0].text.length, 64 * 1024);
  } finally { pair.close(); }
});

test("post-dispatch invalid UTF-8 text poisons the bridge without disclosure", async () => {
  const pair = await socketPair();
  try {
    const running = runInheritedSequence(pair, {
      requestId: "call-surrogate",
      code: "print(1)",
      options: {},
    });
    await readJsonLine(pair.peer);
    pair.peer.write(Buffer.from(
      `{"protocol":"${PROTOCOL}","request_id":"call-surrogate","type":"result","status":"ok","output":"\\ud800SENTINEL"}\n`,
      "utf8",
    ));
    assert.deepEqual(await running, {
      first: { ok: false, message: "Asterion ipython bridge is unavailable" },
      second: { ok: false, message: "Asterion ipython bridge is unavailable" },
    });
  } finally {
    pair.close();
  }
});

test("abort during a backpressured partial write returns promptly and poisons", async () => {
  const pair = await socketPair();
  try {
    const running = runInheritedSequence(pair, {
      requestId: "call-backpressure",
      codeBytes: 8 * 1024 * 1024,
      abortAfterMs: 20,
      options: {
        deadlineMs: 500,
        maxCodeBytes: 9 * 1024 * 1024,
        maxLineBytes: 10 * 1024 * 1024,
      },
    });
    assert.deepEqual(await Promise.race([
      running,
      new Promise((_resolve, reject) => setTimeout(() => reject(new Error("bridge hung")), 2_000)),
    ]), {
      first: { ok: false, message: "Asterion ipython bridge is unavailable" },
      second: { ok: false, message: "Asterion ipython bridge is unavailable" },
    });
  } finally {
    pair.close();
  }
});

test("rejects mismatched results, oversized output, and cancellation", async (t) => {
  await t.test("mismatched result", async () => {
    const pair = await socketPair();
    try {
      const running = runInheritedBridge(pair, {
        requestId: "call-1",
        code: "print(42)",
        options: {},
      });
      await readJsonLine(pair.peer);
      pair.peer.write(
        JSON.stringify({
          protocol: PROTOCOL,
          request_id: "other",
          type: "result",
          status: "ok",
          output: "42",
        }) + "\n",
      );
      assert.deepEqual(await running.result, {
        ok: false,
        message: "Asterion ipython bridge is unavailable",
      });
    } finally {
      pair.close();
    }
  });

  await t.test("oversized output", async () => {
    const pair = await socketPair();
    try {
      const running = runInheritedBridge(pair, {
        requestId: "call-2",
        code: "print(42)",
        options: { maxOutputBytes: 8 },
      });
      await readJsonLine(pair.peer);
      pair.peer.write(
        JSON.stringify({
          protocol: PROTOCOL,
          request_id: "call-2",
          type: "result",
          status: "ok",
          output: "SENTINEL-OUTPUT",
        }) + "\n",
      );
      assert.deepEqual(await running.result, {
        ok: false,
        message: "Asterion ipython bridge is unavailable",
      });
    } finally {
      pair.close();
    }
  });

  await t.test("cancelled request", async () => {
    const pair = await socketPair();
    try {
      const bridge = createIpythonBridge(pair.descriptor);
      const controller = new AbortController();
      controller.abort();
      await assert.rejects(
        bridge.execute("call-3", "SENTINEL-CODE", controller.signal),
        { message: "Asterion ipython bridge is unavailable" },
      );
    } finally {
      pair.close();
    }
  });
});

test("built artifact is comment-free and loads through the pinned loader", async () => {
  const source = readFileSync(artifactPath);
  const text = source.toString("utf8");
  assert.ok(source.length > 0);
  assert.equal(text.split("\n").some((line) => /^\s*(?:\/\/|\/\*)/.test(line)), false);
  assert.match(text, /from["']node:fs["']/);
  assert.match(text, /from["']node:util["']/);
  assert.doesNotMatch(text, /from["']@/);

  const root = mkdtempSync(join(tmpdir(), "asterion-prime-extension-loader-"));
  const pinnedPath = join(root, "ipython-extension.mjs");
  writeFileSync(pinnedPath, source);
  const descriptor = openSync(pinnedPath, "r");
  unlinkSync(pinnedPath);
  process.env.ASTERION_PI_EXTENSION_SOURCE_FD = String(descriptor);
  process.env.ASTERION_PI_EXTENSION_SOURCE_NAME = "ipython-extension.mjs";
  process.env.ASTERION_PI_EXTENSION_SOURCE_SHA256 = createHash("sha256")
    .update(source)
    .digest("hex");
  process.env.ASTERION_PRIME_IPYTHON_FD = "7";
  const registered = [];
  try {
    // The loader takes the host package from the host's own resolver. Copying
    // the loader beside a stub package supplies that resolver outside Pi.
    const host = join(root, "node_modules", "@earendil-works", "pi-coding-agent");
    mkdirSync(host, { recursive: true });
    writeFileSync(
      join(host, "package.json"),
      JSON.stringify({
        name: "@earendil-works/pi-coding-agent",
        version: "0.0.0",
        type: "module",
        main: "index.js",
        exports: { ".": "./index.js" },
      }),
    );
    writeFileSync(
      join(host, "index.js"),
      'export const buildSessionContext = () => ({ messages: [] });\n'
        + "export const convertToLlm = (messages) => messages;\n"
        + 'export const serializeConversation = () => "";\n',
    );
    const loaderCopy = join(root, "asterion_pi_extension_loader.mjs");
    writeFileSync(loaderCopy, readFileSync(loaderPath));
    const loader = await import(`${pathToFileURL(loaderCopy).href}?task5`);
    await loader.default({ registerTool: (tool) => registered.push(tool) });
    assert.deepEqual(registered.map((tool) => tool.name), ["ipython", "p7_execute_plan", "p7_workspace"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test("Asterion-owned summarization material reproduces the shared parity fixture", () => {
  const fixture = JSON.parse(
    readFileSync(
      resolve("../../../tests/fixtures/asterion_prime_p1/v1/summarization-parity.json"),
    ),
  );
  const material = Object.freeze(fixture.material);
  for (const testCase of fixture.cases) {
    const instruction = summarizeInstruction(
      material, testCase.custom_instructions, testCase.previous_summary);
    assert.equal(instruction, testCase.instruction, testCase.name);
    const encoded = composeSummarizationRequest(
      material, testCase.conversation, instruction, testCase.previous_summary);
    assert.equal(encoded, testCase.request_canonical_json, testCase.name);
    assert.equal(
      createHash("sha256").update(encoded, "utf8").digest("hex"),
      testCase.sha256,
      testCase.name,
    );
  }
  // The turn prefix reuses the same conversation wrapping with its own template.
  const turnPrefix = composeSummarizationRequest(
    material, "prefix body", material.turn_prefix_instruction, null);
  const initialHistory = composeSummarizationRequest(
    material, "prefix body", material.initial_instruction, null);
  assert.notEqual(turnPrefix, initialHistory);
  assert.equal(turnPrefix.includes("<previous-summary>"), false);
  assert.equal(
    JSON.parse(turnPrefix).messages[0].content[0].text.endsWith(material.turn_prefix_instruction),
    true,
  );
});

const WITNESS_PAYLOAD = {
  event: {
    type: "session_before_compact",
    preparation: {
      settings: { enabled: false, reserveTokens: 16384, keepRecentTokens: 256 },
      firstKeptEntryId: "entry-2",
      messagesToSummarize: [{ role: "user", content: [{ type: "text", text: "hello" }] }],
      turnPrefixMessages: [],
      isSplitTurn: false,
      tokensBefore: 12,
    },
    branchEntries: [
      { id: "entry-1", parentId: null, type: "message" },
      { id: "entry-2", parentId: "entry-1", type: "message" },
    ],
  },
};

function runInheritedWitness(pair, payload) {
  const source = `
    import { registerContextWitness } from ${JSON.stringify(pathToFileURL(artifactPath).href)};
    const payload = JSON.parse(process.argv[1]);
    const deps = Object.freeze({
      buildSessionContext: (entries) => ({ messages: entries.at(-1)?.type === "compaction"
        ? [{ role: "compactionSummary", retainedMessageCount: 0 }] : [] }),
      convertToLlm: (messages) => messages,
      serializeConversation: () => "SERIALIZED-CONVERSATION",
    });
    const hooks = new Map();
    const witness = registerContextWitness({ on: (event, hook) => hooks.set(event, hook) }, deps,
      { descriptor: 3, launchNonce: payload.launch, timeoutMs: 2000 });
    let outcome;
    try { outcome = await hooks.get("session_before_compact")(payload.event, { getSystemPrompt: () => "SYSTEM-PROMPT" }); }
    catch { outcome = "threw"; }
    process.stdout.write(JSON.stringify({ outcome: outcome ?? null, closed: witness.closed }));
    process.exit(0);
  `;
  const child = spawn(process.execPath, ["--input-type=module", "-e", source, JSON.stringify(payload)], {
    stdio: ["ignore", "pipe", "pipe", pair.client],
  });
  let stdout = "", stderr = "";
  child.stdout.on("data", (value) => { stdout += value; });
  child.stderr.on("data", (value) => { stderr += value; });
  return {
    result: new Promise((resolveResult, reject) => {
      child.once("error", reject);
      child.once("exit", (code) => {
        if (code !== 0 || stderr !== "") { reject(new Error("witness child failed")); return; }
        resolveResult(JSON.parse(stdout));
      });
    }),
  };
}

function witnessFrame(value) {
  const raw = Buffer.from(canonicalJson(value));
  const header = Buffer.alloc(4);
  header.writeUInt32BE(raw.length);
  return Buffer.concat([header, raw]);
}

function readWitnessFrame(socket, timeoutMs = 5000) {
  return new Promise((resolveFrame, reject) => {
    let pending = Buffer.alloc(0);
    const timer = setTimeout(() => reject(new Error("witness peer timed out")), timeoutMs);
    const onData = (chunk) => {
      pending = Buffer.concat([pending, chunk]);
      if (pending.length < 4 || pending.length < 4 + pending.readUInt32BE(0)) return;
      socket.off("data", onData);
      clearTimeout(timer);
      resolveFrame(JSON.parse(pending.subarray(4).toString("utf8")));
    };
    socket.on("data", onData);
    socket.once("end", () => { clearTimeout(timer); reject(new Error("witness peer closed")); });
    socket.once("close", () => { clearTimeout(timer); reject(new Error("witness peer closed")); });
  });
}

test("the arm frame's native material drives the request the witness proposes", async () => {
  const launch = "a".repeat(64);
  const pair = await socketPair();
  try {
    const running = runInheritedWitness(pair, { ...WITNESS_PAYLOAD, launch, material });
    pair.peer.write(witnessFrame({
      protocol: "asterion.prime-context-witness/v1",
      launch_nonce: launch, command_nonce: "b".repeat(64), authority_sha256: "c".repeat(64),
      phase: "arm", summarization: material,
    }));
    const proposal = await readWitnessFrame(pair.peer);
    assert.equal(proposal.phase, "proposal");
    assert.equal(proposal.first_kept_entry_id, "entry-2");
    assert.equal(proposal.covered_leaf_id, "entry-2");
    assert.equal(proposal.source_kind, "messages");
    assert.equal(proposal.turn_prefix_summary_request, null);
    assert.equal(proposal.private_diagnostics.tokensBefore, 12);
    // The body is assembled from the material the native side sent, not from
    // any prompt this extension carries.
    assert.equal(
      proposal.main_summary_request,
      composeSummarizationRequest(material, "SERIALIZED-CONVERSATION", material.initial_instruction, null),
    );
    pair.peer.write(witnessFrame({
      protocol: "asterion.prime-context-witness/v1",
      launch_nonce: launch, command_nonce: "b".repeat(64), authority_sha256: "c".repeat(64),
      phase: "decision", status: "reject",
    }));
    assert.deepEqual(await running.result, { outcome: { cancel: true }, closed: false });
  } finally {
    pair.close();
  }
});

test("tampered arm material is rejected before any proposal", async () => {
  const launch = "a".repeat(64);
  for (const tampered of [
    { ...material, version: "other" },
    { ...material, initial_instruction: material.initial_instruction + " {conversation}" },
    { ...material, previous_summary_block: "no marker here" },
    (({ system_prompt, ...rest }) => rest)(material),
  ]) {
    const pair = await socketPair();
    try {
      const running = runInheritedWitness(pair, { ...WITNESS_PAYLOAD, launch, material: tampered });
      pair.peer.write(witnessFrame({
        protocol: "asterion.prime-context-witness/v1",
        launch_nonce: launch, command_nonce: "b".repeat(64), authority_sha256: "c".repeat(64),
        phase: "arm", summarization: tampered,
      }));
      await assert.rejects(readWitnessFrame(pair.peer, 400));
      assert.deepEqual(await running.result, { outcome: { cancel: true }, closed: true });
    } finally {
      pair.close();
    }
  }
});

test("P7 decision results lead with Chinese prose and retain exact details", async () => {
  const narrative = "当前游戏认知\n已确认：横条可以移动。\n待验证：接触目标是否过关。";
  for (const name of ["p7_observe", "p7_act_checked", "p7_cognition", "p7_cognition_update", "p7_planning_background"]) {
    const result = { cognition_narrative_zh: narrative, applied_count: 1, observation: {frame: [[1]]}, semantic: {claims: {full: "LEDGER_ONLY"}}, planning_background: {semantic_cognition: {semantic: {claims: "LEDGER_ONLY"}}, revision: {primitive_actions: 1}} };
    const tool = createLegacyAppLevelTools({callMethod: async () => result}).find(t => t.name === name);
    const output = await tool.execute("zh", {});
    assert.ok(output.content[0].text.startsWith(narrative));
    assert.ok(output.content[0].text.includes('"applied_count":1'));
    assert.ok(output.content[0].text.includes("结构化证据（程序校验用）"));
    assert.equal(output.details, result);
    assert.equal(result.semantic.claims.full, "LEDGER_ONLY");
  }
});

 test("passes a public decision summary through its registered method", async () => {
  const calls = [];
  const tool = createLegacyAppLevelTools({callMethod: async (...args) => {calls.push(args); return {status: "recorded", execution_authority: "none"};}}).find(t => t.name === "p7_decision");
  assert.ok(tool);
  assert.deepEqual(tool.parameters.required, ["goal", "basis", "expected"]);
  assert.equal(tool.parameters.properties.goal.maxLength, 600);
  const payload = {goal: "移动", basis: "当前观察", expected: "位置变化"};
  await tool.execute("decision-1", payload);
  assert.deepEqual(calls, [["decision-1", "decision", payload, undefined]]);
});

 test("research tools expose tagged workspace requests and complete actor predictions", async () => {
  const calls = [];
  const tools = createAppLevelTools({callMethod: async (...args) => { calls.push(args); return {status: "published"}; }});
  assert.deepEqual(tools.map(t => t.name), ["p7_execute_plan", "p7_workspace"]);
  assert.equal(IsSchema(P7_WORKSPACE_PARAMETERS), true);
  assert.equal(IsSchema(P7_EXECUTE_PLAN_PARAMETERS), true);
  assert.deepEqual(P7_WORKSPACE_PARAMETERS.anyOf.map(s => s.properties.op.const), ["read", "publish", "checkpoint", "focus"]);
  assert.equal(P7_EXECUTE_PLAN_PARAMETERS.properties.steps.maxItems, 20);
  assert.ok(P7_EXECUTE_PLAN_PARAMETERS.properties.steps.items.properties.expect.properties.cells);
  const request = {op: "read"};
  await tools.find(t => t.name === "p7_workspace").execute("research-1", request);
  assert.deepEqual(calls, [["research-1", "workspace", request, undefined]]);
});
