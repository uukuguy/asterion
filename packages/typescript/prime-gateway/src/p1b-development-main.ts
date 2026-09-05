import process from "node:process";
import {
  inheritedP1BDevelopmentSocket,
  P1BDevelopmentBridge,
} from "./p1b-development-bridge.js";

function fail(): never {
  process.stderr.write("p1b bridge failed\n");
  process.exit(1);
}

// macOS injects this locale key even for spawn({ env: {} }); it is not caller authority.
const macosLocale = process.env.__CF_USER_TEXT_ENCODING;
if (process.platform === "darwin" && macosLocale !== undefined) {
  const uid = process.getuid?.();
  if (uid === undefined) fail();
  const prefix = `0x${uid.toString(16).toUpperCase()}:`;
  if (!new RegExp(`^${prefix}0x[0-9A-F]+:0x[0-9A-F]+$`, "i").test(macosLocale)) fail();
  delete process.env.__CF_USER_TEXT_ENCODING;
}
if (Object.keys(process.env).length !== 0) fail();
if (process.argv.length !== 3 || !/^[1-9][0-9]*$/.test(process.argv[2] ?? "")) fail();
const fd = Number(process.argv[2]);
if (!Number.isSafeInteger(fd) || fd < 3) fail();
new P1BDevelopmentBridge(inheritedP1BDevelopmentSocket(fd)).run().catch(() => fail());
