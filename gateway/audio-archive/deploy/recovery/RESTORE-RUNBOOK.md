# Meser service clean-machine recovery

Target: a clean supported Ubuntu 24.04 LTS VM. The old VM filesystem is not an input. The GitHub repository `meser-recovery/audio-archive` and its Releases remain the canonical archive store; there is no application database to restore.

1. Keep the age X25519 private identity outside the production VM and outside the recovery bundle. Copy it temporarily into an authorized isolated restore environment with mode `0600`.
2. Install the recorded host runtime versions: Docker Engine with Compose v2, HAProxy, age and systemd. Restore the reviewed HAProxy ingress configuration and verify that `meserproject.duckdns.org` still routes to loopback `127.0.0.1:9443`, while the unconditional Xray/REALITY default still routes to `127.0.0.1:9444`.
3. Run `sha256sum -c SHA256SUMS` in the bundle before decrypting or loading anything. Compare the accepted source SHA/tree, image IDs/digests, Compose checksum, Caddy checksum and HAProxy checksum with `recovery-manifest.txt` and `release-manifest.txt`.
4. Confirm `runtime.env` contains exactly the eleven keys enforced by `runtime-env.sh`: `SOURCE_SHA`, `GATEWAY_IMAGE`, `CADDY_IMAGE`, `GITHUB_APP_ID`, `GITHUB_APP_INSTALLATION_ID`, `ALLOWED_ORIGIN`, `MESER_SITE_ADDRESS`, `MESER_HTTP_BIND`, `MESER_TLS_BIND`, `MESER_RUNTIME_UID` and `MESER_SYNTHETIC_RUNTIME`. Source/image values must match the release manifests. In a separately authorized operator copy, enable both gates in `restore-meser-service.sh`. Run it with the bundle, off-VM age identity and an empty service root. It restores exact image archives and secret ownership/modes without printing secret contents.
5. Require each loaded image reference and each running container to match the exact manifest image ID. Validate Compose and Caddy, start only `gateway` and `caddy`, check `/healthz`, and preserve Caddy data/config volumes. The `waveform_cache` volume is disposable derived data: it is not restored, decrypted or included in a recovery bundle, and its absence must result in an empty volume that is regenerated on authenticated demand. Never use `docker compose down` in recovery or rollback.
6. Read-only validation: public Pages service link; unauthenticated protected-page denial; one-password login and `/v1/session` replay; landing, Calendar, Materials, Archive automatic access and Editor; one retained synthetic/read-only archive fixture; verified source retrieval; logout; HAProxy/Xray coexistence. Do not create, update, delete or publish archive data during rehearsal unless separately authorized disposable data is named.

The weekly unit/timer templates are intentionally not installed or enabled by repository work. Create a bundle after every production activation and after every secret, credential, password, signing-key, topology, Compose, Caddy or HAProxy material change. Retain the newest eight weekly recovery points and one monthly point for twelve months. Same-TrueNAS storage is off-VM but must be recorded as not protecting against loss of that physical host.

## S12 optional settings key

A legacy bundle has exactly three secret files and `secret-metadata.txt` inside
`secrets.age`. Missing `settings_key_version` is version 0. Version 1 has exactly
one additional `archive-settings-key` (64 hex characters, 32 independent random
bytes) and a checksum-bound reviewed `compose.s12.yaml`. Unknown files, symlinks,
hardlinks, unsafe secret modes, metadata mismatch, invalid key and missing or
corrupt overlay are refused. No settings plaintext is included in a bundle:
canonical ciphertext stays in `meser-recovery/audio-archive` Git history.

Backup source `/etc/meser-audio-archive/archive-settings-key` is 0600. The optional
runtime mount uses a distinct `archive-settings-runtime-key`, 0640, owned by root
and group 0, readable by the existing non-root Gateway (`1000:0`); no world read.
The overlay mounts this file only into Gateway, read-only, with host-path creation
disabled. Caddy receives neither the key nor credentials. Keep runtime copies
outside the strict backup secret directory; configure the backup source as the
exact canonical secret set. Restore installs canonical 0600 and runtime 0640
copies under its config root, then includes the exact overlay in Compose.

After an authorized restore, require exact images and existing health checks,
then verify `loadConfig().settingsKey` is present from the actual non-root Gateway
user without printing the value. An authenticated read of `/v1/archive-settings`
must successfully decrypt the existing fixed canonical file and return the
expected profile names, active ID and thresholds without credential fields.
A missing/wrong key or tag is an S12 failure, never permission to create defaults.
Verify ordinary Archive and Editor separately. The age private identity remains
off VM, outside the bundle, and is removed from the isolated environment after
rehearsal. Do not run a real import to test recovery without separate permission.

## Authorized key rotation procedure (not executed by S12 implementation)

All provisioning, rotation, production CAS writes, activation and real bundles
need separate authorization. Retain the current encrypted recovery bundle and
old key outside the VM until the replacement has passed isolated recovery.
Pause S12 configuration/import writes in the maintenance window; do not alter
existing session/audio data or expose plaintext settings on disk.

1. Record exact source/tree/images, current canonical Git head and encrypted
   settings blob identity. Read and validate the current settings using the old
   mounted key. Any read/decrypt error stops rotation.
2. Provision a new independent random 256-bit key in a 0600 operator file. Keep
   both keys recoverable. Do not derive it from another secret or write it to
   `runtime.env`, shell arguments/logs, source or a manifest.
3. In the separately authorized server-side operator process, use existing
   `repository.getHead/readJson`, `decryptSettings/validateSettings`,
   `encryptSettings` and `repository.commitJson(expectedHead,...)` to re-encrypt
   the exact current document with the new key. Use a fresh nonce/AAD and the
   fixed settings path. A CAS conflict requires rereading/decrypting the latest
   document; never force-update a ref or replace it with stale settings.
4. Resolve a lost commit response by reading the authoritative encrypted blob
   and verifying it with the new key. Read after write and compare the entire
   validated logical document/revision to the pre-write value. Do not update the
   runtime mount until this comparison succeeds.
5. Replace canonical 0600 and runtime 0640 key copies with the retained new key;
   restart only the separately authorized Gateway with the optional overlay.
   Verify non-root key access, authenticated decrypt, legacy workflows and exact
   runtime images. Create the updated version-1 encrypted S10A bundle, retaining
   an external recovery copy of both old/new keys until recovery passes.
6. Destroy the isolated runtime copy and restore from that new bundle with the
   off-VM age identity. Decrypt the same current canonical configuration and
   verify active connection and storage thresholds. Only after this succeeds
   retire the previous key from active runtime use. Keep historical key recovery
   material under the operator's approved retention controls.

Interruption before canonical CAS: old ciphertext/key continue to work; the new
uncommitted key cannot decrypt it. Interruption after CAS but before mount: S12
fails closed with the old runtime key; recover/install the retained new key and
verify the current blob, rather than overwriting it. A lost response is resolved
before any further write. If reverting re-encryption is separately authorized,
CAS against the current head and re-encrypt the *current logical document* with
a retained known key; never reset Git to an old settings version. Ordinary
Archive/Editor remain available while only S12 is unavailable.

Historical ciphertext remains accessible in public Git history. Rotating an
encryption key does not erase that history. A compromised key requires rotation
of the key **and all affected Zoom credentials**; historical secrets should be
considered exposed. Pending imports must be completed/discarded before changing
credentials they still require.

## Reader compatibility gate

Before S12 writes, exact legacy images/configs can use the existing rollback
rehearsal. After the first `zoom_cloud` Session/catalog/transaction, rollback to
an unmodified pre-S12 Gateway is prohibited: its strict validators reject that
origin. Prepare and rehearse a reviewed reader-compatible target before allowing
real S12 writes. Never delete new records or promise rollback based only on image
startup. Keep activation/restore authorization gates false in repository source.

Synthetic CI runs both legacy and version-1 bundle/restore cases. Version 1
creates/rotates synthetic settings with the actual AES schema, destroys local
runtime keys, recovers them from `secrets.age`, and decrypts the same canonical
fixture; the Docker case additionally proves the actual non-root mount. The
fixture also tests CAS conflict, interrupted rotation, wrong/missing keys,
tampered tag, safe DTOs and unaffected legacy listing. It uses no real account.
