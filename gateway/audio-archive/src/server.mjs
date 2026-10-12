import http from "node:http";
import { createApp } from "./app.mjs";
import { loadConfig } from "./config.mjs";
import { AudioArchiveDomain } from "./domain.mjs";
import { GitHubArchiveRepository } from "./github.mjs";
import { nodeHandler } from "./http-adapter.mjs";
import { WaveformService } from "./waveform.mjs";
import { ZoomArchive } from './zoom-archive.mjs';

const config = loadConfig();
const repository = new GitHubArchiveRepository(config);
const domain = new AudioArchiveDomain(repository, config);
const waveformService = new WaveformService({
  ffmpegPath: process.env.FFMPEG_BIN,
  ffprobePath: process.env.FFPROBE_BIN,
  resolveSource: (sessionId, blobId) => domain.waveformSource(sessionId, blobId),
  openPart: (assetId, signal) => repository.openReleaseAsset(assetId, signal)
});
await waveformService.initialize();
const app = createApp({ config, domain, waveformService, zoomArchive: new ZoomArchive(domain, { key: config.settingsKey }) });

const server = http.createServer(nodeHandler(app));

let stopping = false;
async function shutdown() {
  if (stopping) return; stopping = true;
  server.close();
  await waveformService.close();
}
process.once("SIGTERM", shutdown);
process.once("SIGINT", shutdown);

server.listen(config.port, "0.0.0.0", () => {
  console.log(JSON.stringify({ level: "info", message: "gateway_started", port: config.port }));
});
