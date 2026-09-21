import { randomUUID } from "node:crypto";
import { LoginThrottle, SessionRegistry, clearSessionCookies, createSession, readSession, requireCsrf, verifyPassword } from "./auth.mjs";
import { ValidationError, assertUuid, hashIdempotencyKey } from "./validation.mjs";
import { waveformResponse } from "./waveform.mjs";

const JSON_LIMIT = 1024 * 1024;
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const ORDINARY_SERVICE_DOCUMENTS = new Set([
  "/", "/index.html", "/Calendar.html", "/Google-Drive.html",
  "/Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html"
]);

function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json; charset=utf-8", ...headers } });
}

function withCookies(response, cookies) {
  const headers = new Headers(response.headers);
  for (const cookie of cookies) headers.append("Set-Cookie", cookie);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
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

function apiResponse(response) {
  const headers = new Headers(response.headers);
  headers.set("Cache-Control", "no-store");
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function requireOrigin(request, allowedOrigin) {
  if (request.headers.get("origin") !== allowedOrigin) {
    const error = new Error("Origin is not allowed"); error.status = 403; throw error;
  }
}

function requireSession(request, config, sessions, clock) {
  const session = readSession(request, config.sessionSigningSecret, sessions, clock());
  if (!session) { const error = new Error("Service session is required"); error.status = 401; throw error; }
  return session;
}

function canonicalDocumentReturn(value, allowedOrigin) {
  let target;
  try { target = new URL(value || "/", allowedOrigin); } catch { return "/"; }
  if (target.origin !== allowedOrigin || target.hash || target.username || target.password) return "/";
  if (ORDINARY_SERVICE_DOCUMENTS.has(target.pathname)) return target.search ? "/" : target.pathname;
  const keys = [...target.searchParams.keys()];
  if (new Set(keys).size !== keys.length) return target.pathname;
  const uuid = input => typeof input === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(input);
  if (target.pathname === "/Audio-Archive.html") {
    if (keys.some(key => key !== "session")) return target.pathname;
    const session = target.searchParams.get("session");
    return session && uuid(session) ? `${target.pathname}?session=${encodeURIComponent(session)}` : target.pathname;
  }
  if (target.pathname === "/Audio-Editor.html") {
    const allowed = new Set(["session", "workflow", "projectRevision", "speakerOutput"]);
    if (keys.some(key => !allowed.has(key))) return target.pathname;
    const session = target.searchParams.get("session");
    const workflow = target.searchParams.get("workflow");
    const revision = target.searchParams.get("projectRevision");
    const output = target.searchParams.get("speakerOutput");
    if ((session && !uuid(session)) || (workflow && !["announcement", "speaker"].includes(workflow)) ||
        (revision && (!/^\d+$/.test(revision) || Number(revision) < 1)) || (output && !uuid(output))) return target.pathname;
    const clean = new URLSearchParams();
    if (session) clean.set("session", session);
    if (workflow) clean.set("workflow", workflow);
    if (revision) clean.set("projectRevision", revision);
    if (output) clean.set("speakerOutput", output);
    return `${target.pathname}${clean.size ? `?${clean}` : ""}`;
  }
  return "/";
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

export function createApp({ config, domain, waveformService = null, throttle = new LoginThrottle(), clock = () => Date.now(), sessionRegistry } = {}) {
  const sessions = sessionRegistry || new SessionRegistry({ clock, maxEntries: config.activeSessionLimit || 256 });
  return async function handle(request) {
    const requestId = randomUUID();
    const url = new URL(request.url);
    const started = clock();
    try {
      if (url.pathname === "/healthz" && request.method === "GET") return json({ ok: true, service: "audio-archive-gateway" });
      if (url.pathname === "/internal/auth-check" && request.method === "GET") {
        const session = readSession(request, config.sessionSigningSecret, sessions, clock());
        return new Response(null, { status: session ? 200 : 401, headers: {
          "Cache-Control": "no-store", "X-Service-Authenticated": session ? "true" : "false", "X-Service-Login": "/login"
        } });
      }
      if (url.pathname === "/internal/document-auth" && request.method === "GET") {
        const session = readSession(request, config.sessionSigningSecret, sessions, clock());
        if (session) return new Response(null, { status: 200, headers: {
          "Cache-Control": "no-store", "X-Service-Authenticated": "true"
        } });
        const intent = canonicalDocumentReturn(request.headers.get("x-forwarded-uri"), config.allowedOrigin);
        return new Response(null, { status: 303, headers: {
          "Cache-Control": "no-store", Location: `/login?return=${encodeURIComponent(intent)}`
        } });
      }
      if (url.pathname === "/v1/session/login" && request.method === "POST") {
        requireOrigin(request, config.allowedOrigin);
        throttle.check(request);
        const body = await jsonBody(request, 4096);
        if (!body || Object.keys(body).length !== 1 || typeof body.password !== "string" ||
            !await verifyPassword(body.password, config.sharedPasswordVerifier)) {
          throttle.failure(request);
          return apiResponse(json({ error: "Неверный пароль." }, 401));
        }
        throttle.success(request);
        const created = createSession(config.sessionSigningSecret, config.sessionLifetimeSeconds, sessions, clock());
        return apiResponse(withCookies(json({ authenticated: true }, 200), created.cookies));
      }
      if (url.pathname === "/v1/session/logout" && request.method === "POST") {
        requireOrigin(request, config.allowedOrigin);
        const existing = readSession(request, config.sessionSigningSecret, sessions, clock());
        if (existing) { requireCsrf(request, existing); sessions.revoke(existing.sessionId); }
        return apiResponse(withCookies(json({ authenticated: false }, 200), clearSessionCookies()));
      }
      if (request.method === "OPTIONS") {
        requireOrigin(request, config.allowedOrigin);
        return apiResponse(new Response(null, { status: 204 }));
      }
      const session = requireSession(request, config, sessions, clock);
      if (!SAFE_METHODS.has(request.method)) {
        requireOrigin(request, config.allowedOrigin);
        requireCsrf(request, session);
      }
      if (url.pathname === "/v1/session" && request.method === "GET") {
        return apiResponse(json({ authenticated: true, expiresAt: session.expiresAt, csrfToken: session.csrfToken }));
      }
      if (url.pathname === "/v1/config" && request.method === "GET") {
        return apiResponse(json({ schemaVersion: 1, acceptedPartSize: config.acceptedPartBytes, maximumPartSize: 64 * 1024 * 1024,
          maximumSessionSize: 500 * 1024 * 1024, speakerProjectHistory: 1 }));
      }
      if (url.pathname === "/v1/source-sessions" && request.method === "GET") {
        return apiResponse(json(await domain.listSessions(url.searchParams.get("lifecycle") || "incoming")), config.allowedOrigin);
      }
      if (url.pathname === "/v1/source-sessions/ingestions" && request.method === "POST") {
        return apiResponse(json(await domain.beginIngestion(await jsonBody(request)), 201), config.allowedOrigin);
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
        return apiResponse(json(result), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/ingestions\/([^/]+)\/finalize$/)) && request.method === "POST") {
        actionBody(await jsonBody(request));
        return apiResponse(json(await domain.finalizeIngestion(assertUuid(match[0], "transactionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)\/content$/)) && request.method === "GET") {
        const result = await domain.downloadSourcePart(assertUuid(match[0], "sessionId"), assertUuid(match[1], "blobId"), Number(match[2]));
        return apiResponse(new Response(result.bytes, { status: 200, headers: {
          "Content-Type": "application/octet-stream", "Content-Length": String(result.bytes.byteLength),
          "Content-Disposition": `attachment; filename="${result.assetName}"`
        } }), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/blobs\/([^/]+)\/waveform$/)) && request.method === "GET") {
        if ([...url.searchParams].length) throw new ValidationError("Waveform endpoint does not accept query parameters");
        if (!waveformService) { const error = new Error("Waveform service is unavailable"); error.status = 503; throw error; }
        return apiResponse(waveformResponse(await waveformService.get(assertUuid(match[0], "sessionId"), assertUuid(match[1], "blobId"), request.signal)), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/announcement\/publications$/)) && request.method === "POST") {
        return apiResponse(json(await domain.beginAnnouncementPublication(assertUuid(match[0], "sessionId"), await jsonBody(request)), 201), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/speaker\/saves$/)) && request.method === "POST") {
        return apiResponse(json(await domain.beginSpeakerPublication(assertUuid(match[0], "sessionId"), await jsonBody(request)), 201), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/announcement\/([^/]+)$/)) && request.method === "GET") {
        return apiResponse(json(await domain.getAnnouncementOutput(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/speaker\/([^/]+)$/)) && request.method === "GET") {
        return apiResponse(json(await domain.getSpeakerOutput(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/announcement\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)\/content$/)) && request.method === "GET") {
        const result = await domain.downloadAnnouncementPart(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"),
          assertUuid(match[2], "blobId"), Number(match[3]));
        return apiResponse(new Response(result.bytes, { status: 200, headers: {
          "Content-Type": "application/octet-stream", "Content-Length": String(result.bytes.byteLength),
          "Content-Disposition": `attachment; filename="${result.assetName}"`
        } }), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/speaker\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)\/content$/)) && request.method === "GET") {
        const result = await domain.downloadSpeakerPart(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"),
          assertUuid(match[2], "blobId"), Number(match[3]));
        return apiResponse(new Response(result.bytes, { status: 200, headers: {
          "Content-Type": "application/octet-stream", "Content-Length": String(result.bytes.byteLength),
          "Content-Disposition": `attachment; filename="${result.assetName}"`
        } }), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/announcement-publications\/([^/]+)$/)) && request.method === "GET") {
        return apiResponse(json(await domain.getAnnouncementPublication(assertUuid(match[0], "transactionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/speaker-saves\/([^/]+)$/)) && request.method === "GET") {
        return apiResponse(json(await domain.getSpeakerPublication(assertUuid(match[0], "transactionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/announcement-publications\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)$/)) && request.method === "PUT") {
        const maximum = config.acceptedPartBytes;
        const declared = Number(request.headers.get("content-length"));
        if (Number.isFinite(declared) && declared > maximum) { const error = new ValidationError("Part is too large"); error.status = 413; throw error; }
        const bytes = Buffer.from(await request.arrayBuffer());
        if (bytes.byteLength < 1 || bytes.byteLength > maximum) { const error = new ValidationError("Part is too large or empty"); error.status = 413; throw error; }
        const result = await domain.uploadAnnouncementPart(assertUuid(match[0], "transactionId"), assertUuid(match[1], "blobId"), Number(match[2]), bytes,
          request.headers.get("x-part-sha256"), request.headers.get("idempotency-key"));
        return apiResponse(json(result), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/speaker-saves\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)$/)) && request.method === "PUT") {
        const maximum = config.acceptedPartBytes;
        const declared = Number(request.headers.get("content-length"));
        if (Number.isFinite(declared) && declared > maximum) { const error = new ValidationError("Part is too large"); error.status = 413; throw error; }
        const bytes = Buffer.from(await request.arrayBuffer());
        if (bytes.byteLength < 1 || bytes.byteLength > maximum) { const error = new ValidationError("Part is too large or empty"); error.status = 413; throw error; }
        const result = await domain.uploadSpeakerPart(assertUuid(match[0], "transactionId"), assertUuid(match[1], "blobId"), Number(match[2]), bytes,
          request.headers.get("x-part-sha256"), request.headers.get("idempotency-key"));
        return apiResponse(json(result), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/announcement-publications\/([^/]+)\/(finalize|cancel|discard)$/)) && request.method === "POST") {
        const body = actionBody(await jsonBody(request));
        const transactionId = assertUuid(match[0], "transactionId");
        if (match[1] === "finalize") return apiResponse(json(await domain.finalizeAnnouncementPublication(transactionId)), config.allowedOrigin);
        return apiResponse(json(await domain.cancelAnnouncementPublication(transactionId, body, match[1] === "discard")), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/speaker-saves\/([^/]+)\/(finalize|cancel|discard)$/)) && request.method === "POST") {
        const body = actionBody(await jsonBody(request));
        const transactionId = assertUuid(match[0], "transactionId");
        if (match[1] === "finalize") return apiResponse(json(await domain.finalizeSpeakerPublication(transactionId)), config.allowedOrigin);
        return apiResponse(json(await domain.cancelSpeakerPublication(transactionId, body, match[1] === "discard")), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)$/))) {
        const sessionId = assertUuid(match[0], "sessionId");
        if (request.method === "GET") return apiResponse(json(await domain.getSession(sessionId)), config.allowedOrigin);
        if (request.method === "PATCH") return apiResponse(json(await domain.updateMetadata(sessionId, await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/workflows\/(announcement|speaker)\/status$/)) && request.method === "PUT") {
        return apiResponse(json(await domain.updateWorkflow(assertUuid(match[0], "sessionId"), match[1], await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/drafts\/(announcement|speaker)$/))) {
        const sessionId = assertUuid(match[0], "sessionId");
        if (request.method === "GET") return apiResponse(json({ draft: await domain.loadDraft(sessionId, match[1]) }), config.allowedOrigin);
        if (request.method === "PUT") return apiResponse(json(await domain.saveDraft(sessionId, match[1], await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/projects\/speaker$/)) && request.method === "GET") {
        return apiResponse(json(await domain.speakerProjectHistory(assertUuid(match[0], "sessionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/projects\/speaker\/states\/(\d+)$/)) && request.method === "GET") {
        return apiResponse(json(await domain.getSpeakerProjectState(assertUuid(match[0], "sessionId"), Number(match[1]))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/projects\/speaker\/continuations$/)) && request.method === "POST") {
        return apiResponse(json(await domain.continueSpeakerProject(assertUuid(match[0], "sessionId"), await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/(archive|restore)$/)) && request.method === "POST") {
        return apiResponse(json(await domain.setLifecycle(assertUuid(match[0], "sessionId"), match[1] === "archive" ? "archived" : "incoming", await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/deletion-preview$/)) && request.method === "GET") {
        return apiResponse(json(await domain.dependencyPreview(assertUuid(match[0], "sessionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/(announcement|speaker)\/versions\/(\d+)\/delete$/)) && request.method === "POST") {
        return apiResponse(json(await domain.deleteOutputVersion(assertUuid(match[0], "sessionId"), match[1], Number(match[2]), await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/(announcement|speaker)\/delete$/)) && request.method === "POST") {
        return apiResponse(json(await domain.deleteOutputSeries(assertUuid(match[0], "sessionId"), match[1], await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/sources\/delete$/)) && request.method === "POST") {
        return apiResponse(json(await domain.deleteSources(assertUuid(match[0], "sessionId"), await jsonBody(request))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/purge$/)) && request.method === "POST") {
        return apiResponse(json(await domain.purgeSession(assertUuid(match[0], "sessionId"), await jsonBody(request))), config.allowedOrigin);
      }
      if (url.pathname === "/v1/maintenance/incomplete" && request.method === "GET") {
        return apiResponse(json(await domain.listIncomplete()), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/maintenance\/incomplete\/([^/]+)\/(resume|retry|discard)$/)) && request.method === "POST") {
        actionBody(await jsonBody(request));
        return apiResponse(json(await domain.recoverIncomplete(assertUuid(match[0], "transactionId"), match[1])), config.allowedOrigin);
      }
      if (url.pathname === "/v1/maintenance/catalog/rebuild" && request.method === "POST") {
        actionBody(await jsonBody(request));
        return apiResponse(json(await domain.rebuildCatalog()), config.allowedOrigin);
      }
      return apiResponse(json({ error: "Операция не найдена." }, 404), config.allowedOrigin);
    } catch (error) {
      const status = Number.isInteger(error?.status) && error.status >= 400 && error.status < 600 ? error.status : 500;
      const safe = status < 500 ? error.message : "Внутренняя ошибка шлюза.";
      console.error(JSON.stringify({ level: "error", message: "request_failed", requestId, method: request.method, path: url.pathname, status,
        durationMs: clock() - started, errorType: error?.name || "Error" }));
      const headers = error?.retryAfter ? { "Retry-After": String(error.retryAfter) } : {};
      const waveformDiagnostic = error?.name === "WaveformError" ? {
        stage: error.stage || "load", exitStatus: Number.isInteger(error.exitStatus) ? error.exitStatus : null
      } : null;
      const response = json({ error: safe, requestId,
        ...(error instanceof ValidationError && error.details ? { details: error.details } : {}),
        ...(waveformDiagnostic ? { waveformDiagnostic } : {}) }, status, headers);
      return request.headers.get("origin") === config.allowedOrigin ? apiResponse(response, config.allowedOrigin) : response;
    }
  };
}
