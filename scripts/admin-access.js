(() => {
  const SALT = "2969";
  const SALTED_PASSWORD_VERIFIER = "598ebb5954daa98ece99310008316b259607777f0772006fb675ca92962cc216";
  const SESSION_KEY = "meser_service_access_v1";
  const LANDING_URL = "Admin-panel_5ab2b48b89f2fe30ce3272f2816f7d3f19b45752737d55f70f8c3a7f117dc527.html";

  function legacyBytes(value) {
    const bytes = new Uint8Array(value.length);
    for (let index = 0; index < value.length; index += 1) {
      bytes[index] = value.charCodeAt(index) & 0xff;
    }
    return bytes;
  }

  async function legacySha256(value) {
    const digest = await window.crypto.subtle.digest("SHA-256", legacyBytes(value));
    return Array.from(new Uint8Array(digest), byte => byte.toString(16).padStart(2, "0")).join("");
  }

  const form = document.getElementById("admin-access-form");
  const passwordInput = document.getElementById("admin-password");
  const error = document.getElementById("admin-error");
  const submit = form?.querySelector('button[type="submit"]');
  if (!form || !passwordInput || !error || !submit) return;

  form.addEventListener("submit", async event => {
    event.preventDefault();
    error.textContent = "";
    submit.disabled = true;
    try {
      const verifier = await legacySha256(passwordInput.value + SALT);
      if (verifier === SALTED_PASSWORD_VERIFIER) {
        sessionStorage.setItem(SESSION_KEY, "granted");
        passwordInput.value = "";
        location.replace(LANDING_URL);
        return;
      }
      error.textContent = "Неверный пароль.";
      passwordInput.focus();
      passwordInput.select();
    } catch {
      error.textContent = "Неверный пароль.";
      passwordInput.focus();
    } finally {
      submit.disabled = false;
    }
  });
})();
