import test from "node:test";
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join, resolve } from "node:path";

const root = resolve(import.meta.dirname, "..");
const repositoryRoot = resolve(root, "../..");
const deploy = resolve(root, "deploy/self-hosted");
const read = (path) => readFileSync(path, "utf8");
const compose = read(resolve(deploy, "compose.yaml"));
const caddy = read(resolve(deploy, "Caddyfile"));
const haproxy = read(resolve(deploy, "haproxy.cfg"));
const runbook = read(resolve(root, "PROVISIONING.md"));
const s10aActivation = read(resolve(root, "deploy/s10a/activate-reviewed-service.sh"));
const s10aRollback = read(resolve(root, "deploy/s10a/rollback-reviewed-service.sh"));
const legacyActivation = read(resolve(root, "deploy/s10a/activate-reviewed-gateway.sh"));
const recoveryCreate = read(resolve(root, "deploy/recovery/create-recovery-bundle.sh"));
const recoveryRestore = read(resolve(root, "deploy/recovery/restore-meser-service.sh"));
const s10aChecklist = read(resolve(root, "deploy/s10a/OPERATOR-CHECKLIST.md"));

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
  assert.match(gateway, /service_private/);
  assert.match(gateway, /SOURCE_SHA/);
  assert.match(proxy, /Caddy\.Dockerfile/);
  assert.match(proxy, /- "80:80\/tcp"/);
  assert.match(proxy, /- "127\.0\.0\.1:9443:443\/tcp"/);
  assert.doesNotMatch(proxy, /- "443:443/);
  assert.match(proxy, /service_private/);
  assert.doesNotMatch(proxy, /\n\s+secrets:/);
  assert.doesNotMatch(proxy, /Caddyfile:\/etc\/caddy/);
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
  assert.match(caddy, /forward_auth gateway:8080[\s\S]*uri \/internal\/auth-check/);
  assert.match(caddy, /@login path \/login/);
  assert.match(caddy, /scripts\/service-session-client\.mjs/);
  assert.doesNotMatch(caddy.match(/@login path[^\n]+/)?.[0] || "", /audio-archive-client/);
  assert.match(caddy, /@internal path \/internal\/\*/);
  assert.match(caddy, /Content-Security-Policy/);
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

test("runbook keeps full-service activation and recovery explicitly unexecuted", () => {
  for (const token of ["unexecuted", "exact reviewed", "off-VM", "age X25519", "false", "gateway", "Caddy", "rollback", "clean Ubuntu 24.04 LTS"]) {
    assert.match(runbook, new RegExp(token));
  }
  assert.match(runbook, /must not use `docker compose down`/);
  assert.match(runbook, /HAProxy\/Xray routing.*not changed/);
  const activeFiles = [
    "src/config.mjs", "README.md", "PROVISIONING.md", "deploy/self-hosted/compose.yaml",
    "deploy/self-hosted/Caddyfile", "deploy/self-hosted/haproxy.cfg"
  ].map((relative) => read(resolve(root, relative))).join("\n");
  assert.doesNotMatch(activeFiles, /Cloud Run|Secret Manager|Google Cloud|\bgcloud\b|\bGCP\b|Artifact Registry|Cloud Build/i);
  assert.doesNotMatch(activeFiles, /-----BEGIN (?:RSA )?PRIVATE KEY-----|scrypt\$[^`\s]+/);
});

test("protected frontend is repository-owned and Pages entry points are forward-only", () => {
  for (const relative of ["login.html", "index.html", "Calendar.html", "Google-Drive.html", "Audio-Editor.html", "Audio-Archive.html"]) {
    const html = read(resolve(repositoryRoot, "service/frontend", relative));
    assert.match(html, /scripts\/origin-guard\.js/, relative);
    assert.doesNotMatch(html, /audio-archive-gateway|sessionStorage|StorageAccess|safari-bootstrap/, relative);
  }
  for (const relative of ["Admin-panel.html", "Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html", "Calendar.html", "Google-Drive.html", "Audio-Editor.html", "Audio-Archive.html"]) {
    const html = read(resolve(repositoryRoot, relative));
    assert.match(html, /service-compatibility\.js/);
    assert.match(html, /https:\/\/meserproject\.duckdns\.org/);
    assert.doesNotMatch(html, /\/v1\/|password|sessionStorage|audio-archive-client|audio-processor/i);
  }
});

test("S10A activation package is inert, full-stack, checksum guarded, recovery-gated and rollback bound", () => {
  assert.match(s10aActivation, /S10A_PRODUCTION_AUTHORIZED=false/);
  assert.match(s10aActivation, /S10A_INDEPENDENT_REVIEW_COMPLETE=false/);
  assert.match(s10aActivation, /sha256sum "\$artifact"/);
  assert.match(s10aActivation, /tar -tzf "\$artifact" >"\$listing"/);
  assert.match(s10aActivation, /build --pull=false gateway caddy/);
  assert.match(s10aActivation, /up -d --no-build gateway caddy/);
  assert.match(s10aActivation, /rollback-reviewed-service\.sh/);
  assert.match(s10aActivation, /__Host-meser_service_session/);
  assert.match(s10aActivation, /recovery bundle integrity failed/);
  assert.doesNotMatch(s10aActivation, /ssh |systemctl|docker compose down/);
  assert.match(s10aRollback, /gateway caddy/);
  assert.doesNotMatch(s10aRollback, /docker compose down|volume rm|haproxy\.cfg.*>/);
  assert.match(legacyActivation, /permanently disabled/);
  assert.match(s10aChecklist, /No command.*executed against production/);
});

test("recovery tooling uses age, exact secret allowlist, off-VM marker and inert restore gates", () => {
  assert.match(recoveryCreate, /age -r "\$recipient"/);
  assert.match(recoveryCreate, /\.meser-recovery-target/);
  assert.match(recoveryCreate, /mountpoint -q/);
  assert.match(recoveryCreate, /release artifact checksum failed/);
  assert.match(recoveryCreate, /release manifest is incomplete/);
  for (const name of ["github-app.pem", "shared-password-verifier", "session-signing-secret"]) assert.match(recoveryCreate, new RegExp(name));
  assert.match(recoveryRestore, /MESER_RESTORE_AUTHORIZED=false/);
  assert.match(recoveryRestore, /sha256sum -c SHA256SUMS/);
  assert.match(recoveryRestore, /age -d -i/);
});

test("S10A artifact layout check consumes the complete tar listing under pipefail", () => {
  const fixture = mkdtempSync(join(tmpdir(), "s10a-layout-"));
  const sourceSha = "a".repeat(40);
  const packageRoot = `meser-service-s10a-${sourceSha}`;
  const dockerfile = `${packageRoot}/gateway/audio-archive/Dockerfile`;
  const archive = resolve(fixture, "artifact.tar.gz");
  const fileList = resolve(fixture, "files.txt");

  try {
    mkdirSync(resolve(fixture, packageRoot, "gateway/audio-archive"), { recursive: true });
    mkdirSync(resolve(fixture, packageRoot, "padding"), { recursive: true });
    writeFileSync(resolve(fixture, dockerfile), "FROM scratch\n");

    const entries = [dockerfile];
    for (let index = 0; index < 4096; index += 1) {
      const name = `${packageRoot}/padding/${String(index).padStart(4, "0")}-${"x".repeat(64)}`;
      writeFileSync(resolve(fixture, name), "");
      entries.push(name);
    }
    writeFileSync(fileList, `${entries.join("\n")}\n`);

    const packed = spawnSync("tar", ["-czf", archive, "-C", fixture, "-T", fileList], { encoding: "utf8" });
    assert.equal(packed.status, 0, packed.stderr);

    const pattern = `^${packageRoot}/gateway/audio-archive/Dockerfile$`;
    const pipeSafe = spawnSync(
      "bash",
      ["-o", "pipefail", "-c", 'tar -tzf "$1" | grep -E "$2" >/dev/null', "layout-check", archive, pattern],
      { encoding: "utf8" },
    );
    assert.equal(pipeSafe.status, 0, pipeSafe.stderr);
  } finally {
    rmSync(fixture, { recursive: true, force: true });
  }
});
