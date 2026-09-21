FROM node:24-alpine@sha256:e67514e5d0f6c46656005e1b693b2ec9d52e80b641307de684d4a015ba7a4eaf

ARG SOURCE_SHA
LABEL org.opencontainers.image.revision=$SOURCE_SHA \
      org.opencontainers.image.source="https://github.com/meser-recovery/starter-package"

ENV NODE_ENV=production
WORKDIR /app

# One manifest binds the digest-pinned source image, Alpine package, architecture,
# exact native binary hashes and version used by the image and realistic CI load.
COPY ffmpeg-toolchain.env ./ffmpeg-toolchain.env
COPY tools/verify-ffmpeg-toolchain.mjs ./tools/verify-ffmpeg-toolchain.mjs
RUN set -a \
    && . ./ffmpeg-toolchain.env \
    && set +a \
    && test "$(apk --print-arch)" = "$FFMPEG_ARCH" \
    && apk add --no-cache "ffmpeg=$FFMPEG_PACKAGE" \
    && node ./tools/verify-ffmpeg-toolchain.mjs \
    && mkdir -p /var/cache/meser-waveforms \
    && chown root:root /var/cache/meser-waveforms \
    && chmod 0770 /var/cache/meser-waveforms

ENV FFMPEG_BIN=/usr/bin/ffmpeg \
    FFPROBE_BIN=/usr/bin/ffprobe

COPY package.json ./
COPY src ./src

USER node
EXPOSE 8080
CMD ["node", "src/server.mjs"]
