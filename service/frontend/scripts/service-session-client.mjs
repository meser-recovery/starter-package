export function isUuid(value) {
  return typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value);
}

export class ServiceSessionGateway {
  constructor(fetchImpl = fetch) {
    this.fetchImpl = fetchImpl.bind(globalThis);
    this.csrfToken = null;
    this.authGeneration = 0;
  }

  async request(path, options = {}) {
    const { captureCsrf = true, ...fetchOptions } = options;
    const headers = new Headers(fetchOptions.headers || {});
    if (fetchOptions.body && typeof fetchOptions.body !== "string") {
      headers.set("Content-Type", "application/json");
      fetchOptions.body = JSON.stringify(fetchOptions.body);
    }
    if (!/^(GET|HEAD|OPTIONS)$/i.test(fetchOptions.method || "GET") && this.csrfToken) headers.set("X-CSRF-Token", this.csrfToken);
    const response = await this.fetchImpl(path, { credentials: "include", ...fetchOptions, headers });
    const payload = response.status === 204 ? null : await response.json().catch(() => null);
    if (!response.ok) {
      const error = new Error(payload?.error || "Служебная операция не выполнена.");
      error.status = response.status;
      throw error;
    }
    if (captureCsrf && payload?.csrfToken) this.csrfToken = payload.csrfToken;
    return payload;
  }

  sessionStatus({ captureCsrf = true } = {}) {
    return this.request("/v1/session", { captureCsrf });
  }

  invalidateAuthentication() {
    this.authGeneration += 1;
    this.csrfToken = null;
  }

  async login(password, { onState } = {}) {
    const generation = ++this.authGeneration;
    this.csrfToken = null;
    onState?.("checking-password");
    try {
      await this.request("/v1/session/login", { method: "POST", body: { password }, captureCsrf: false });
    } catch (error) {
      if (error?.status === 401) error.code = "invalid_password";
      throw error;
    }
    try {
      onState?.("verifying-session");
      const proof = await this.sessionStatus({ captureCsrf: false });
      if (proof?.authenticated !== true || typeof proof.csrfToken !== "string" || !proof.csrfToken) throw new Error("Сессия не подтверждена.");
      if (generation !== this.authGeneration) return Object.freeze({ authenticated: false, stale: true });
      this.csrfToken = proof.csrfToken;
      return proof;
    } catch (error) {
      if (generation === this.authGeneration) this.csrfToken = null;
      if (error?.status === 401) error.code = "session_replay_failed";
      throw error;
    }
  }

  async logout() {
    this.authGeneration += 1;
    try { return await this.request("/v1/session/logout", { method: "POST" }); }
    finally { this.csrfToken = null; }
  }
}
