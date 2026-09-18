import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFileSync, readdirSync, statSync } from "node:fs";
import { dirname, extname, relative, resolve } from "node:path";

const repositoryRoot = resolve(import.meta.dirname, "../..");
const frontendRoot = resolve(repositoryRoot, "service/frontend");
const allowlistPath = resolve(frontendRoot, "asset-allowlist.txt");
const normalize = path => path.replaceAll("\\", "/");

function walk(directory) {
  return readdirSync(directory).flatMap(name => {
    const path = resolve(directory, name);
    return statSync(path).isDirectory() ? walk(path) : [normalize(relative(repositoryRoot, path))];
  });
}

const allowed = readFileSync(allowlistPath, "utf8").trim().split("\n").sort();
const actual = walk(frontendRoot).sort();
assert.deepEqual(actual, allowed, "protected frontend tree must exactly match asset-allowlist.txt");

for (const [path, expected] of Object.entries({
  "service/frontend/vendor/ffmpeg/core/ffmpeg-core.js": "67a48f11645f85439f3fde4f2119042c16b374b910206b7a7a24f342e28dcae3",
  "service/frontend/vendor/ffmpeg/ffmpeg/classes.js": "7a829c898bdbc3a8806652a5502d9101178ce4e988a2c50b3abc1306ce4fc919"
})) {
  const digest = createHash("sha256").update(readFileSync(resolve(repositoryRoot, path))).digest("hex");
  assert.equal(digest, expected, `vendored upstream bytes changed: ${path}`);
}

const entryPoints = actual.filter(path => extname(path) === ".html");
assert.deepEqual(entryPoints, [
  "service/frontend/Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html",
  "service/frontend/Audio-Archive.html",
  "service/frontend/Audio-Editor.html",
  "service/frontend/Calendar.html",
  "service/frontend/Google-Drive.html",
  "service/frontend/index.html",
  "service/frontend/login.html"
]);

for (const path of actual) {
  assert.doesNotMatch(path, /(?:^|\/)(?:\.env|.*(?:secret|credential|private[-_.]?key|cookie|token|\.pem))(?:$|\/)/i, `secret-like file is forbidden: ${path}`);
  const extension = extname(path);
  if (![".html", ".css", ".js", ".mjs"].includes(extension)) continue;
  const text = readFileSync(resolve(repositoryRoot, path), "utf8");
  assert.doesNotMatch(text, /StorageAccess|hasStorageAccess|requestStorageAccess|storage-access-bridge|safari-bootstrap|meser-storage-access|__Host-meser_audio_(?:session|storage_session)|meser_service_access_v1|SALTED_PASSWORD_VERIFIER/,
    `superseded auth surface is forbidden: ${path}`);
  if (extension === ".html") assert.match(text, /scripts\/origin-guard\.js/, `origin guard missing: ${path}`);

  const references = [];
  if (extension === ".html") {
    for (const match of text.matchAll(/(?:src|href)="([^"]+)"/g)) references.push(match[1]);
  }
  if ([".js", ".mjs"].includes(extension)) {
    for (const match of text.matchAll(/(?:from\s+|import\s*\(|new URL\s*\()\s*["'](\.{1,2}\/[^"']+)["']/g)) references.push(match[1]);
  }
  if (extension === ".css") {
    for (const match of text.matchAll(/url\(["']?([^"')]+)["']?\)/g)) references.push(match[1]);
  }
  for (const reference of references) {
    if (/^(?:https?:|data:|blob:|#|\/)/.test(reference)) continue;
    const clean = reference.split(/[?#]/, 1)[0];
    if (clean === "." || clean === "./") continue;
    const target = normalize(relative(repositoryRoot, resolve(repositoryRoot, dirname(path), clean)));
    assert.ok(allowed.includes(target), `referenced asset is absent from allowlist: ${path} -> ${target}`);
  }
}

console.log(`Protected frontend inventory: PASS (${actual.length} allowlisted files)`);
