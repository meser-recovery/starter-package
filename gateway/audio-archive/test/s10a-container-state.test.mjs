import test from "node:test";
import assert from "node:assert/strict";
import { chmodSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";
import { spawnSync } from "node:child_process";

const repositoryRoot = resolve(import.meta.dirname, "../../..");
const captureScript = resolve(repositoryRoot, "gateway/audio-archive/deploy/s10a/capture-container-state.sh");
const containerId = "a".repeat(64);
const imageId = `sha256:${"b".repeat(64)}`;

function inspectFixture({ json = "", dockerExit = 0, pipefail = false }) {
  const fixture = mkdtempSync(join(tmpdir(), "s10a-container-state-"));
  const bin = join(fixture, "bin");
  const output = join(fixture, "captured-state");
  mkdirSync(bin);
  const docker = join(bin, "docker");
  writeFileSync(docker, `#!/usr/bin/env bash
set -eu
[[ "$1" == inspect && "$2" == --type && "$3" == container && -n "$4" ]]
if [[ "\${MOCK_DOCKER_EXIT:-0}" != 0 ]]; then exit "$MOCK_DOCKER_EXIT"; fi
printf '%s' "\${MOCK_DOCKER_JSON:-}"
`);
  chmodSync(docker, 0o755);

  const args = pipefail
    ? ["-o", "pipefail", captureScript, "fixture-container", output]
    : [captureScript, "fixture-container", output];
  const result = spawnSync("bash", args, {
    encoding: "utf8",
    env: {
      ...process.env,
      PATH: `${bin}:${process.env.PATH}`,
      MOCK_DOCKER_JSON: json,
      MOCK_DOCKER_EXIT: String(dockerExit),
    },
  });
  let captured = null;
  try {
    captured = readFileSync(output, "utf8");
  } catch {
    // A refused capture must not leave a partial output file.
  }
  rmSync(fixture, { recursive: true, force: true });
  return { ...result, captured };
}

function containerJson({ status = "running", health = "healthy", image = imageId } = {}) {
  const state = { Status: status };
  if (health !== null) state.Health = { Status: health };
  return JSON.stringify([{ Id: containerId, Image: image, State: state }]);
}

test("captures a running gateway with its exact healthy state", () => {
  const result = inspectFixture({ json: containerJson() });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.captured, `container_id=${containerId}\nimage_id=${imageId}\nstatus=running\nhealth_status=healthy\n`);
});

test("captures a running healthless Caddy as explicitly not-configured", () => {
  const result = inspectFixture({ json: containerJson({ health: null }) });
  assert.equal(result.status, 0, result.stderr);
  assert.equal(result.captured, `container_id=${containerId}\nimage_id=${imageId}\nstatus=running\nhealth_status=not-configured\n`);
});

test("preserves an exited container status without inventing health", () => {
  const result = inspectFixture({ json: containerJson({ status: "exited", health: null }) });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.captured, /^status=exited$/m);
  assert.match(result.captured, /^health_status=not-configured$/m);
});

test("rejects empty and malformed inspect results without partial state", async (t) => {
  for (const [name, json] of [
    ["empty", ""],
    ["invalid JSON", "not-json"],
    ["empty array", "[]"],
    ["missing State", JSON.stringify([{ Id: containerId, Image: imageId }])],
    ["malformed Health", JSON.stringify([{ Id: containerId, Image: imageId, State: { Status: "running", Health: null } }])],
  ]) {
    await t.test(name, () => {
      const result = inspectFixture({ json });
      assert.notEqual(result.status, 0);
      assert.equal(result.captured, null);
    });
  }
});

test("rejects docker inspect non-zero without masking the error", () => {
  const result = inspectFixture({ json: containerJson(), dockerExit: 42 });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /docker inspect failed/);
  assert.equal(result.captured, null);
});

test("rejects an absent image ID", () => {
  const result = inspectFixture({ json: containerJson({ image: "" }) });
  assert.notEqual(result.status, 0);
  assert.equal(result.captured, null);
});

test("preserves exact container and image identities for rollback", () => {
  const result = inspectFixture({ json: containerJson({ health: "unhealthy" }) });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.captured, new RegExp(`^container_id=${containerId}$`, "m"));
  assert.match(result.captured, new RegExp(`^image_id=${imageId}$`, "m"));
  assert.match(result.captured, /^health_status=unhealthy$/m);
});

test("capture succeeds under set -o pipefail without a short-circuit pipeline", () => {
  const result = inspectFixture({ json: containerJson({ health: null }), pipefail: true });
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.captured, /^health_status=not-configured$/m);
});
