FROM node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf

ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=$SOURCE_SHA \
      org.opencontainers.image.source="https://github.com/meser-recovery/starter-package"

ENV NODE_ENV=production
WORKDIR /app

# The digest-pinned Node image's Alpine package version is pinned so the reviewed image contents cannot
# silently move to a different native decoder between builds.
RUN apk add --no-cache ffmpeg=8.1.2-r0 \
    && ffmpeg -version | head -1 | grep -F 'ffmpeg version 8.1.2' \
    && mkdir -p /var/cache/meser-waveforms \
    && chown root:root /var/cache/meser-waveforms \
    && chmod 0770 /var/cache/meser-waveforms

COPY package.json ./
COPY src ./src

USER node
EXPOSE 8080
CMD ["node", "src/server.mjs"]
