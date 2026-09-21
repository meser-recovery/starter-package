#!/usr/bin/env node
import { createHash } from "node:crypto";
import { spawn } from "node:child_process";
import { access, lstat, open } from "node:fs/promises";
import { constants } from "node:fs";
import { isAbsolute } from "node:path";
import { pathToFileURL } from "node:url";

const required = (environment, name) => {
  const value = environment[name];
  if (!value) throw new Error(`${name} is required`);
  return value;
};

async function sha256(path) {
  const handle = await open(path, constants.O_RDONLY | constants.O_NOFOLLOW);
  const hash = createHash("sha256");
  try {
    for await (const chunk of handle.createReadStream({ autoClose: false })) hash.update(chunk);
  } finally { await handle.close(); }
  return hash.digest("hex");
}

async function firstLine(path) {
  return new Promise((resolve, reject) => {
    const child = spawn(path, ["-version"], { shell: false, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = ""; let stderr = "";
    child.stdout.on("data", chunk => { if (stdout.length < 4096) stdout += chunk.toString("utf8", 0, 4096 - stdout.length); });
    child.stderr.on("data", chunk => { if (stderr.length < 4096) stderr += chunk.toString("utf8", 0, 4096 - stderr.length); });
    child.once("error", reject);
    child.once("close", code => code === 0 ? resolve(stdout.split(/\r?\n/, 1)[0]) : reject(new Error(`native version check exited ${code}: ${stderr.trim() || "no diagnostic"}`)));
  });
}

async function verifyBinary(kind, path, expectedHash, version) {
  if (!isAbsolute(path)) throw new Error(`${kind}_BIN must be an absolute path`);
  const info = await lstat(path).catch(() => null);
  if (!info?.isFile() || info.isSymbolicLink()) throw new Error(`${kind} binary is missing, not regular, or a symlink`);
  await access(path, constants.X_OK);
  if (!/^[0-9a-f]{64}$/.test(expectedHash)) throw new Error(`${kind}_SHA256 is malformed`);
  const actualHash = await sha256(path);
  if (actualHash !== expectedHash) throw new Error(`${kind} checksum mismatch`);
  const line = await firstLine(path);
  const expectedPrefix = `${kind.toLowerCase()} version ${version}`;
  if (line !== expectedPrefix && !line.startsWith(`${expectedPrefix} `)) throw new Error(`${kind} exact version mismatch`);
  return actualHash;
}

export async function verifyFfmpegToolchain(environment = process.env) {
  const version = required(environment, "FFMPEG_VERSION");
  if (!/^\d+\.\d+\.\d+$/.test(version)) throw new Error("FFMPEG_VERSION is malformed");
  const ffmpeg = required(environment, "FFMPEG_BIN");
  const ffprobe = required(environment, "FFPROBE_BIN");
  const ffmpegSha256 = await verifyBinary("FFMPEG", ffmpeg, required(environment, "FFMPEG_SHA256"), version);
  const ffprobeSha256 = await verifyBinary("FFPROBE", ffprobe, required(environment, "FFPROBE_SHA256"), version);
  return Object.freeze({ version, ffmpeg, ffprobe, ffmpegSha256, ffprobeSha256 });
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  verifyFfmpegToolchain().then(result => {
    console.log(`FFMPEG_TOOLCHAIN=PASS VERSION=${result.version} FFMPEG_SHA256=${result.ffmpegSha256} FFPROBE_SHA256=${result.ffprobeSha256}`);
  }, error => {
    console.error(`FFMPEG_TOOLCHAIN=REFUSED reason=${error instanceof Error ? error.message : "unknown failure"}`);
    process.exitCode = 1;
  });
}
