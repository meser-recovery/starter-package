import http from "node:http";
import { Readable } from "node:stream";
import { createApp } from "./app.mjs";
import { loadConfig } from "./config.mjs";
import { AudioArchiveDomain } from "./domain.mjs";
import { GitHubArchiveRepository } from "./github.mjs";

const config = loadConfig();
const repository = new GitHubArchiveRepository(config);
const domain = new AudioArchiveDomain(repository, config);
const app = createApp({ config, domain });

const server = http.createServer(async (incoming, outgoing) => {
  try {
    const origin = `http://${incoming.headers.host || "localhost"}`;
    const request = new Request(new URL(incoming.url || "/", origin), {
      method: incoming.method,
      headers: incoming.headers,
      body: ["GET", "HEAD"].includes(incoming.method || "GET") ? undefined : Readable.toWeb(incoming),
      duplex: "half"
    });
    const response = await app(request);
    outgoing.writeHead(response.status, Object.fromEntries(response.headers));
    if (response.body) Readable.fromWeb(response.body).pipe(outgoing);
    else outgoing.end();
  } catch {
    outgoing.writeHead(500, { "Content-Type": "application/json; charset=utf-8" });
    outgoing.end(JSON.stringify({ error: "Внутренняя ошибка шлюза." }));
  }
});

server.listen(config.port, "0.0.0.0", () => {
  console.log(JSON.stringify({ level: "info", message: "gateway_started", port: config.port }));
});
