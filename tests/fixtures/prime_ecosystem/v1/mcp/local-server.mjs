#!/usr/bin/env node
import { createInterface } from "node:readline";

const SERVER_ID = "ecosystem-mcp-local";
const VERSION = "1.0.0";
const CHALLENGE_DIGEST = "171d8a72511c85d1573964f8a10f4f31e11def2eb2e9eedf7d6feff628a9f9cc";
const CREDENTIAL = "opaque-mcp-refresh-token";

const largeOutput = process.argv.includes("--large-output");
const partialLine = process.argv.includes("--partial-line");
const stderrFlood = process.argv.includes("--stderr-flood");
let initialized = false;

function write(value) {
  process.stdout.write(`${JSON.stringify(value)}\n`);
}

const lines = createInterface({ input: process.stdin });
lines.on("line", (line) => {
  if (partialLine) {
    process.stdout.write("{\"type\":\"auth_challenge\"");
    return;
  }
  if (stderrFlood) {
    process.stderr.write("x".repeat(16384));
    return;
  }
  let message;
  try {
    message = JSON.parse(line);
  } catch {
    write({ type: "error" });
    return;
  }
  if (message.type === "initialize" && message.credential === undefined) {
    if (
      message.server_id !== SERVER_ID ||
      message.version !== VERSION ||
      typeof message.lease_id !== "string" ||
      typeof message.discovery_digest !== "string"
    ) {
      write({ type: "error" });
      return;
    }
    write({
      type: "auth_challenge",
      server_id: SERVER_ID,
      challenge_digest: CHALLENGE_DIGEST,
    });
    return;
  }
  if (message.type === "initialize" && message.credential !== undefined) {
    if (
      message.server_id !== SERVER_ID ||
      message.version !== VERSION ||
      message.credential !== CREDENTIAL
    ) {
      write({ type: "error" });
      return;
    }
    initialized = true;
    write({ type: "initialized", server_id: SERVER_ID });
    return;
  }
  if (message.type === "list") {
    if (!initialized) {
      write({ type: "error" });
      return;
    }
    if (largeOutput) {
      write({ type: "list_result", tool_count: 1, padding: "x".repeat(16384) });
      return;
    }
    write({ type: "list_result", tool_count: 1, resource_count: 1 });
    return;
  }
  if (message.type === "shutdown") {
    lines.close();
    process.exitCode = 0;
    return;
  }
  write({ type: "error" });
});
