import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const repositoryRoot = resolve(root, "../..");
const deploy = resolve(root, "deploy/self-hosted");
const read = (path) => readFileSync(path, "utf8");
const compose = read(resolve(deploy, "compose.yaml"));
const caddy = read(resolve(deploy, "Caddyfile"));
const haproxy = read(resolve(deploy, "haproxy.cfg"));
const runbook = read(resolve(root, "PROVISIONING.md"));

function serviceBlock(name, next) {
  const end = next ? `\n  ${next}:` : "\nnetworks:";
  const match = compose.match(new RegExp(`\\n  ${name}:\\n([\\s\\S]*?)${end}`));
  assert.ok(match, `${name} service block is missing`);
  return match[1];
}

test("self-hosted Compose isolates gateway ports, networks, and file secrets", () => {
  const gateway = serviceBlock("gateway", "caddy");
  const proxy = serviceBlock("caddy");
  assert.match(gateway, /user: "1000:0"/);
  assert.match(gateway, /expose:\n\s+- "8080"/);
  assert.doesNotMatch(gateway, /\n\s+ports:/);
  assert.doesNotMatch(gateway, /network_mode|privileged:/);
  assert.match(gateway, /no-new-privileges:true/);
  assert.match(gateway, /archive_private/);
  assert.match(proxy, /image: caddy:2\.11\.4-alpine/);
  assert.match(proxy, /- "80:80\/tcp"/);
  assert.match(proxy, /- "127\.0\.0\.1:9443:443\/tcp"/);
  assert.doesNotMatch(proxy, /- "443:443/);
  assert.match(proxy, /archive_private/);
  assert.doesNotMatch(proxy, /\n\s+secrets:/);
  assert.doesNotMatch(compose, /network_mode:\s*host/);
  for (const path of ["github-app.pem", "shared-password-verifier", "session-signing-secret"]) {
    assert.match(compose, new RegExp(`/etc/meser-audio-archive/${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
    assert.match(gateway, new RegExp(`/run/secrets/${path.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}`));
  }
  assert.doesNotMatch(compose, /GITHUB_APP_PRIVATE_KEY:\s|SHARED_PASSWORD_VERIFIER:\s|SESSION_SIGNING_SECRET:\s/);
});

test("Caddy terminates one hostname behind loopback HAProxy and replaces forwarding headers", () => {
  assert.equal((caddy.match(/^meserproject\.duckdns\.org\s*\{/gm) || []).length, 1);
  assert.match(caddy, /proxy_protocol[\s\S]*fallback_policy reject[\s\S]*\n\s*tls/);
  assert.match(caddy, /strict_sni_host on/);
  assert.match(caddy, /reverse_proxy gateway:8080/);
  for (const header of ["X-Forwarded-For", "X-Forwarded-Proto", "X-Forwarded-Host"]) {
    assert.match(caddy, new RegExp(`header_up -${header}`));
    assert.match(caddy, new RegExp(`header_up ${header}`));
  }
  assert.doesNotMatch(caddy, /xray|reality|:8443|:5678|:65000/i);
});

test("host HAProxy uses exact SNI passthrough and unconditional Xray default", () => {
  assert.match(haproxy, /frontend public_tls_443[\s\S]*bind :443[\s\S]*mode tcp/);
  assert.match(haproxy, /tcp-request inspect-delay 5s/);
  assert.match(haproxy, /req\.ssl_sni -i meserproject\.duckdns\.org/);
  assert.match(haproxy, /use_backend caddy_tls if meser_gateway_sni/);
  assert.match(haproxy, /default_backend xray_reality/);
  assert.match(haproxy, /127\.0\.0\.1:9443 send-proxy-v2/);
  assert.match(haproxy, /127\.0\.0\.1:9444 check/);
  assert.doesNotMatch(haproxy, /bind[^\n]*(?:8443|5678|65000)|ssl crt|mode http/i);
});

test("runbook is gated, unresolved values fail closed, and provider remnants are absent", () => {
  for (const gate of ["Gate 1", "Gate 2", "Gate 3", "Gate 4"]) assert.match(runbook, new RegExp(gate));
  for (const port of ["80", "443", "8443", "5678", "65000", "9443", "9444"]) assert.match(runbook, new RegExp(`\\b${port}\\b`));
  for (const token of ["UNEXECUTED", "UNRESOLVED", "PHASE_B_AUTHORIZED", "SECOND_REVIEW_COMPLETE", "sha256sum", "rollback-resolved.sh"]) {
    assert.match(runbook, new RegExp(token));
  }
  const activeFiles = [
    "src/config.mjs", "README.md", "PROVISIONING.md", "deploy/self-hosted/compose.yaml",
    "deploy/self-hosted/Caddyfile", "deploy/self-hosted/haproxy.cfg"
  ].map((relative) => read(resolve(root, relative))).join("\n");
  assert.doesNotMatch(activeFiles, /Cloud Run|Secret Manager|Google Cloud|\bgcloud\b|\bGCP\b|Artifact Registry|Cloud Build/i);
  assert.doesNotMatch(activeFiles, /-----BEGIN (?:RSA )?PRIVATE KEY-----|scrypt\$[^`\s]+/);
});

test("all frontend gateway hooks remain present and empty before deployment", () => {
  for (const relative of [
    "Admin-panel.html",
    "Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html",
    "Audio-Editor.html"
  ]) {
    const html = read(resolve(repositoryRoot, relative));
    assert.equal((html.match(/<meta name="audio-archive-gateway" content="">/g) || []).length, 1, relative);
  }
});
