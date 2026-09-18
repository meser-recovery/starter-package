import { ServiceSessionGateway } from "./service-session-client.mjs";
import { ServiceSessionController } from "./service-session.mjs";
import { prepareSpeakerLogout } from "./speaker-editor.mjs";

const gateway = new ServiceSessionGateway();
const controller = new ServiceSessionController({ gateway });
const logout = document.getElementById("service-logout");

logout?.addEventListener("click", async () => {
  if (logout.disabled || !await prepareSpeakerLogout()) return;
  logout.disabled = true;
  try {
    if (!await controller.restore()) return;
    await controller.logout();
  } finally {
    location.replace("/login");
  }
});
