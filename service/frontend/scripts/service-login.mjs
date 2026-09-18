import { ServiceSessionGateway, isUuid } from "./service-session-client.mjs";
import { ServiceSessionController } from "./service-session.mjs";

const gateway = new ServiceSessionGateway();
const form = document.getElementById("admin-access-form");
const password = document.getElementById("admin-password");
const toggle = document.getElementById("admin-password-toggle");
const status = document.getElementById("admin-error");
const submit = form.querySelector('button[type="submit"]');

function canonicalReturn() {
  const values = new URLSearchParams(location.search).getAll("return");
  if (values.length !== 1) return "/";
  let target;
  try { target = new URL(values[0], location.origin); } catch { return "/"; }
  if (target.origin !== location.origin || target.hash) return "/";
  const ordinary = new Set(["/", "/Calendar.html", "/Google-Drive.html",
    "/Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html"]);
  if (ordinary.has(target.pathname)) return target.search ? "/" : target.pathname;
  const keys = [...target.searchParams.keys()];
  if (new Set(keys).size !== keys.length) return target.pathname;
  if (target.pathname === "/Audio-Archive.html") {
    if (keys.some(key => key !== "session")) return target.pathname;
    const session = target.searchParams.get("session");
    return session && isUuid(session) ? `${target.pathname}?session=${encodeURIComponent(session)}` : target.pathname;
  }
  if (target.pathname === "/Audio-Editor.html") {
    const allowed = new Set(["session", "workflow", "projectRevision", "speakerOutput"]);
    if (keys.some(key => !allowed.has(key))) return target.pathname;
    const session = target.searchParams.get("session");
    const workflow = target.searchParams.get("workflow");
    const revision = target.searchParams.get("projectRevision");
    const output = target.searchParams.get("speakerOutput");
    if ((session && !isUuid(session)) || (workflow && !["announcement", "speaker"].includes(workflow)) ||
        (revision && (!/^\d+$/.test(revision) || Number(revision) < 1)) || (output && !isUuid(output))) return target.pathname;
    const clean = new URLSearchParams();
    if (session) clean.set("session", session);
    if (workflow) clean.set("workflow", workflow);
    if (revision) clean.set("projectRevision", revision);
    if (output) clean.set("speakerOutput", output);
    return `${target.pathname}${clean.size ? `?${clean}` : ""}`;
  }
  return "/";
}

const controller = new ServiceSessionController({
  gateway,
  onState: ({ state, detail }) => {
    const messages = {
      "checking-password": "Проверяем пароль…",
      "verifying-session": "Подтверждаем служебную сессию…",
      denied: "Неверный пароль.",
      throttled: "Слишком много попыток. Подождите и повторите вход.",
      "network-error": "Не удалось связаться с сервером. Проверьте подключение.",
      "server-error": detail?.status >= 500 ? "Служебный сервер временно недоступен." : "Не удалось подтвердить вход."
    };
    if (messages[state]) status.textContent = messages[state];
  }
});

toggle.addEventListener("click", () => {
  const visible = password.type === "password";
  password.type = visible ? "text" : "password";
  toggle.classList.toggle("is-visible", visible);
  toggle.setAttribute("aria-label", visible ? "Скрыть пароль" : "Показать пароль");
  toggle.setAttribute("aria-pressed", String(visible));
});

form.addEventListener("submit", async event => {
  event.preventDefault();
  if (submit.disabled) return;
  submit.disabled = true;
  status.textContent = "";
  try {
    if (await controller.login(password.value)) location.replace(canonicalReturn());
  } catch {
    password.focus();
    password.select();
  } finally {
    password.value = "";
    submit.disabled = false;
  }
});

if (await controller.restore()) location.replace(canonicalReturn());
