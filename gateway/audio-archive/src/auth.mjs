import { createHmac, randomBytes, scrypt as scryptCallback, timingSafeEqual } from "node:crypto";
import { promisify } from "node:util";
import { ValidationError } from "./validation.mjs";

const scrypt = promisify(scryptCallback);
export const SERVICE_COOKIE_NAME = "__Host-meser_service_session";
export const RETIRED_COOKIE_NAMES = Object.freeze([
  "__Host-meser_audio_session",
  "__Host-meser_audio_storage_session"
]);

function base64url(value) {
  return Buffer.from(value).toString("base64url");
}

function fixedTimeEqual(left, right) {
  const leftHash = createHmac("sha256", "meser-fixed-compare").update(String(left)).digest();
  const rightHash = createHmac("sha256", "meser-fixed-compare").update(String(right)).digest();
  return timingSafeEqual(leftHash, rightHash);
}

export async function createPasswordVerifier(password, salt = randomBytes(16), parameters = { N: 32768, r: 8, p: 1 }) {
  if (typeof password !== "string" || password.length < 8 || password.length > 256) throw new ValidationError("Password length is invalid");
  const result = await scrypt(password, salt, 32, { ...parameters, maxmem: 64 * 1024 * 1024 });
  return `scrypt$${parameters.N}$${parameters.r}$${parameters.p}$${base64url(salt)}$${base64url(result)}`;
}

export async function verifyPassword(password, verifier) {
  if (typeof password !== "string" || password.length < 1 || password.length > 256 || typeof verifier !== "string") return false;
  const [algorithm, nText, rText, pText, saltText, expectedText, ...extra] = verifier.split("$");
  const N = Number(nText); const r = Number(rText); const p = Number(pText);
  if (algorithm !== "scrypt" || extra.length || !Number.isSafeInteger(N) || N < 16384 || N > 65536 ||
      !Number.isSafeInteger(r) || r < 1 || r > 16 || !Number.isSafeInteger(p) || p < 1 || p > 4) return false;
  let salt; let expected;
  try {
    salt = Buffer.from(saltText, "base64url"); expected = Buffer.from(expectedText, "base64url");
  } catch {
    return false;
  }
  if (salt.length < 16 || salt.length > 64 || expected.length !== 32) return false;
  const actual = await scrypt(password, salt, expected.length, { N, r, p, maxmem: 128 * N * r + 8 * 1024 * 1024 });
  return timingSafeEqual(actual, expected);
}

function signature(sessionId, secret) {
  return createHmac("sha256", secret).update(sessionId).digest("base64url");
}

function parseCookies(header) {
  return Object.fromEntries(String(header || "").split(";").map((part) => {
    const position = part.indexOf("=");
    return position < 0 ? [part.trim(), ""] : [part.slice(0, position).trim(), part.slice(position + 1).trim()];
  }).filter(([key]) => key));
}

export class SessionRegistry {
  constructor({ clock = () => Date.now(), maxEntries = 256 } = {}) {
    if (!Number.isSafeInteger(maxEntries) || maxEntries < 1) throw new Error("Session registry limit is invalid");
    this.clock = clock;
    this.maxEntries = maxEntries;
    this.sessions = new Map();
  }

  prune(now = this.clock()) {
    for (const [sessionId, session] of this.sessions) {
      if (session.expiresAt * 1000 <= now) this.sessions.delete(sessionId);
    }
    while (this.sessions.size >= this.maxEntries) this.sessions.delete(this.sessions.keys().next().value);
  }

  create(lifetimeSeconds, now = this.clock()) {
    this.prune(now);
    const session = Object.freeze({
      sessionId: randomBytes(24).toString("base64url"),
      csrfToken: randomBytes(32).toString("base64url"),
      issuedAt: Math.floor(now / 1000),
      expiresAt: Math.floor(now / 1000) + lifetimeSeconds
    });
    this.sessions.set(session.sessionId, session);
    return session;
  }

  get(sessionId, now = this.clock()) {
    const session = this.sessions.get(sessionId);
    if (!session || session.expiresAt * 1000 <= now) {
      if (session) this.sessions.delete(sessionId);
      return null;
    }
    return session;
  }

  revoke(sessionId) {
    return this.sessions.delete(sessionId);
  }
}

export function createSession(sessionSecret, lifetimeSeconds, registry, now = Date.now()) {
  if (typeof sessionSecret !== "string" || sessionSecret.length < 32) throw new Error("SESSION_SIGNING_SECRET must contain at least 32 characters");
  if (!(registry instanceof SessionRegistry)) throw new Error("A session registry is required");
  const session = registry.create(lifetimeSeconds, now);
  const value = `${session.sessionId}.${signature(session.sessionId, sessionSecret)}`;
  const cookie = `${SERVICE_COOKIE_NAME}=${value}; Path=/; Max-Age=${lifetimeSeconds}; Secure; HttpOnly; SameSite=Lax`;
  return { cookie, cookies: [cookie, ...retiredCookieClears()], session };
}

function retiredCookieClears() {
  return RETIRED_COOKIE_NAMES.map((name) => `${name}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax`);
}

export function clearSessionCookies() {
  return [`${SERVICE_COOKIE_NAME}=; Path=/; Max-Age=0; Secure; HttpOnly; SameSite=Lax`, ...retiredCookieClears()];
}

export function readSession(request, sessionSecret, registry, now = Date.now()) {
  const value = parseCookies(request.headers.get("cookie"))[SERVICE_COOKIE_NAME];
  if (!value) return null;
  const [sessionId, suppliedSignature, ...extra] = value.split(".");
  if (!sessionId || !suppliedSignature || extra.length || !fixedTimeEqual(suppliedSignature, signature(sessionId, sessionSecret))) return null;
  return registry.get(sessionId, now);
}

export function requireCsrf(request, session) {
  const supplied = request.headers.get("x-csrf-token");
  if (!supplied || !fixedTimeEqual(supplied, session.csrfToken)) {
    const error = new Error("CSRF validation failed");
    error.status = 403;
    throw error;
  }
}

export class LoginThrottle {
  constructor({ clock = () => Date.now(), maxEntries = 256, windowMs = 5 * 60_000, maxFailures = 5, blockMs = 15 * 60_000 } = {}) {
    this.clock = clock;
    this.maxEntries = maxEntries;
    this.windowMs = windowMs;
    this.maxFailures = maxFailures;
    this.blockMs = blockMs;
    this.entries = new Map();
  }

  key(request) {
    const address = request.headers.get("x-forwarded-for")?.split(",")[0].trim() || "unknown";
    const agent = request.headers.get("user-agent") || "unknown";
    return createHmac("sha256", "meser-login-throttle").update(`${address}\0${agent}`).digest("hex");
  }

  prune() {
    const now = this.clock();
    for (const [key, value] of this.entries) if (value.blockedUntil <= now && value.windowStarted + this.windowMs <= now) this.entries.delete(key);
    while (this.entries.size >= this.maxEntries) this.entries.delete(this.entries.keys().next().value);
  }

  check(request) {
    const value = this.entries.get(this.key(request));
    if (value?.blockedUntil > this.clock()) {
      const error = new Error("Too many login attempts");
      error.status = 429;
      error.retryAfter = Math.ceil((value.blockedUntil - this.clock()) / 1000);
      throw error;
    }
  }

  failure(request) {
    this.prune();
    const key = this.key(request);
    const now = this.clock();
    const previous = this.entries.get(key);
    const value = !previous || previous.windowStarted + this.windowMs <= now ? { failures: 0, windowStarted: now, blockedUntil: 0 } : previous;
    value.failures++;
    if (value.failures >= this.maxFailures) value.blockedUntil = now + this.blockMs;
    this.entries.set(key, value);
  }

  success(request) {
    this.entries.delete(this.key(request));
  }
}
