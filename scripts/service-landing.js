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
    logout?.addEventListener("click", () => {
      sessionStorage.removeItem(SESSION_KEY);
      location.replace(LOGIN_URL);
    });
  });
})();
