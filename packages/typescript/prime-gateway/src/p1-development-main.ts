import process from "node:process";
import { inheritedP1DevelopmentSocket, P1DevelopmentBridge } from "./p1-development-bridge.js";

function fail(): never { process.stderr.write("p1 bridge failed\n"); process.exit(1); }

if (Object.keys(process.env).some((key) => /(?:key|token|secret|password|credential|^aws_|anthropic|openai)/i.test(key))) fail();
if (process.argv.length !== 3 || !/^[1-9][0-9]*$/.test(process.argv[2] ?? "")) fail();
const fd = Number(process.argv[2]);
if (!Number.isSafeInteger(fd) || fd < 3) fail();
new P1DevelopmentBridge(inheritedP1DevelopmentSocket(fd)).run().catch(() => fail());
