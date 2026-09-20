import test from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const readiness = resolve(repositoryRoot, "gateway/audio-archive/deploy/s10a/readiness.sh");
const priorImage = `sha256:${"a".repeat(64)}`;
const candidateImage = `sha256:${"b".repeat(64)}`;

function fixture() {
  const root = mkdtempSync(join(tmpdir(), "s10a-readiness-"));
  const bin = join(root, "bin");
  mkdirSync(bin);
  const state = join(root, "curl-state");
  const sequence = join(root, "curl-sequence");
  const log = join(root, "readiness.log");
  writeFileSync(state, "0\n");
  writeFileSync(join(bin, "curl"), `#!/usr/bin/env bash
set -eu
index=$(cat "$MOCK_CURL_STATE")
index=$((index + 1))
printf '%s\\n' "$index" >"$MOCK_CURL_STATE"
line=$(sed -n "\${index}p" "$MOCK_CURL_SEQUENCE")
if [[ -z "$line" ]]; then line=$(tail -n 1 "$MOCK_CURL_SEQUENCE"); fi
IFS='|' read -r result http body <<<"$line"
output=
while (($#)); do
  if [[ "$1" == --output ]]; then output=$2; shift 2; else shift; fi
done
[[ -n "$output" ]]
printf '%s' "$body" >"$output"
printf '%s' "$http"
exit "$result"
`);
  writeFileSync(join(bin, "docker"), `#!/usr/bin/env bash
set -eu
[[ "$1" == inspect && "$2" == --type && "$3" == container ]]
printf '%s' "$MOCK_DOCKER_INSPECT"
`);
  chmodSync(join(bin, "curl"), 0o755);
  chmodSync(join(bin, "docker"), 0o755);
  return { root, bin, state, sequence, log };
}

function runPublic(lines, { timeout = 2, extraEnv = {} } = {}) {
  const work = fixture();
  writeFileSync(work.sequence, `${lines.join("\n")}\n`);
  const result = spawnSync(
    "bash",
    ["-c", 'source "$1"; meser_readiness_prepare_log "$2"; meser_wait_public_health https://service.example "$3" test "$2"', "readiness", readiness, work.log, String(timeout)],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        ...extraEnv,
        PATH: `${work.bin}:${process.env.PATH}`,
        MOCK_CURL_STATE: work.state,
        MOCK_CURL_SEQUENCE: work.sequence,
        MESER_READINESS_INTERVAL_SECONDS: "0.01",
        MESER_READINESS_CONNECT_TIMEOUT_SECONDS: "0.05",
        MESER_READINESS_TOTAL_TIMEOUT_SECONDS: "0.05",
      },
    },
  );
  const log = readFileSync(work.log, "utf8");
  const calls = Number(readFileSync(work.state, "utf8").trim());
  rmSync(work.root, { recursive: true, force: true });
  return { ...result, log, calls };
}

function runContainer({ image = priorImage, status = "running", health, policy = "require-healthy" }) {
  const work = fixture();
  const state = { Status: status };
  if (health !== undefined) state.Health = { Status: health };
  const inspect = JSON.stringify([{ Id: "c".repeat(64), Image: image, State: state }]);
  const result = spawnSync(
    "bash",
    ["-c", 'source "$1"; meser_readiness_prepare_log "$2"; meser_wait_container_ready fixture "$3" fixture-service "$4" 1 "$2"', "readiness", readiness, work.log, priorImage, policy],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        PATH: `${work.bin}:${process.env.PATH}`,
        MOCK_DOCKER_INSPECT: inspect,
        MESER_READINESS_INTERVAL_SECONDS: "0.01",
      },
    },
  );
  const log = readFileSync(work.log, "utf8");
  rmSync(work.root, { recursive: true, force: true });
  return { ...result, log };
}

test("retries transient curl 35 and requires two consecutive healthy responses", () => {
  const result = runPublic(["35|000|", '0|200|{"ok":true}', '0|200|{"ok":true}']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.calls, 3);
  assert.match(result.log, /curl=35 http=000 consecutive=0 result=transient/);
  assert.match(result.log, /consecutive=1 result=success-awaiting-confirmation/);
  assert.match(result.log, /consecutive=2 result=ready/);
});

test("retries transient HTTP 503 and then accepts two healthy responses", () => {
  const result = runPublic(["0|503|", '0|200|{"ok":true}', '0|200|{"ok":true}']);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.calls, 3);
  assert.match(result.log, /curl=0 http=503 consecutive=0 result=transient/);
});

test("fails closed immediately for certificate or hostname validation failure", () => {
  const result = runPublic(["60|000|certificate failure"]);
  assert.notEqual(result.status, 0);
  assert.equal(result.calls, 1);
  assert.match(result.log, /curl=60 .*result=contract-failure/);
});

test("fails closed immediately for a non-transient HTTP contract status", () => {
  const result = runPublic(["0|404|not found"]);
  assert.notEqual(result.status, 0);
  assert.equal(result.calls, 1);
  assert.match(result.log, /http=404 .*result=contract-failure/);
});

test("fails closed for a malformed HTTP 200 health response", () => {
  const result = runPublic(["0|200|not-json"]);
  assert.notEqual(result.status, 0);
  assert.equal(result.calls, 1);
  assert.match(result.log, /http=200 .*result=malformed-response/);
});

test("exhausts a monotonic bounded deadline for persistent startup transients", () => {
  const result = runPublic(["35|000|"], { timeout: 1 });
  assert.notEqual(result.status, 0);
  assert.ok(result.calls > 1);
  assert.match(result.log, /result=deadline-exhausted/);
});

test("supports a running Caddy container without State.Health", () => {
  const result = runContainer({ policy: "allow-not-configured" });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.log, /status=running health=not-configured result=ready/);
});

test("requires a healthy gateway container before public readiness", () => {
  const result = runContainer({ health: "healthy" });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.log, /status=running health=healthy result=ready/);
});

test("rejects a candidate image when rollback expects the prior image", () => {
  const result = runContainer({ image: candidateImage, health: "healthy" });
  assert.notEqual(result.status, 0);
  assert.match(result.log, /result=image-mismatch/);
});

test("readiness diagnostics never include response bodies or runtime secrets", () => {
  const secret = "runtime-secret-that-must-not-leak";
  const result = runPublic([`0|404|${secret}`], { extraEnv: { GITHUB_APP_ID: secret, SHARED_PASSWORD: secret } });
  assert.notEqual(result.status, 0);
  assert.doesNotMatch(result.stdout, new RegExp(secret));
  assert.doesNotMatch(result.stderr, new RegExp(secret));
  assert.doesNotMatch(result.log, new RegExp(secret));
});
