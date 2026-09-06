(() => {
  const SESSION_KEY = "meser_service_access_v1";
  const LOGIN_URL = "Admin-panel.html";

  if (sessionStorage.getItem(SESSION_KEY) !== "granted") {
    document.documentElement.hidden = true;
    location.replace(LOGIN_URL);
    return;
  }

  document.addEventListener("DOMContentLoaded", () => {
    const logout = document.getElementById("service-logout");
    logout?.addEventListener("click", async () => {
      logout.disabled = true;
      const baseUrl = document.querySelector('meta[name="audio-archive-gateway"]')?.content.replace(/\/$/, "");
      if (baseUrl) {
        try {
          const status = await fetch(`${baseUrl}/v1/session`, { credentials: "include" });
          if (status.ok && (status.headers.get("Content-Type") || "").toLowerCase().startsWith("application/json")) {
            const { csrfToken } = await status.json();
            await fetch(`${baseUrl}/v1/session/logout`, {
              method: "POST", credentials: "include", headers: { "X-CSRF-Token": csrfToken }
            });
          }
        } catch {
          // Local logout remains available when the archive gateway is unreachable.
        }
      }
      sessionStorage.removeItem(SESSION_KEY);
      location.replace(LOGIN_URL);
    });
  });
})();
