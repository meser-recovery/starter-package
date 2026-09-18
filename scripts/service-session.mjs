export const SERVICE_SESSION_STATES = Object.freeze([
  "disconnected", "checking-password", "verifying-session", "connected", "denied", "throttled", "network-error", "server-error"
]);

export const SERVICE_SESSION_EXPIRED_MESSAGE = "Служебная сессия истекла. Войдите снова, чтобы продолжить.";

export class ServiceSessionController {
  constructor({ gateway, onState = () => {} }) {
    this.gateway = gateway;
    this.onState = onState;
    this.state = "disconnected";
    this.generation = 0;
  }

  transition(state, detail = null) {
    if (!SERVICE_SESSION_STATES.includes(state)) throw new Error("Неизвестное состояние служебной сессии.");
    this.state = state;
    this.onState({ state, detail, generation: this.generation });
  }

  async restore() {
    const generation = ++this.generation;
    this.transition("verifying-session");
    try {
      const proof = await this.gateway.sessionStatus({ captureCsrf: false });
      if (generation !== this.generation) return false;
      if (proof?.authenticated !== true || typeof proof.csrfToken !== "string" || !proof.csrfToken) throw Object.assign(new Error("Сессия не подтверждена."), { status: 401 });
      this.gateway.csrfToken = proof.csrfToken;
      this.transition("connected");
      return true;
    } catch (error) {
      if (generation !== this.generation) return false;
      this.gateway.csrfToken = null;
      this.transition("disconnected", error);
      return false;
    }
  }

  async login(password) {
    const generation = ++this.generation;
    this.gateway.csrfToken = null;
    this.transition("checking-password");
    try {
      const proof = await this.gateway.login(password, { onState: state => {
        if (generation === this.generation && state === "verifying-session") this.transition("verifying-session");
      } });
      if (generation !== this.generation) return false;
      if (proof?.authenticated !== true || !this.gateway.csrfToken) throw Object.assign(new Error("Сессия не подтверждена."), { status: 401 });
      this.transition("connected");
      return true;
    } catch (error) {
      if (generation !== this.generation) return false;
      this.gateway.csrfToken = null;
      if (error?.status === 401 && error?.code === "invalid_password") this.transition("denied", error);
      else if (error?.status === 429) this.transition("throttled", error);
      else if (error?.status >= 500) this.transition("server-error", error);
      else if (error instanceof TypeError || error?.name === "AbortError") this.transition("network-error", error);
      else this.transition("server-error", error);
      throw error;
    }
  }

  cancel() {
    ++this.generation;
    this.gateway.invalidateAuthentication?.();
    this.gateway.csrfToken = null;
    this.transition("disconnected");
  }

  async logout() {
    ++this.generation;
    try { await this.gateway.logout(); }
    finally { this.gateway.csrfToken = null; this.transition("disconnected"); }
  }
}
