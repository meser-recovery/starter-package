FROM caddy:2.11.4-alpine@sha256:de23def33b17fb5d1290b0f6c2add1d70780e52341896c00a4c8a2a2fe9d355e

ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=$SOURCE_SHA \
      org.opencontainers.image.source="https://github.com/meser-recovery/starter-package"

COPY gateway/audio-archive/deploy/self-hosted/Caddyfile /etc/caddy/Caddyfile
COPY service/frontend /srv/service
