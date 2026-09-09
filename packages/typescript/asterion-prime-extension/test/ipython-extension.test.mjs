import assert from "node:assert/strict";
import { spawn } from "node:child_process";
import { createHash } from "node:crypto";
import {
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
  createIpythonBridge,
  toolNames,
} from "../dist/ipython-extension.mjs";

const artifactPath = resolve("dist/ipython-extension.mjs");
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

test("registers exactly the ipython tool", async () => {
  const registered = [];
  process.env.ASTERION_PRIME_IPYTHON_FD = "7";
  register({ registerTool: (tool) => registered.push(tool) });
  assert.deepEqual(toolNames(), ["ipython"]);
  assert.deepEqual(registered.map((tool) => tool.name), ["ipython"]);
  assert.equal(registered[0].label, "ipython");
  assert.equal(registered[0].executionMode, "sequential");
  assert.equal(IsSchema(registered[0].parameters), true);
  assert.deepEqual(registered[0].parameters.required, ["code"]);
  await assert.rejects(registered[0].execute("bad", null), {
    message: "Asterion ipython bridge is unavailable",
  });
  assert.equal(process.env.ASTERION_PRIME_IPYTHON_FD, undefined);
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

test("non-ok worker results are redacted and permanently poison the bridge", async (t) => {
  for (const status of ["error", "uncertain"]) {
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
    const loader = await import(`${new URL(`file://${loaderPath}`).href}?task5`);
    await loader.default({ registerTool: (tool) => registered.push(tool) });
    assert.deepEqual(registered.map((tool) => tool.name), ["ipython"]);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
