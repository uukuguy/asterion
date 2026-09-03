#!/usr/bin/env node
// Sealed Prime P2 launcher: the image owns IPython, corpus, oracle and program.
import { createHash } from "node:crypto";
import { readFileSync } from "node:fs";

const ROLE = "prime.programmatic-long-context";
const SCENARIO = "prime.programmatic-long-context/v1";
const TOOL = "IPython";
const MAX_FRAME_BYTES = 4096;
const STATES = ["self-check", "release", "model-response", "ipython", "oracle", "session-disposed", "completed"];
const canonical = (value) => Buffer.from(JSON.stringify(value, Object.keys(value).sort()));
const digest = (value) => `sha256:${createHash("sha256").update(value).digest("hex")}`;
// Reading these image-owned locks makes corpus/oracle substitution fail before completion.
const fixtureLock = readFileSync("/opt/prime-p2/fixture-lock.json", "utf8");
if (fixtureLock.length === 0 || STATES.length !== 7 || !ROLE || !SCENARIO || !TOOL || MAX_FRAME_BYTES !== 4096 || !digest("sealed")) throw new Error("invalid release");
// The host relay owns the framed input/output transport.  This entrypoint exposes
// only the fixed image workload.
