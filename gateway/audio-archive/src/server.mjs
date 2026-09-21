import http from "node:http";
import { Readable } from "node:stream";
import { createApp } from "./app.mjs";
import { loadConfig } from "./config.mjs";
import { AudioArchiveDomain } from "./domain.mjs";
import { GitHubArchiveRepository } from "./github.mjs";
import { nodeResponseHeaders } from "./http-adapter.mjs";
import { WaveformService } from "./waveform.mjs";

const config = loadConfig();
const repository = new GitHubArchiveRepository(config);
const domain = new AudioArchiveDomain(repository, config);
const waveformService = new WaveformService({
  resolveSource: (sessionId, blobId) => domain.waveformSource(sessionId, blobId),
  openPart: (assetId, signal) => repository.openReleaseAsset(assetId, signal)
});
await waveformService.initialize();
const app = createApp({ config, domain, waveformService });

const server = http.createServer(async (incoming, outgoing) => {
  const controller = new AbortController();
  const aborted = () => controller.abort();
  incoming.once("aborted", aborted);
  outgoing.once("close", () => { if (!outgoing.writableFinished) controller.abort(); });
  try {
    const origin = `http://${incoming.headers.host || "localhost"}`;
    const request = new Request(new URL(incoming.url || "/", origin), {
      method: incoming.method,
      headers: incoming.headers,
      body: ["GET", "HEAD"].includes(incoming.method || "GET") ? undefined : Readable.toWeb(incoming),
      duplex: "half", signal: controller.signal
    });
    const response = await app(request);
    outgoing.writeHead(response.status, nodeResponseHeaders(response.headers));
    if (response.body) Readable.fromWeb(response.body).pipe(outgoing);
    else outgoing.end();
  } catch {
    outgoing.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
    outgoing.end(JSON.stringify({ error: "Внутренняя ошибка шлюза." }));
  }
});

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
