# S10A Closure Record

Status: **MOBILE ACCEPTANCE REOPENED** — see [`S10A_CLOSURE_ADDENDUM_REAL_IPHONE_REGRESSION.md`](S10A_CLOSURE_ADDENDUM_REAL_IPHONE_REGRESSION.md). The production activation and non-mobile evidence below remain historical facts; the prior mobile PASS is superseded for final acceptance.

Closure date: 2026-09-21

Production activation date: 2026-09-20 UTC

This record is the authoritative closure statement for the complete S10A line of work. It ties together the original Safari Archive/remote-source task, the same-origin service FIX, the guarded activation and recovery workflow, the mobile long-audio waveform corrective, and the protected-UI/public-return corrective.

## 1. Accepted production identity and activation result

| Field | Accepted value |
| --- | --- |
| Source SHA | `00087057a233ed40500d77706d54f8b9b22df45d` |
| Source tree | `99cd8556b4b72af6db0fb2afa44510c194159478` |
| Activation result | `PASS` |
| Wrapper run count | `1` |
| Wrapper exit code | `0` |
| Replacement started | `true` |
| Rollback | `NOT_REQUIRED` |
| Archive mutations | `0` |
| Active Gateway image ID/digest | `sha256:398a338e47cb872446337a3e47957dba89b45c84a88aa74282beb2a6541a8d09` |
| Active Caddy/frontend image ID/digest | `sha256:0e19a65547f37f054be50bb4356d2d1f8658adbe64af0c2b9513e8fd40dc5724` |
| Deployment record | `/var/lib/meser-audio-archive/deployments/20260920T230052Z-00087057a233ed40500d77706d54f8b9b22df45d` |
| Post-activation recovery bundle | `/mnt/meser-recovery/meser-service-recovery-20260920T230116Z-00087057a233ed40500d77706d54f8b9b22df45d` |
| Sanitized activation log | `/home/alex/meser-s10a-transfer-00087057/activation-00087057.log` |
| Activation log SHA-256 | `574fc4c4a682206075623ea59172eaee5b7e816987ab1c11822efd39bf228c1c` |

The guarded wrapper ran exactly once. Candidate replacement completed, the reviewed readiness and zero-write smoke passed, the post-activation recovery bundle was created and verified, and the external live-browser attestation passed. Automatic rollback was armed but was not needed.

## 2. Final service architecture

The public and protected sites remain deliberately separate:

```text
https://meser-recovery.github.io/starter-package/
  └─ “Для служащих”
       └─ https://meserproject.duckdns.org/
            ├─ protected frontend served by Caddy
            └─ same-origin /v1/* forwarded to the private Gateway
```

The protected service uses one canonical origin, `https://meserproject.duckdns.org`. Caddy serves the protected documents and frontend assets and forwards same-origin Gateway requests. The Gateway is not a second public login surface.

One submission of the existing shared service password creates the server-side `__Host-meser_service_session` session. The cookie is host-only, Secure and HttpOnly. The authenticated session is shared by the protected landing page, Calendar, Materials, Audio Archive and Audio Editor. Audio Archive connects automatically through that session; there is no Archive-specific password, second authentication layer, browser storage authority or manual Archive connection step.

Protected document navigation that lacks a valid service session returns a safe `303` to `/login` with a validated return intent. Protected assets and data remain fail-closed. Public access to `/internal/*` is denied.

The protected header retains two direct public-return links: the NA logo and the brand identity. Both navigate in the same tab to `https://meser-recovery.github.io/starter-package/`. The public site's “Для служащих” link continues to enter the protected DuckDNS flow.

## 3. Implemented and verified production behavior

### 3.1 Activation and runtime readiness

- The Gateway container is running the exact accepted image and is Docker `healthy`.
- The Caddy/frontend container is running the exact accepted image; its expected Docker health state is `not-configured`.
- Public `/healthz` returned HTTP `200` with `{"ok":true,"service":"audio-archive-gateway"}`.
- Candidate readiness tolerated the bounded HAProxy/Caddy startup interval and required two consecutive valid public health responses.
- Unauthenticated protected navigation returned `303` to `/login?return=%2F`.
- External `/internal/*` access returned `404`.
- The authoritative deployment record and verified post-activation recovery bundle were written only after the reviewed activation checks passed.

### 3.2 Authentication, session and protected UI

- The canonical service login accepted the existing shared password.
- The login response produced the canonical protected session cookie; authenticated replay succeeded.
- All protected pages used the same server-side session without another password prompt.
- Logout revoked the session, cleared the browser cookie and returned the browser to `/login`.
- The guarded activation smoke verified that a protected API returns `401` after logout/revocation.
- Authentication/session/cookie/CSRF semantics were not weakened by the Archive, waveform or UI correctives.

### 3.3 Archive and remote source

- Audio Archive connected automatically after service authentication.
- The existing record “Яаков” appeared and opened successfully.
- Opening and inspecting the record remained read-only.
- The Editor opened from the same service session.
- The record's three remote M4A source tracks downloaded and reconstructed successfully.
- The accepted read-only source-part control matched path `/v1/source-sessions/c180c34e-7219-52f6-8808-3536b0af8621/blobs/e4aeda88-fa30-8005-a9ac-cfe0ef850b85/parts/2/content`, SHA-256 `acea0855890284fe82805d49f8cc7118049577c08c82a449ec264c8e8890ec75` and byte count `6245482` on two identical reads during guarded activation.
- No Archive create, update, delete, publish or output mutation occurred: `ARCHIVE_MUTATIONS=0`.

### 3.4 Editor, FFmpeg/WASM and CSP

- The Editor loaded the accepted remote source under the actual production Caddy headers.
- FFmpeg/WASM loaded under a CSP containing the minimal `'wasm-unsafe-eval'` allowance without general `'unsafe-eval'`.
- The three long M4A tracks completed sequential waveform preparation.
- The restored Editor project displayed all three waveforms across the full `3747.648 s` source duration.
- The production Chrome run produced no browser-visible loading error, infinite loader, console error or tab failure.

### 3.5 Public-return acceptance

The live production smoke covered the protected landing page, Calendar, Materials, the protected administrative page, Audio Editor, Audio Archive and the login route where applicable.

- Each protected page was confirmed on `meserproject.duckdns.org`.
- Both public-return links exposed the exact absolute href `https://meser-recovery.github.io/starter-package/`.
- Neither link used a new-tab target.
- Fourteen real link activations (two per page) arrived at the exact GitHub Pages root in the same tab.
- None returned to DuckDNS or produced `/login?return=%2F` after the public navigation.
- The public “Для служащих” link still returned to the protected DuckDNS flow.
- The public-return smoke performed no Archive mutation.

## 4. Mobile long-audio waveform corrective

The initial real-device failure was isolated to the FFmpeg/WASM waveform path after authenticated Archive selection and source reconstruction; it was not an authentication, session, Archive-connect, source-route, manifest or MIME loss defect. The earlier production build discarded the concrete internal stage, so out-of-memory pressure remained a working hypothesis rather than a proven root cause.

The corrective implementation retained the 65,536-peak waveform contract while replacing the monolithic `65536 × 100 × 4` RGBA output with sequential bounded chunks. Each output is at most `4096 × 100 × 4 = 1,638,400` bytes. One active input is written to the WASM filesystem per track, outputs are read and deleted sequentially, tracks do not overlap, and every track uses a clean fatal-failure/abort lifecycle. Stage-aware safe diagnostics distinguish engine load, input read, WASM write, FFmpeg execution, WASM read, peak conversion, cleanup and abort without logging participant names, filenames, cookies, credentials or Archive contents.

Verified physical-iPhone results:

| Device/browser scenario | Result |
| --- | --- |
| iPhone Safari — one long track | PASS |
| iPhone Safari — three long tracks | PASS; three × 65,536 peaks; 15,598 ms; `archiveMutations=0` |
| iPhone Chrome — one long track | PASS |
| iPhone Chrome — three long tracks | PASS; three × 65,536 peaks; 16,865 ms; `archiveMutations=0` |

In both iPhone browsers FFmpeg/WASM loaded, sequential processing completed, and the tab remained stable. Automated tests separately cover deterministic gapless chunk planning, output memory bounds, stage failures, abort, retry, cleanup and three-track serialization. Automated WebKit evidence is not represented as physical-iPhone evidence.

## 5. Accepted residual risk

The following device coverage was not executed and is accepted explicitly as residual risk for closure:

- Android Chrome: **NOT TESTED** on a real device.
- Alternative Android browser: **NOT TESTED** on a real device.
- Physical-device refresh/repeat after waveform completion: **NOT TESTED as a separate device scenario**.
- Physical-device abort/retry during waveform preparation: **NOT TESTED as a separate device scenario**.

Automated Chromium, Firefox, WebKit, Caddy-backed CSP, abort/retry and sequential-track results exist, but they do not replace the missing physical Android runs. Closure does not claim otherwise.

## 6. Recovery storage and trust boundary

| Recovery property | Recorded value |
| --- | --- |
| Storage host | TrueNAS `192.168.1.150` |
| Dataset/export path | `/mnt/nas/meser` |
| NFS source | `192.168.1.150:/mnt/nas/meser` |
| Production VM mount | `/mnt/meser-recovery` |
| Required marker | `meser-recovery-truenas-192.168.1.150-nas-meser-v1` |
| Encryption | age/X25519 recipient encryption |
| Private identity | Kept only outside the production VM and outside recovery bundles |
| Production backup schedule | No timer installed or active |

The NFS target is off the production VM but remains on the same physical TrueNAS/storage host. It protects against loss of the application VM; it does **not** protect against loss or compromise of the TrueNAS host itself. This failure-domain limitation is recorded in the recovery manifest and remains an operational residual risk.

Exactly three secret files are allowed into the encrypted payload:

```text
github-app.pem
session-signing-secret
shared-password-verifier
```

The allowlist is fail-closed. Missing, duplicate, additional, symlinked or incorrectly permissioned inputs are rejected. These files exist in the bundle only inside `secrets.age`; no plaintext secret is present in the bundle. The age private identity is never copied to production and was not used to decrypt the post-activation bundle on the production VM.

## 7. Recovery bundle contents and integrity

The post-activation bundle contains fourteen checksummed payload files plus `SHA256SUMS`; the activation workflow verified all `14/14` payload checksums:

- exact `release-manifest.txt`;
- deterministic source archive and its checksum file;
- exact Gateway image archive and checksum file;
- exact Caddy/frontend image archive and checksum file;
- reviewed `compose.yaml`;
- reviewed `Caddyfile`;
- reviewed HAProxy reference configuration;
- canonical eleven-key `runtime.env`;
- `recovery-manifest.txt` with source SHA/tree, exact image refs/IDs, destination marker, runtime baseline, encryption method and failure-domain note;
- `RESTORE-RUNBOOK.md`;
- encrypted `secrets.age` containing only the three allowlisted secret files and non-secret mode metadata;
- `SHA256SUMS` covering every payload file above.

The canonical `runtime.env` contains exactly these eleven non-secret keys:

```text
SOURCE_SHA
GATEWAY_IMAGE
CADDY_IMAGE
GITHUB_APP_ID
GITHUB_APP_INSTALLATION_ID
ALLOWED_ORIGIN
MESER_SITE_ADDRESS
MESER_HTTP_BIND
MESER_TLS_BIND
MESER_RUNTIME_UID
MESER_SYNTHETIC_RUNTIME
```

For production, the source SHA and image references must equal the release and recovery manifests; `ALLOWED_ORIGIN` must be `https://meserproject.duckdns.org`; `MESER_SITE_ADDRESS` must be `meserproject.duckdns.org`; HTTP/TLS binds must be `80` and `127.0.0.1:9443`; runtime UID must be `1000`; and synthetic mode must be `false`. Missing, duplicate, unknown, empty or mismatched keys fail closed.

## 8. Guarded clean-machine restore procedure

This is an operator procedure, not standing authorization to restore production. A restore requires a new explicit authorization naming the exact bundle and target environment.

1. **Prepare an isolated target.** Use a clean supported Ubuntu 24.04 LTS environment with the recorded architecture. Install the recorded prerequisites: Docker Engine with Compose v2, age, HAProxy and systemd. Do not expose the target as production and do not modify the existing production VM during rehearsal.
2. **Establish network prerequisites.** Restore the reviewed HAProxy ingress separately and verify the recorded routing invariants: the canonical service reaches loopback `127.0.0.1:9443`, while the existing unconditional Xray/REALITY default remains on `127.0.0.1:9444`. DNS, firewall and router changes require separate authorization.
3. **Mount the recovery target read-only first.** Confirm the NFS source is exactly `192.168.1.150:/mnt/nas/meser`, the mount is not a symlink, and `.meser-recovery-target` is a regular file whose exact content is `meser-recovery-truenas-192.168.1.150-nas-meser-v1`. Stop if any identity differs.
4. **Select the exact bundle.** Use `/mnt/meser-recovery/meser-service-recovery-20260920T230116Z-00087057a233ed40500d77706d54f8b9b22df45d`. Confirm it is a regular directory, not a symlink, and contains `SHA256SUMS`, `recovery-manifest.txt`, `release-manifest.txt`, `runtime.env`, both image archives, Compose, Caddy and `secrets.age`.
5. **Verify before decrypting or loading.** From the bundle directory run `sha256sum -c SHA256SUMS`. Require every entry to pass. Compare source SHA/tree, image refs/IDs, Compose/Caddy/HAProxy checksums, destination marker and failure-domain statement across the release and recovery manifests. Stop on any discrepancy.
6. **Validate the canonical runtime.** Run the accepted `runtime-env.sh` shape validator. Require exactly the eleven keys listed above and the production values/invariants recorded in section 7. Confirm both GitHub App identifiers match the currently authorized production identities without printing their values. Stop on malformed, missing, duplicate, unknown or inconsistent data.
7. **Bring the private identity only into the isolated recovery environment.** Copy the off-VM age X25519 private identity to a dedicated temporary root-owned, non-symlink file with mode `0600`. Never copy it into the production VM, recovery bundle, repository, command-line arguments, logs or shared storage.
8. **Create a reviewed restore operator copy.** The committed `restore-meser-service.sh` must still contain:

   ```text
   MESER_RESTORE_AUTHORIZED=false
   MESER_ISOLATED_ENVIRONMENT_CONFIRMED=false
   ```

   After independent review and explicit authorization, prepare a root-only operator copy whose unified diff contains exactly the two changes to `true`. Do not change the committed source. Confirm shell syntax, regular/non-symlink status, ownership and mode before execution.
9. **Provide an empty restore root.** Create a dedicated empty absolute service root for the restore. Do not point the restore at an existing repository checkout or mutable old-VM filesystem.
10. **Run the accepted three-argument restore once.** From the isolated environment invoke:

    ```text
    restore-meser-service.sh <recovery-bundle> <off-vm-age-identity> <empty-service-root>
    ```

    The script rechecks bundle integrity, manifests, runtime identity and age-key permissions before decrypting or loading anything. It decrypts into a unique `/tmp/meser-restore.*` root-only staging directory, verifies the exact secret allowlist, installs modes, and registers an EXIT trap to remove plaintext staging.
11. **Load and prove exact images.** Load only `gateway-image.tar` and `caddy-frontend-image.tar` from the verified bundle. Require each loaded reference and ID to equal both manifests. Never pull, rebuild, retag or substitute an image when an identity check fails.
12. **Validate configuration before startup.** Validate Compose with the restored canonical runtime and the exact reviewed files. Validate Caddy with the pinned restored Caddy image. Compare the reviewed HAProxy checksum/invariants; do not overwrite HAProxy merely because a reference file exists in the bundle.
13. **Start only the restored application services.** The accepted restore starts `gateway` and `caddy` with `--no-build`. It must not use `docker compose down`. Require running containers to use the exact manifest image IDs.
14. **Perform health and zero-write acceptance.** Require Gateway healthy, Caddy running, public `/healthz=200` with the expected JSON, safe unauthenticated document redirect, fail-closed protected assets/data, one-password login and session replay, Archive automatic access, existing-record read, verified source retrieval, Editor/FFmpeg/WASM under the actual CSP, public-return links, logout/revocation and external denial of `/internal/*`. Require `ARCHIVE_MUTATIONS=0`.
15. **Remove recovery plaintext.** Whether restore succeeds or fails, verify that the restore script's EXIT trap removed `/tmp/meser-restore.*` plaintext staging. Securely remove the temporary private age identity from the isolated environment after the authorized validation is complete. Never retain a decrypted secret archive.
16. **Record the result.** Save a sanitized log and its SHA-256, exact bundle identity, exact loaded/running image IDs, health/smoke matrix, cleanup result and any rollback/stop action. Do not include secret contents, secret hashes, cookies, CSRF values or credentials.

### Mandatory stop and rollback conditions

Stop immediately without bypass or automatic retry if any of the following occurs:

- NFS source or marker mismatch;
- symlink, ownership or mode violation;
- any `SHA256SUMS`, manifest, source, configuration or runtime mismatch;
- age decryption failure or a secret allowlist mismatch;
- loaded or running image ID differs from the manifest;
- Compose/Caddy validation fails;
- Gateway/Caddy readiness, public health, auth/session, Archive read-only, Editor/CSP, logout or internal-route denial fails;
- any Archive mutation is observed;
- plaintext staging cannot be proven removed.

For an isolated clean-machine rehearsal, keep the failed target isolated, preserve sanitized evidence, remove plaintext staging and do not promote it. Do not improvise a production fix, pull alternate images or repeat restore without new authorization.

For a separately authorized in-place recovery, capture the exact current Gateway/Caddy container and image identities before replacement. If a post-replacement check fails, invoke the accepted `rollback-reviewed-service.sh <captured-rollback-directory>` workflow, require both previous exact image IDs and canonical `/healthz` to recover, and stop. Never use `docker compose down`, delete the accepted recovery point or retry activation/restore without a new authorization.

## 9. Operational state after closure

### Implemented and verified

- Exact full-service production activation from the accepted source/tree.
- Same-origin Caddy/Gateway architecture and one shared server-side session.
- Automatic Archive access, existing-record read and remote-source preparation.
- Resource-bounded long-audio waveform extraction and stage-aware diagnostics.
- Real iPhone Safari and Chrome one-track/three-track waveform runs.
- Live Chrome protected-flow, Editor/FFmpeg/WASM and public-return acceptance.
- Verified encrypted post-activation recovery bundle on the marked off-VM NFS target.
- Wrapper cleanup and zero Archive mutations.

### Accepted residual risk

- Real Android Chrome and alternative Android-browser acceptance are `NOT TESTED`.
- Separate real-device refresh/repeat and abort/retry runs are `NOT TESTED`.
- Recovery storage is off-VM but not independent of loss of the TrueNAS physical host.

### Not performed

- No second activation or wrapper run.
- No production rollback.
- No real disaster restore or production decrypt rehearsal using the off-VM private age identity.
- No age private identity copy to the production VM.
- No production secret rotation or modification.
- No Archive write or mutation.
- No backup service/timer installation or activation.
- No `/etc/fstab`, HAProxy, Xray, DNS, router or firewall change as part of closure.
- No Android device claim.

New recovery bundles therefore remain manual products of an explicitly authorized activation/recovery workflow. The repository contains disabled service/timer templates, but no recurring backup is installed or active.

All four committed authorization gates remain `false`: the two production activation gates in `activate-reviewed-service.sh` and the two restore gates in `restore-meser-service.sh`. The one-time production operator copy was separate from Git and does not grant standing authorization for another activation or restore.

## 10. Cleanup and absence of collateral changes

The one-time activation cleanup removed:

- `/run/meser-s10a-smoke-password`;
- `/run/meser-s10a-source-smoke-record`;
- the public-return verdict/attestation files;
- the temporary root-only plaintext secret staging directory.

Original production secret files and their permissions were not changed. Secrets were not rotated. The accepted pre-cutover recovery points were retained. `/etc/fstab`, HAProxy, DNS, router/firewall and Archive data were not changed. The backup timer remained absent/inactive.

## 11. S10A traceability

| Accepted change | Purpose in the closed S10A chain |
| --- | --- |
| `750f4e2` — PR #45 | Original Safari Archive connection and verified remote-source preparation, including fail-closed identity validation and rapid-selection regression coverage. |
| `6fdf4f5` — PR #46 | Same-origin protected service, server-side login/session, Caddy auth routing, CSP/WASM, logout and full-service activation/recovery foundations. |
| `309e9ae` — PR #47 | Acceptance runtime evidence and canonical recovery/runtime compatibility. |
| `1ff3384` — PR #48 | Healthless-Caddy state capture for guarded activation. |
| `9dc6f41` — PR #49 | Bounded readiness and rollback correction after the activation incident. |
| `168dd31` — PR #50 | Resource-bounded mobile long-audio waveform extraction, diagnostics, cleanup and real-iPhone evidence. |
| `0008705` — PR #51 | Protected public-return links and focused login/Archive/Editor UI corrective; final accepted production source. |

The earlier failed and rolled-back attempts remain useful incident evidence in `S10A_REQUIREMENT_EVIDENCE_MATRIX.md`; they are not the final operational state. This Closure Record supersedes their pre-activation status statements with the separately authorized successful activation evidence above.

## 12. Closure decision

S10A is closed because the exact accepted source is active, the production full-service checks and live Chrome acceptance passed, the physical-iPhone waveform corrective passed in Safari and Chrome, the post-activation encrypted recovery point was created and verified, cleanup completed, and Archive mutations remained zero.

Closure is conditional only on the explicitly accepted and documented residual risks in section 5 and section 9. It does not convert unperformed Android testing, a real disaster restore, recurring backups or TrueNAS-host-loss protection into completed evidence.
