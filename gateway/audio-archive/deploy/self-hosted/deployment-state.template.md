# Self-hosted deployment state — UNRESOLVED TEMPLATE

Copy this file to the ignored `deployment-state.local.md` only during a separately authorized read-only VM discovery. Do not authorize Phase A or Phase B while any field says `UNRESOLVED`.

## Ownership and paths

| Field | Discovered value | Evidence/checksum |
| --- | --- | --- |
| HAProxy package/version and unit | UNRESOLVED | UNRESOLVED |
| x-ui unit/container | UNRESOLVED | UNRESOLVED |
| Xray unit/process owner | UNRESOLVED | UNRESOLVED |
| Authoritative x-ui/Xray config path | UNRESOLVED | UNRESOLVED |
| Generated Xray config path, if separate | UNRESOLVED | UNRESOLVED |
| Xray restart/reload command | UNRESOLVED | UNRESOLVED |
| Baseline backup directory | UNRESOLVED | UNRESOLVED |
| Deployment operator/group | UNRESOLVED | UNRESOLVED |

## Listener inventory

Record the complete `ss` output and owning process/container for every row before and after cutover.

| TCP port/address | Before | After | Required invariant |
| --- | --- | --- | --- |
| `:80` | UNRESOLVED | UNRESOLVED | Caddy only after authorized Phase A |
| `:443` | UNRESOLVED | UNRESOLVED | Xray before; HAProxy after Phase B |
| `:8443` | UNRESOLVED | UNRESOLVED | unchanged MTProto |
| `:5678` | UNRESOLVED | UNRESOLVED | unchanged n8n |
| `:65000` | UNRESOLVED | UNRESOLVED | unchanged x-ui |
| `127.0.0.1:9443` | UNRESOLVED | UNRESOLVED | free before; Caddy after Phase A |
| `127.0.0.1:9444` | UNRESOLVED | UNRESOLVED | free before; Xray only during Phase B |

## Required evidence

- Authoritative Xray backup path and SHA-256: `UNRESOLVED`
- Generated Xray backup path and SHA-256, or confirmed not separate: `UNRESOLVED`
- Restored-copy checksum verification: `UNRESOLVED`
- Proposed Xray localhost config validation: `UNRESOLVED`
- `haproxy -c` output: `UNRESOLVED`
- `caddy validate` output: `UNRESOLVED`
- `docker compose config` output hash: `UNRESOLVED`
- Gateway image ID and health result: `UNRESOLVED`
- Caddy-to-gateway local health result: `UNRESOLVED`
- Existing REALITY client verification procedure: `UNRESOLVED`
- Approved Phase A change ticket: `UNRESOLVED`
- Separately confirmed Phase B/cutover ticket: `UNRESOLVED`
- Materialized and reviewed literal rollback commands: `UNRESOLVED`
