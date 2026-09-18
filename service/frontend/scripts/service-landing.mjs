import { ServiceSessionGateway } from "./service-session-client.mjs";
import { ServiceSessionController } from "./service-session.mjs";

const gateway = new ServiceSessionGateway();
const controller = new ServiceSessionController({ gateway });
const logout = document.getElementById("service-logout");

if (!await controller.restore()) location.replace("/login");

logout?.addEventListener("click", async () => {
  logout.disabled = true;
  try { await controller.logout(); }
  finally { location.replace("/login"); }
});
