import process from "node:process";
import { inheritedP7SolvingSocket, P7SolvingBridge } from "./p7-solving-bridge.js";

function fail(error?: unknown): never {
  const kind = error instanceof Error ? error.name : typeof error;
  process.stderr.write(`p7 solving bridge failed:${kind}\n`);
  process.exit(1);
}
const macosLocale = process.env.__CF_USER_TEXT_ENCODING;
if (process.platform === "darwin" && macosLocale !== undefined) {
  const uid = process.getuid?.(); if (uid === undefined) fail();
  const prefix = `0x${uid.toString(16).toUpperCase()}:`;
  if (!new RegExp(`^${prefix}0x[0-9A-F]+:0x[0-9A-F]+$`, "i").test(macosLocale)) fail();
  delete process.env.__CF_USER_TEXT_ENCODING;
}
if (Object.keys(process.env).length !== 0) fail();
if (process.argv.length !== 3 || !/^[1-9][0-9]*$/.test(process.argv[2] ?? "")) fail();
const fd = Number(process.argv[2]); if (!Number.isSafeInteger(fd) || fd < 3) fail();
new P7SolvingBridge(inheritedP7SolvingSocket(fd)).run().catch((error: unknown) => fail(error));
