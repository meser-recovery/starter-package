import { randomUUID } from "node:crypto";
import { LoginThrottle, clearSessionCookie, createSession, readSession, requireCsrf, verifyPassword } from "./auth.mjs";
import { ValidationError, assertUuid, hashIdempotencyKey } from "./validation.mjs";

const JSON_LIMIT = 1024 * 1024;
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);

function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json; charset=utf-8", ...headers } });
}

async function jsonBody(request, maximum = JSON_LIMIT) {
  const contentType = request.headers.get("content-type") || "";
  if (!contentType.toLowerCase().startsWith("application/json")) throw new ValidationError("Content-Type must be application/json");
  const declared = Number(request.headers.get("content-length"));
  if (Number.isFinite(declared) && declared > maximum) {
    const error = new ValidationError("Request body is too large"); error.status = 413; throw error;
  }
  const bytes = Buffer.from(await request.arrayBuffer());
  if (bytes.byteLength > maximum) { const error = new ValidationError("Request body is too large"); error.status = 413; throw error; }
  try { return JSON.parse(bytes.toString("utf8")); } catch { throw new ValidationError("Request body is not valid JSON"); }
}

function cors(response, origin) {
  const headers = new Headers(response.headers);
  headers.set("Access-Control-Allow-Origin", origin);
  headers.set("Access-Control-Allow-Credentials", "true");
  headers.set("Access-Control-Allow-Methods", "GET, HEAD, POST, PUT, PATCH, OPTIONS");
  headers.set("Access-Control-Allow-Headers", "Content-Type, X-CSRF-Token, X-Part-SHA256, Idempotency-Key");
  headers.set("Access-Control-Max-Age", "600");
  headers.append("Vary", "Origin");
  headers.set("Cache-Control", "no-store");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function requireOrigin(request, allowedOrigin) {
  if (request.headers.get("origin") !== allowedOrigin) {
    const error = new Error("Origin is not allowed"); error.status = 403; throw error;
  }
}

function requireSession(request, config, clock) {
  const session = readSession(request, config.sessionSigningSecret, clock());
  if (!session) { const error = new Error("Archive session is required"); error.status = 401; throw error; }
  if (!SAFE_METHODS.has(request.method)) requireCsrf(request, session);
  return session;
}

function routeMatch(pathname, pattern) {
  const match = pathname.match(pattern);
  if (!match) return null;
  try {
    return match.slice(1).map((value) => decodeURIComponent(value));
  } catch {
    throw new ValidationError("Request path is malformed");
  }
}

function actionBody(body) {
  hashIdempotencyKey(body?.idempotencyKey);
  return body;
}

export function createApp({ config, domain, throttle = new LoginThrottle(), clock = () => Date.now() }) {
  return async function handle(request) {
    const requestId = randomUUID();
    const url = new URL(request.url);
    const started = clock();
    try {
      if (url.pathname === "/healthz" && request.method === "GET") return json({ ok: true, service: "audio-archive-gateway" });
      requireOrigin(request, config.allowedOrigin);
      if (request.method === "OPTIONS") return cors(new Response(null, { status: 204 }), config.allowedOrigin);
      if (url.pathname === "/v1/config" && request.method === "GET") {
        return cors(json({ schemaVersion: 1, acceptedPartSize: config.acceptedPartBytes, maximumPartSize: 64 * 1024 * 1024, maximumSessionSize: 500 * 1024 * 1024 }), config.allowedOrigin);
      }
      if (url.pathname === "/v1/session/login" && request.method === "POST") {
        throttle.check(request);
        const body = await jsonBody(request, 4096);
        if (!body || Object.keys(body).length !== 1 || typeof body.password !== "string" ||
            !await verifyPassword(body.password, config.sharedPasswordVerifier)) {
          throttle.failure(request);
          return cors(json({ error: "Неверный пароль." }, 401), config.allowedOrigin);
        }
        throttle.success(request);
        const session = createSession(config.sessionSigningSecret, config.sessionLifetimeSeconds, clock());
        return cors(json({ authenticated: true, csrfToken: session.csrfToken }, 200, { "Set-Cookie": session.cookie }), config.allowedOrigin);
      }
      const session = requireSession(request, config, clock);
      if (url.pathname === "/v1/session" && request.method === "GET") {
        return cors(json({ authenticated: true, expiresAt: session.expiresAt, csrfToken: session.csrfToken }), config.allowedOrigin);
      }
      if (url.pathname === "/v1/session/logout" && request.method === "POST") {
        return cors(json({ authenticated: false }, 200, { "Set-Cookie": clearSessionCookie() }), config.allowedOrigin);
      }
      if (url.pathname === "/v1/source-sessions" && request.method === "GET") {
        return cors(json(await domain.listSessions(url.searchParams.get("lifecycle") || "incoming")), config.allowedOrigin);
      }
      if (url.pathname === "/v1/source-sessions/ingestions" && request.method === "POST") {
        return cors(json(await domain.beginIngestion(await jsonBody(request)), 201), config.allowedOrigin);
      }
      let match;
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/ingestions\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)$/)) && request.method === "PUT") {
        const maximum = config.acceptedPartBytes;
        const declared = Number(request.headers.get("content-length"));
        if (Number.isFinite(declared) && declared > maximum) { const error = new ValidationError("Part is too large"); error.status = 413; throw error; }
        const bytes = Buffer.from(await request.arrayBuffer());
        if (bytes.byteLength < 1 || bytes.byteLength > maximum) { const error = new ValidationError("Part is too large or empty"); error.status = 413; throw error; }
        const result = await domain.uploadPart(assertUuid(match[0], "transactionId"), assertUuid(match[1], "blobId"), Number(match[2]), bytes,
          request.headers.get("x-part-sha256"), request.headers.get("idempotency-key"));
        return cors(json(result), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/ingestions\/([^/]+)\/finalize$/)) && request.method === "POST") {
        actionBody(await jsonBody(request));
        return cors(json(await domain.finalizeIngestion(assertUuid(match[0], "transactionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)$/))) {
        const sessionId = assertUuid(match[0], "sessionId");
        if (request.method === "GET") return cors(json(await domain.getSession(sessionId)), config.allowedOrigin);
        if (request.method === "PATCH") return cors(json(await domain.updateMetadata(sessionId, await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/workflows\/(announcement|speaker)\/status$/)) && request.method === "PUT") {
        return cors(json(await domain.updateWorkflow(assertUuid(match[0], "sessionId"), match[1], await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/drafts\/(announcement|speaker)$/))) {
        const sessionId = assertUuid(match[0], "sessionId");
        if (request.method === "GET") return cors(json({ draft: await domain.loadDraft(sessionId, match[1]) }), config.allowedOrigin);
        if (request.method === "PUT") return cors(json(await domain.saveDraft(sessionId, match[1], await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/(archive|restore)$/)) && request.method === "POST") {
        return cors(json(await domain.setLifecycle(assertUuid(match[0], "sessionId"), match[1] === "archive" ? "archived" : "incoming", await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/deletion-preview$/)) && request.method === "GET") {
        return cors(json(await domain.dependencyPreview(assertUuid(match[0], "sessionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/(announcement|speaker)\/versions\/(\d+)\/delete$/)) && request.method === "POST") {
        return cors(json(await domain.deleteOutputVersion(assertUuid(match[0], "sessionId"), match[1], Number(match[2]), await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/(announcement|speaker)\/delete$/)) && request.method === "POST") {
        return cors(json(await domain.deleteOutputSeries(assertUuid(match[0], "sessionId"), match[1], await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/sources\/delete$/)) && request.method === "POST") {
        return cors(json(await domain.deleteSources(assertUuid(match[0], "sessionId"), await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/purge$/)) && request.method === "POST") {
        return cors(json(await domain.purgeSession(assertUuid(match[0], "sessionId"), await jsonBody(request))), config.allowedOrigin);
      }
      if (url.pathname === "/v1/maintenance/incomplete" && request.method === "GET") {
        return cors(json(await domain.listIncomplete()), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/maintenance\/incomplete\/([^/]+)\/(resume|retry|discard)$/)) && request.method === "POST") {
        actionBody(await jsonBody(request));
        return cors(json(await domain.recoverIncomplete(assertUuid(match[0], "transactionId"), match[1])), config.allowedOrigin);
      }
      if (url.pathname === "/v1/maintenance/catalog/rebuild" && request.method === "POST") {
        actionBody(await jsonBody(request));
        return cors(json(await domain.rebuildCatalog()), config.allowedOrigin);
      }
      return cors(json({ error: "Операция не найдена." }, 404), config.allowedOrigin);
    } catch (error) {
      const status = Number.isInteger(error?.status) && error.status >= 400 && error.status < 600 ? error.status : 500;
      const safe = status < 500 ? error.message : "Внутренняя ошибка шлюза.";
      console.error(JSON.stringify({ level: "error", message: "request_failed", requestId, method: request.method, path: url.pathname, status,
        durationMs: clock() - started, errorType: error?.name || "Error" }));
      const headers = error?.retryAfter ? { "Retry-After": String(error.retryAfter) } : {};
      const response = json({ error: safe, requestId, ...(error instanceof ValidationError && error.details ? { details: error.details } : {}) }, status, headers);
      return request.headers.get("origin") === config.allowedOrigin ? cors(response, config.allowedOrigin) : response;
    }
  };
}
