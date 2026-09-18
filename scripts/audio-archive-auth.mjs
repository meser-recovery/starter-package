export const ARCHIVE_AUTH_STATES = Object.freeze([
  "disconnected", "checking-password", "verifying-session", "storage-access-required",
  "opening-first-party-bootstrap", "awaiting-storage-grant", "connected", "denied", "unsupported", "error"
]);

const BRIDGE_MESSAGE_TYPE = "meser-storage-access";
const BRIDGE_MESSAGE_VERSION = 1;

export class ArchiveAuthController {
  constructor({ gateway, mount, onState = () => {}, timeoutMs = 45_000 }) {
    this.gateway = gateway;
    this.mount = mount;
    this.onState = onState;
    this.timeoutMs = timeoutMs;
    this.state = "disconnected";
    this.iframe = null;
    this.timeout = null;
    this.attempt = 0;
    this.handleMessage = this.handleMessage.bind(this);
    globalThis.addEventListener?.("message", this.handleMessage);
  }

  transition(state, detail = "") {
    if (!ARCHIVE_AUTH_STATES.includes(state)) throw new Error("Неизвестное состояние подключения архива.");
    this.state = state;
    this.onState({ state, detail });
  }

  async restore() {
    const attempt = ++this.attempt;
    this.transition("verifying-session");
    try {
      const proof = await this.gateway.sessionStatus();
      if (attempt !== this.attempt) return false;
      if (proof?.authenticated !== true || !this.gateway.csrfToken) throw new Error("Сеанс не подтверждён.");
      this.transition("connected");
      return true;
    } catch (error) {
      if (attempt !== this.attempt) return false;
      this.gateway.csrfToken = null;
      this.transition("disconnected", error);
      return false;
    }
  }

  async login(password) {
    const attempt = ++this.attempt;
    try {
      const proof = await this.gateway.login(password, { onState: (state) => {
        if (attempt === this.attempt) this.transition(state);
      } });
      if (attempt !== this.attempt) return false;
      if (proof?.authenticated !== true || !this.gateway.csrfToken) throw new Error("Сеанс не подтверждён.");
      this.transition("connected");
      return true;
    } catch (error) {
      if (attempt !== this.attempt) return false;
      this.gateway.csrfToken = null;
      if (error?.status === 401 && this.state === "checking-password") {
        error.code = "invalid_password";
        this.transition("denied", error);
      } else if ([401, 403].includes(error?.status) && this.state === "verifying-session") {
        error.code = "storage_access_required";
        this.transition("storage-access-required", error);
      } else this.transition("error", error);
      throw error;
    }
  }

  openBootstrap() {
    this.transition("opening-first-party-bootstrap");
    const link = document.createElement("a");
    link.href = `${this.gateway.baseUrl}/safari-bootstrap`;
    link.target = "_blank";
    link.rel = "noopener noreferrer";
    link.click();
    this.showBridge();
    return true;
  }

  showBridge() {
    this.removeBridge();
    if (!this.mount) throw new Error("Не найдено место для запроса доступа Safari.");
    const iframe = document.createElement("iframe");
    iframe.title = "Разрешение Safari на доступ к аудиоархиву";
    iframe.src = `${this.gateway.baseUrl}/storage-access-bridge`;
    iframe.className = "archive-storage-access-frame";
    this.iframe = iframe;
    this.mount.replaceChildren(iframe);
    this.mount.hidden = false;
    this.transition("awaiting-storage-grant");
    this.timeout = globalThis.setTimeout(() => {
      if (this.iframe !== iframe) return;
      const error = new Error("Safari не подтвердил доступ за отведённое время. Можно повторить безопасно.");
      error.code = "storage_access_timeout";
      this.transition("error", error);
    }, this.timeoutMs);
  }

  async handleMessage(event) {
    if (!this.iframe || event.origin !== new URL(this.gateway.baseUrl).origin || event.source !== this.iframe.contentWindow) return;
    const data = event.data;
    if (!data || data.type !== BRIDGE_MESSAGE_TYPE || data.version !== BRIDGE_MESSAGE_VERSION ||
        !["required", "granted", "denied", "unsupported", "error"].includes(data.status)) return;
    if (data.status === "required") { this.transition("awaiting-storage-grant"); return; }
    if (["denied", "unsupported", "error"].includes(data.status) && this.timeout) {
      globalThis.clearTimeout(this.timeout);
      this.timeout = null;
    }
    if (data.status === "denied") { this.transition("denied", new Error("Safari не разрешил доступ. Сначала подтвердите сеанс в отдельной вкладке, затем повторите.")); return; }
    if (data.status === "unsupported") { this.transition("unsupported", new Error("Этот браузер не поддерживает безопасный запрос доступа к архиву.")); return; }
    if (data.status === "error") { this.transition("error", new Error("Не удалось запросить доступ Safari. Повторите безопасно.")); return; }
    const attempt = ++this.attempt;
    this.transition("verifying-session");
    try {
      const proof = await this.gateway.sessionStatus();
      if (attempt !== this.attempt) return;
      if (proof?.authenticated !== true || !this.gateway.csrfToken) throw new Error("Сеанс не подтверждён после разрешения Safari.");
      this.removeBridge();
      this.transition("connected");
    } catch (error) {
      if (attempt !== this.attempt) return;
      this.gateway.csrfToken = null;
      this.transition("error", error);
    }
  }

  cancel() {
    ++this.attempt;
    this.gateway.csrfToken = null;
    this.removeBridge();
    this.transition("disconnected");
  }

  removeBridge() {
    if (this.timeout) globalThis.clearTimeout(this.timeout);
    this.timeout = null;
    this.iframe?.remove();
    this.iframe = null;
    if (this.mount) { this.mount.replaceChildren(); this.mount.hidden = true; }
  }

  destroy() {
    this.cancel();
    globalThis.removeEventListener?.("message", this.handleMessage);
  }
}
