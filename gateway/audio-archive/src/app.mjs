import { randomUUID } from "node:crypto";
import { LoginThrottle, clearSessionCookie, createSession, readSession, requireCsrf, verifyPassword } from "./auth.mjs";
import { ValidationError, assertUuid, hashIdempotencyKey } from "./validation.mjs";

const JSON_LIMIT = 1024 * 1024;
const SAFE_METHODS = new Set(["GET", "HEAD", "OPTIONS"]);
const GATEWAY_ORIGIN = "https://meserproject.duckdns.org";

const PRESENTATION_HEADERS = Object.freeze({
  "Cache-Control": "no-store",
  "Content-Type": "text/html; charset=utf-8",
  "Referrer-Policy": "no-referrer",
  "X-Content-Type-Options": "nosniff"
});

function json(value, status = 200, headers = {}) {
  return new Response(JSON.stringify(value), { status, headers: { "Content-Type": "application/json; charset=utf-8", ...headers } });
}

function withCookies(response, cookies) {
  const headers = new Headers(response.headers);
  for (const cookie of cookies) headers.append("Set-Cookie", cookie);
  return new Response(response.body, { status: response.status, statusText: response.statusText, headers });
}

function presentation(body, frameAncestors) {
  return new Response(body, { headers: { ...PRESENTATION_HEADERS,
    "Content-Security-Policy": `default-src 'none'; script-src 'nonce-meser-s10a'; connect-src 'self'; form-action 'self'; base-uri 'none'; frame-ancestors ${frameAncestors}`
  } });
}

function bootstrapPage({ verify = false, denied = false } = {}) {
  const status = denied ? "Пароль не подошёл. Повторите ввод." : verify ? "Проверяем защищённый сеанс…" : "Введите служебный пароль непосредственно на защищённом шлюзе.";
  return presentation(`<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Подключение аудиоархива</title><body><main><h1>Подключение Safari к аудиоархиву</h1><p>Safari требует отдельного подтверждения на стороне архива. Пароль останется на этой странице.</p><form method="post" action="/safari-bootstrap"><label>Общий служебный пароль <input name="password" type="password" autocomplete="current-password" required maxlength="256"></label><button type="submit">Подтвердить подключение</button></form><p id="status" role="status">${status}</p><button id="close" type="button">Вернуться в портал / закрыть вкладку</button></main><script nonce="meser-s10a">const status=document.getElementById("status");document.getElementById("close").addEventListener("click",()=>window.close());${verify ? `fetch("/v1/session",{credentials:"include",cache:"no-store"}).then(async response=>{if(!response.ok)throw new Error();const value=await response.json();if(value?.authenticated!==true)throw new Error();status.textContent="Защищённый сеанс готов. Вернитесь в портал и разрешите доступ в появившемся окне.";}).catch(()=>{status.textContent="Safari не подтвердил сеанс. Введите пароль ещё раз.";});` : ""}</script></body></html>`, "'none'");
}

function bootstrapRedirect(location, cookies = []) {
  const headers = new Headers({ ...PRESENTATION_HEADERS, Location: location,
    "Content-Security-Policy": "default-src 'none'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'"
  });
  for (const cookie of cookies) headers.append("Set-Cookie", cookie);
  return new Response(null, { status: 303, headers });
}

function storageAccessBridgePage(allowedOrigin) {
  return presentation(`<!doctype html><html lang="ru"><meta charset="utf-8"><meta name="viewport" content="width=device-width"><title>Доступ Safari</title><body><p id="status" role="status">Проверяем доступ Safari…</p><button id="grant" type="button" hidden>Разрешить доступ к архиву</button><script nonce="meser-s10a">const parentOrigin=${JSON.stringify(allowedOrigin)};const status=document.getElementById("status");const grant=document.getElementById("grant");const send=value=>parent.postMessage({type:"meser-storage-access",version:1,status:value},parentOrigin);async function inspect(){if(typeof document.hasStorageAccess!=="function"||typeof document.requestStorageAccess!=="function"){status.textContent="Этот браузер не поддерживает запрос доступа.";send("unsupported");return;}try{if(await document.hasStorageAccess()){status.textContent="Доступ подтверждён.";send("granted");return;}status.textContent="Нажмите кнопку, чтобы разрешить Safari доступ к аудиоархиву.";grant.hidden=false;send("required");}catch{status.textContent="Не удалось проверить доступ.";send("error");}}grant.addEventListener("click",async()=>{grant.disabled=true;try{await document.requestStorageAccess();status.textContent="Доступ подтверждён.";send("granted");}catch{status.textContent="Доступ не разрешён. Можно повторить после подключения в отдельной вкладке.";grant.disabled=false;send("denied");}});inspect();</script></body></html>`, allowedOrigin);
}

function isGatewaySessionProof(request) {
  return request.headers.get("origin") === GATEWAY_ORIGIN ||
    (request.headers.get("sec-fetch-site") === "same-origin" && request.headers.get("sec-fetch-mode") === "cors");
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
      if (url.pathname === "/safari-bootstrap" && request.method === "GET") {
        return bootstrapPage({ verify: url.searchParams.get("verify") === "1", denied: url.searchParams.get("denied") === "1" });
      }
      if (url.pathname === "/storage-access-bridge" && request.method === "GET") return storageAccessBridgePage(config.allowedOrigin);
      if (url.pathname === "/safari-bootstrap" && request.method === "POST") {
        if (request.headers.get("origin") !== GATEWAY_ORIGIN) { const error = new Error("Origin is not allowed"); error.status = 403; throw error; }
        throttle.check(request);
        if (!(request.headers.get("content-type") || "").toLowerCase().startsWith("application/x-www-form-urlencoded")) {
          const error = new ValidationError("Content-Type must be application/x-www-form-urlencoded"); error.status = 415; throw error;
        }
        const bytes = Buffer.from(await request.arrayBuffer());
        if (bytes.byteLength > 4096) { const error = new ValidationError("Request body is too large"); error.status = 413; throw error; }
        const password = new URLSearchParams(bytes.toString("utf8")).get("password");
        if (!await verifyPassword(password, config.sharedPasswordVerifier)) {
          throttle.failure(request);
          return bootstrapRedirect("/safari-bootstrap?denied=1");
        }
        throttle.success(request);
        const session = createSession(config.sessionSigningSecret, config.sessionLifetimeSeconds, clock());
        return bootstrapRedirect("/safari-bootstrap?verify=1", session.cookies);
      }
      if (url.pathname === "/v1/session" && request.method === "GET" && isGatewaySessionProof(request)) {
        const session = requireSession(request, config, clock);
        return json({ authenticated: true, expiresAt: session.expiresAt, csrfToken: session.csrfToken }, 200, { "Cache-Control": "no-store" });
      }
      requireOrigin(request, config.allowedOrigin);
      if (request.method === "OPTIONS") return cors(new Response(null, { status: 204 }), config.allowedOrigin);
      if (url.pathname === "/v1/config" && request.method === "GET") {
        return cors(json({ schemaVersion: 1, acceptedPartSize: config.acceptedPartBytes, maximumPartSize: 64 * 1024 * 1024,
          maximumSessionSize: 500 * 1024 * 1024, speakerProjectHistory: 1 }), config.allowedOrigin);
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
        return cors(withCookies(json({ authenticated: true, csrfToken: session.csrfToken }, 200), session.cookies), config.allowedOrigin);
      }
      if (url.pathname === "/v1/session/logout" && request.method === "POST") {
        const existing = readSession(request, config.sessionSigningSecret, clock());
        if (existing) requireCsrf(request, existing);
        return cors(withCookies(json({ authenticated: false }, 200), clearSessionCookie()), config.allowedOrigin);
      }
      const session = requireSession(request, config, clock);
      if (url.pathname === "/v1/session" && request.method === "GET") {
        return cors(json({ authenticated: true, expiresAt: session.expiresAt, csrfToken: session.csrfToken }), config.allowedOrigin);
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
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)\/content$/)) && request.method === "GET") {
        const result = await domain.downloadSourcePart(assertUuid(match[0], "sessionId"), assertUuid(match[1], "blobId"), Number(match[2]));
        return cors(new Response(result.bytes, { status: 200, headers: {
          "Content-Type": "application/octet-stream", "Content-Length": String(result.bytes.byteLength),
          "Content-Disposition": `attachment; filename="${result.assetName}"`
        } }), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/announcement\/publications$/)) && request.method === "POST") {
        return cors(json(await domain.beginAnnouncementPublication(assertUuid(match[0], "sessionId"), await jsonBody(request)), 201), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/speaker\/saves$/)) && request.method === "POST") {
        return cors(json(await domain.beginSpeakerPublication(assertUuid(match[0], "sessionId"), await jsonBody(request)), 201), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/announcement\/([^/]+)$/)) && request.method === "GET") {
        return cors(json(await domain.getAnnouncementOutput(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/speaker\/([^/]+)$/)) && request.method === "GET") {
        return cors(json(await domain.getSpeakerOutput(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/announcement\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)\/content$/)) && request.method === "GET") {
        const result = await domain.downloadAnnouncementPart(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"),
          assertUuid(match[2], "blobId"), Number(match[3]));
        return cors(new Response(result.bytes, { status: 200, headers: {
          "Content-Type": "application/octet-stream", "Content-Length": String(result.bytes.byteLength),
          "Content-Disposition": `attachment; filename="${result.assetName}"`
        } }), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/outputs\/speaker\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)\/content$/)) && request.method === "GET") {
        const result = await domain.downloadSpeakerPart(assertUuid(match[0], "sessionId"), assertUuid(match[1], "outputId"),
          assertUuid(match[2], "blobId"), Number(match[3]));
        return cors(new Response(result.bytes, { status: 200, headers: {
          "Content-Type": "application/octet-stream", "Content-Length": String(result.bytes.byteLength),
          "Content-Disposition": `attachment; filename="${result.assetName}"`
        } }), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/announcement-publications\/([^/]+)$/)) && request.method === "GET") {
        return cors(json(await domain.getAnnouncementPublication(assertUuid(match[0], "transactionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/speaker-saves\/([^/]+)$/)) && request.method === "GET") {
        return cors(json(await domain.getSpeakerPublication(assertUuid(match[0], "transactionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/announcement-publications\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)$/)) && request.method === "PUT") {
        const maximum = config.acceptedPartBytes;
        const declared = Number(request.headers.get("content-length"));
        if (Number.isFinite(declared) && declared > maximum) { const error = new ValidationError("Part is too large"); error.status = 413; throw error; }
        const bytes = Buffer.from(await request.arrayBuffer());
        if (bytes.byteLength < 1 || bytes.byteLength > maximum) { const error = new ValidationError("Part is too large or empty"); error.status = 413; throw error; }
        const result = await domain.uploadAnnouncementPart(assertUuid(match[0], "transactionId"), assertUuid(match[1], "blobId"), Number(match[2]), bytes,
          request.headers.get("x-part-sha256"), request.headers.get("idempotency-key"));
        return cors(json(result), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/speaker-saves\/([^/]+)\/blobs\/([^/]+)\/parts\/(\d+)$/)) && request.method === "PUT") {
        const maximum = config.acceptedPartBytes;
        const declared = Number(request.headers.get("content-length"));
        if (Number.isFinite(declared) && declared > maximum) { const error = new ValidationError("Part is too large"); error.status = 413; throw error; }
        const bytes = Buffer.from(await request.arrayBuffer());
        if (bytes.byteLength < 1 || bytes.byteLength > maximum) { const error = new ValidationError("Part is too large or empty"); error.status = 413; throw error; }
        const result = await domain.uploadSpeakerPart(assertUuid(match[0], "transactionId"), assertUuid(match[1], "blobId"), Number(match[2]), bytes,
          request.headers.get("x-part-sha256"), request.headers.get("idempotency-key"));
        return cors(json(result), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/announcement-publications\/([^/]+)\/(finalize|cancel|discard)$/)) && request.method === "POST") {
        const body = actionBody(await jsonBody(request));
        const transactionId = assertUuid(match[0], "transactionId");
        if (match[1] === "finalize") return cors(json(await domain.finalizeAnnouncementPublication(transactionId)), config.allowedOrigin);
        return cors(json(await domain.cancelAnnouncementPublication(transactionId, body, match[1] === "discard")), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/speaker-saves\/([^/]+)\/(finalize|cancel|discard)$/)) && request.method === "POST") {
        const body = actionBody(await jsonBody(request));
        const transactionId = assertUuid(match[0], "transactionId");
        if (match[1] === "finalize") return cors(json(await domain.finalizeSpeakerPublication(transactionId)), config.allowedOrigin);
        return cors(json(await domain.cancelSpeakerPublication(transactionId, body, match[1] === "discard")), config.allowedOrigin);
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
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/projects\/speaker$/)) && request.method === "GET") {
        return cors(json(await domain.speakerProjectHistory(assertUuid(match[0], "sessionId"))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/projects\/speaker\/states\/(\d+)$/)) && request.method === "GET") {
        return cors(json(await domain.getSpeakerProjectState(assertUuid(match[0], "sessionId"), Number(match[1]))), config.allowedOrigin);
      }
      if ((match = routeMatch(url.pathname, /^\/v1\/source-sessions\/([^/]+)\/projects\/speaker\/continuations$/)) && request.method === "POST") {
        return cors(json(await domain.continueSpeakerProject(assertUuid(match[0], "sessionId"), await jsonBody(request))), config.allowedOrigin);
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
