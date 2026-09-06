import process from "node:process";
import {
  inheritedP7DevelopmentSocket,
  P7DevelopmentBridge,
} from "./p7-development-bridge.js";

function fail(): never {
  process.stderr.write("p7 bridge failed\n");
  process.exit(1);
}

// macOS injects this locale key even for spawn({ env: {} }); it is not caller authority.
const macosLocale = process.env.__CF_USER_TEXT_ENCODING;
if (process.platform === "darwin" && macosLocale !== undefined) {
  const uid = process.getuid?.();
  if (uid === undefined) fail();
  const prefix = `0x${uid.toString(16).toUpperCase()}:`;
  if (!new RegExp(`^${prefix}0x[0-9A-F]+:0x[0-9A-F]+$`, "i").test(macosLocale))
    fail();
  delete process.env.__CF_USER_TEXT_ENCODING;
}
if (Object.keys(process.env).length !== 0) fail();
if (process.argv.length !== 3 || !/^[1-9][0-9]*$/.test(process.argv[2] ?? ""))
  fail();
const fd = Number(process.argv[2]);
if (!Number.isSafeInteger(fd) || fd < 3) fail();
new P7DevelopmentBridge(inheritedP7DevelopmentSocket(fd))
  .run()
  .catch(() => fail());
