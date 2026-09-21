import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { chmod, mkdtemp, readFile, readdir, rm, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const repository = resolve(import.meta.dirname, "../..");
const verifier = join(repository, "gateway/audio-archive/tools/verify-ffmpeg-toolchain.mjs");
const generator = join(repository, "tests/safety/fixtures/generate-s10a-real-mobile-waveform-fixture.sh");
const sha256 = bytes => createHash("sha256").update(bytes).digest("hex");

async function executable(path, source) {
  await writeFile(path, source, { mode: 0o700 }); await chmod(path, 0o700);
  return sha256(await readFile(path));
}

async function fixture() {
  const root = await mkdtemp(join(tmpdir(), "meser pinned toolchain "));
  const ffmpeg = join(root, "ffmpeg pinned binary");
  const ffprobe = join(root, "ffprobe pinned binary");
  const ffmpegSha = await executable(ffmpeg, `#!/bin/sh
if [ "\${1:-}" = -version ]; then echo 'ffmpeg version 8.1.2 synthetic-regression'; exit 0; fi
last=
for argument in "$@"; do last=$argument; done
[ -n "$last" ] || exit 9
printf 'ftyp synthetic mp4a fixture\n' >"$last"
`);
  const ffprobeSha = await executable(ffprobe, `#!/bin/sh
[ "\${1:-}" = -version ] || exit 8
echo 'ffprobe version 8.1.2 synthetic-regression'
`);
  const env = { ...process.env, FFMPEG_BIN: ffmpeg, FFPROBE_BIN: ffprobe, FFMPEG_VERSION: "8.1.2",
    FFMPEG_SHA256: ffmpegSha, FFPROBE_SHA256: ffprobeSha };
  return { root, ffmpeg, ffprobe, env };
}

const verify = environment => spawnSync(process.execPath, [verifier], { env: environment, encoding: "utf8", shell: false });

test("pinned tools in a nonstandard path with spaces verify and drive fixture generation", async () => {
  const item = await fixture(); const destination = join(item.root, "generated fixture with spaces");
  try {
    const checked = verify(item.env);
    assert.equal(checked.status, 0, checked.stderr); assert.match(checked.stdout, /FFMPEG_TOOLCHAIN=PASS VERSION=8\.1\.2/);
    const generated = spawnSync("/bin/sh", [generator, destination], { env: item.env, encoding: "utf8", shell: false });
    assert.equal(generated.status, 0, generated.stderr);
    assert.deepEqual((await readdir(destination)).sort(), ["track-1.m4a", "track-2.m4a", "track-3.m4a"]);
  } finally { await rm(item.root, { recursive: true, force: true }); }
});

test("toolchain verifier fails closed for a missing variable or binary", async () => {
  const item = await fixture();
  try {
    const withoutVariable = { ...item.env }; delete withoutVariable.FFMPEG_BIN;
    assert.match(verify(withoutVariable).stderr, /FFMPEG_BIN is required/);
    assert.notEqual(verify(withoutVariable).status, 0);
    const missing = { ...item.env, FFMPEG_BIN: join(item.root, "missing ffmpeg") };
    const result = verify(missing); assert.notEqual(result.status, 0); assert.match(result.stderr, /binary is missing/);
  } finally { await rm(item.root, { recursive: true, force: true }); }
});

test("toolchain verifier rejects checksum mismatch before execution", async () => {
  const item = await fixture();
  try {
    const result = verify({ ...item.env, FFMPEG_SHA256: "0".repeat(64) });
    assert.notEqual(result.status, 0); assert.match(result.stderr, /FFMPEG checksum mismatch/);
  } finally { await rm(item.root, { recursive: true, force: true }); }
});

test("toolchain verifier rejects wrong FFmpeg and FFprobe versions", async () => {
  const item = await fixture();
  try {
    const wrongFfmpeg = await executable(item.ffmpeg, "#!/bin/sh\necho 'ffmpeg version 8.1.1'\n");
    let result = verify({ ...item.env, FFMPEG_SHA256: wrongFfmpeg });
    assert.notEqual(result.status, 0); assert.match(result.stderr, /FFMPEG exact version mismatch/);
    const restoredFfmpeg = await executable(item.ffmpeg, "#!/bin/sh\necho 'ffmpeg version 8.1.2'\n");
    const wrongFfprobe = await executable(item.ffprobe, "#!/bin/sh\necho 'ffprobe version 8.1.1'\n");
    result = verify({ ...item.env, FFMPEG_SHA256: restoredFfmpeg, FFPROBE_SHA256: wrongFfprobe });
    assert.notEqual(result.status, 0); assert.match(result.stderr, /FFPROBE exact version mismatch/);
  } finally { await rm(item.root, { recursive: true, force: true }); }
});
