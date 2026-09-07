import test from "node:test";
import assert from "node:assert/strict";
import { generateKeyPairSync, verify } from "node:crypto";
import { mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { loadConfig } from "../src/config.mjs";
import { createGitHubAppJwt, GitHubArchiveRepository } from "../src/github.mjs";

const { privateKey, publicKey } = generateKeyPairSync("rsa", { modulusLength: 2048 });
const pem = privateKey.export({ type: "pkcs8", format: "pem" });

function config(overrides = {}) {
  return {
    storageOwner: "meser-recovery", storageRepository: "audio-archive", storageBranch: "main",
    githubAppId: "123", githubAppInstallationId: "456", githubAppPrivateKey: pem, ...overrides
  };
}

function jsonResponse(value, status = 200) {
  return new Response(value === null ? null : JSON.stringify(value), { status,
    headers: value === null ? {} : { "Content-Type": "application/json" } });
}

function configEnvironment(overrides = {}) {
  return {
    ALLOWED_ORIGIN: "https://meser-recovery.github.io", GITHUB_APP_ID: "1", GITHUB_APP_INSTALLATION_ID: "2",
    GITHUB_APP_PRIVATE_KEY_FILE: "/run/secrets/github-app.pem",
    SHARED_PASSWORD_VERIFIER_FILE: "/run/secrets/shared-password-verifier",
    SESSION_SIGNING_SECRET_FILE: "/run/secrets/session-signing-secret",
    ...overrides
  };
}

function secretReader(overrides = {}) {
  const values = {
    "/run/secrets/github-app.pem": "line one\nline two\n",
    "/run/secrets/shared-password-verifier": "test-password-verifier\n",
    "/run/secrets/session-signing-secret": "x".repeat(32) + "\n",
    ...overrides
  };
  return (filename) => {
    if (!Object.hasOwn(values, filename)) throw new Error("unreadable");
    return values[filename];
  };
}

test("configuration fixes GitHub scope and accepts one exact HTTPS Pages origin", () => {
  const env = configEnvironment();
  const loaded = loadConfig(env, secretReader());
  assert.equal(`${loaded.storageOwner}/${loaded.storageRepository}`, "meser-recovery/audio-archive");
  assert.throws(() => loadConfig({ ...env, STORAGE_REPOSITORY: "starter-package" }, secretReader()), /must remain/);
  assert.throws(() => loadConfig({ ...env, ALLOWED_ORIGIN: "http://localhost:8000" }, secretReader()), /HTTPS origin/);
  assert.throws(() => loadConfig({ ...env, ALLOWED_ORIGIN: "https://example.test/path" }, secretReader()), /HTTPS origin/);
  assert.throws(() => loadConfig({ ...env, ALLOWED_ORIGIN: "https://example.test" }, secretReader()), /must remain/);
});

test("configuration reads each secret file once, preserves PEM newlines, and strips only the final newline", () => {
  const calls = [];
  const reader = secretReader();
  const loaded = loadConfig(configEnvironment(), (filename, encoding) => {
    calls.push([filename, encoding]);
    return reader(filename);
  });
  assert.equal(loaded.githubAppPrivateKey, "line one\nline two");
  assert.equal(loaded.sharedPasswordVerifier, "test-password-verifier");
  assert.equal(loaded.sessionSigningSecret, "x".repeat(32));
  assert.deepEqual(calls, [
    ["/run/secrets/github-app.pem", "utf8"],
    ["/run/secrets/shared-password-verifier", "utf8"],
    ["/run/secrets/session-signing-secret", "utf8"]
  ]);
});

test("configuration loads startup secrets from real files", () => {
  const directory = mkdtempSync(join(tmpdir(), "audio-archive-config-"));
  try {
    const env = configEnvironment({
      GITHUB_APP_PRIVATE_KEY_FILE: join(directory, "github-app.pem"),
      SHARED_PASSWORD_VERIFIER_FILE: join(directory, "shared-password-verifier"),
      SESSION_SIGNING_SECRET_FILE: join(directory, "session-signing-secret")
    });
    writeFileSync(env.GITHUB_APP_PRIVATE_KEY_FILE, "test-key-line-one\ntest-key-line-two\n", { mode: 0o600 });
    writeFileSync(env.SHARED_PASSWORD_VERIFIER_FILE, "test-verifier\n", { mode: 0o600 });
    writeFileSync(env.SESSION_SIGNING_SECRET_FILE, "z".repeat(32) + "\n", { mode: 0o600 });
    const loaded = loadConfig(env);
    assert.equal(loaded.githubAppPrivateKey, "test-key-line-one\ntest-key-line-two");
    assert.equal(loaded.sharedPasswordVerifier, "test-verifier");
    assert.equal(loaded.sessionSigningSecret, "z".repeat(32));
  } finally {
    rmSync(directory, { recursive: true, force: true });
  }
});

test("configuration fails closed without disclosing unreadable or empty secret contents", () => {
  const env = configEnvironment();
  assert.throws(() => loadConfig({ ...env, GITHUB_APP_PRIVATE_KEY_FILE: "" }, secretReader()),
    (error) => /GITHUB_APP_PRIVATE_KEY_FILE is required/.test(error.message) && !error.message.includes("line one"));
  assert.throws(() => loadConfig(env, secretReader({ "/run/secrets/shared-password-verifier": " \n" })),
    (error) => /SHARED_PASSWORD_VERIFIER_FILE is empty/.test(error.message) && !error.message.includes("test-password"));
  assert.throws(() => loadConfig(env, secretReader({ "/run/secrets/session-signing-secret": undefined })),
    (error) => /SESSION_SIGNING_SECRET_FILE did not contain text/.test(error.message));
  assert.throws(() => loadConfig(env, () => { throw new Error("private material"); }),
    (error) => /GITHUB_APP_PRIVATE_KEY_FILE could not be read/.test(error.message) && !error.message.includes("private material"));
});

test("GitHub App JWT is short-lived RS256 and installation request is machine-only", async () => {
  const now = 1_800_000_000_000;
  const jwt = createGitHubAppJwt("123", pem, now);
  const [header, payload, signature] = jwt.split(".");
  assert.deepEqual(JSON.parse(Buffer.from(header, "base64url")), { alg: "RS256", typ: "JWT" });
  const claims = JSON.parse(Buffer.from(payload, "base64url"));
  assert.equal(claims.iss, "123");
  assert.equal(claims.exp - claims.iat, 540);
  assert.equal(verify("RSA-SHA256", Buffer.from(`${header}.${payload}`), publicKey, Buffer.from(signature, "base64url")), true);
  let request;
  const repository = new GitHubArchiveRepository(config(), async (url, options) => {
    request = { url, options };
    return jsonResponse({ token: "installation-token", expires_at: "2099-01-01T00:00:00Z" });
  }, () => now);
  assert.equal(await repository.token(), "installation-token");
  assert.equal(request.url, "https://api.github.com/app/installations/456/access_tokens");
  assert.match(request.options.headers.Authorization, /^Bearer /);
});

test("atomic JSON commit stays inside fixed repository and rejects arbitrary paths", async () => {
  const seen = [];
  let blob = 0;
  const repository = new GitHubArchiveRepository(config(), async (url, options = {}) => {
    seen.push({ url, method: options.method || "GET", body: options.body && JSON.parse(options.body) });
    if (url.endsWith("/git/ref/heads/main")) return jsonResponse({ object: { sha: "head-1" } });
    if (url.endsWith("/git/commits/head-1")) return jsonResponse({ tree: { sha: "tree-1" } });
    if (url.endsWith("/git/blobs")) return jsonResponse({ sha: `blob-${++blob}` }, 201);
    if (url.endsWith("/git/trees")) return jsonResponse({ sha: "tree-2" }, 201);
    if (url.endsWith("/git/commits")) return jsonResponse({ sha: "commit-2" }, 201);
    if (url.endsWith("/git/refs/heads/main")) return jsonResponse({ object: { sha: "commit-2" } });
    throw new Error(`unexpected ${url}`);
  });
  repository.installationToken = { value: "installation-token", expiresAt: Number.MAX_SAFE_INTEGER };
  await repository.commitJson("head-1", { "catalog.json": { schemaVersion: 1 }, "sessions/11111111-1111-4111-8111-111111111111.json": { id: "x" } }, "atomic");
  assert.ok(seen.every(({ url }) => url.includes("/repos/meser-recovery/audio-archive/")));
  const tree = seen.find(({ url }) => url.endsWith("/git/trees"));
  assert.equal(tree.body.tree.length, 2);
  assert.equal(seen.at(-1).method, "PATCH");
  await assert.rejects(() => repository.readJson("../../starter-package/secrets.json", "head-1"), /Unsafe/);
});

test("canonical ingestion transaction paths use their structural UUID", async () => {
  const transactionId = "11111111-1111-4111-8111-111111111111";
  const transactionPath = `transactions/ingest-${transactionId}.json`;
  const stored = { id: transactionId, kind: "ingest", status: "planned" };
  const seen = [];
  const repository = new GitHubArchiveRepository(config(), async (url, options = {}) => {
    const body = options.body && JSON.parse(options.body);
    seen.push({ url, method: options.method || "GET", body });
    if (url.includes(`/contents/${transactionPath}?ref=head-1`)) {
      return jsonResponse({ type: "file", encoding: "base64", content: Buffer.from(JSON.stringify(stored)).toString("base64"), sha: "transaction-blob" });
    }
    if (url.endsWith("/git/ref/heads/main")) return jsonResponse({ object: { sha: "head-1" } });
    if (url.endsWith("/git/commits/head-1")) return jsonResponse({ tree: { sha: "tree-1" } });
    if (url.endsWith("/git/blobs")) return jsonResponse({ sha: "blob-1" }, 201);
    if (url.endsWith("/git/trees")) return jsonResponse({ sha: "tree-2" }, 201);
    if (url.endsWith("/git/commits")) return jsonResponse({ sha: "commit-2" }, 201);
    if (url.endsWith("/git/refs/heads/main")) return jsonResponse({ object: { sha: "commit-2" } });
    throw new Error(`unexpected ${url}`);
  });
  repository.installationToken = { value: "installation-token", expiresAt: Number.MAX_SAFE_INTEGER };

  assert.deepEqual(await repository.readJson(transactionPath, "head-1"), { data: stored, blobSha: "transaction-blob" });
  assert.equal(await repository.commitJson("head-1", { [transactionPath]: stored }, "persist ingestion"), "commit-2");
  const tree = seen.find(({ url }) => url.endsWith("/git/trees"));
  assert.deepEqual(tree.body.tree.map(({ path }) => path), [transactionPath]);

  const callsBeforeRejection = seen.length;
  await assert.rejects(
    () => repository.readJson("transactions/ingest-11111111-1111-0111-8111-111111111111.json", "head-1"),
    /Unsafe internal UUID path/
  );
  assert.equal(seen.length, callsBeforeRejection);
});

test("release asset upload uses opaque deterministic name and fixed upload host", async () => {
  let seen;
  const repository = new GitHubArchiveRepository(config(), async (url, options) => {
    seen = { url, options };
    return jsonResponse({ id: 7, name: "blob-11111111-1111-4111-8111-111111111111-part-0001.bin", size: 3 }, 201);
  });
  repository.installationToken = { value: "installation-token", expiresAt: Number.MAX_SAFE_INTEGER };
  await repository.uploadReleaseAsset(9, "blob-11111111-1111-4111-8111-111111111111-part-0001.bin", Buffer.from("abc"));
  assert.equal(seen.url, "https://uploads.github.com/repos/meser-recovery/audio-archive/releases/9/assets?name=blob-11111111-1111-4111-8111-111111111111-part-0001.bin");
  assert.equal(seen.options.headers["Content-Length"], "3");
  await assert.rejects(() => repository.uploadReleaseAsset(9, "recording.mp3", Buffer.from("abc")), /Unsafe/);
});
