import test from "node:test";
import assert from "node:assert/strict";
import { ServiceSessionController } from "../../scripts/service-session.mjs";

test("service session restore retains CSRF only after a current replay", async () => {
  const gateway = {
    csrfToken: null,
    async sessionStatus(options) {
      assert.deepEqual(options, { captureCsrf: false });
      return { authenticated: true, csrfToken: "replayed-token" };
    }
  };
  const states = [];
  const controller = new ServiceSessionController({ gateway, onState: ({ state }) => states.push(state) });
  assert.equal(await controller.restore(), true);
  assert.equal(gateway.csrfToken, "replayed-token");
  assert.deepEqual(states, ["verifying-session", "connected"]);
});

test("cancel fences a late session replay and clears live auth state", async () => {
  let release;
  const replay = new Promise((resolve) => { release = resolve; });
  const gateway = {
    csrfToken: "older-token",
    invalidations: 0,
    sessionStatus() { return replay; },
    invalidateAuthentication() { this.invalidations += 1; this.csrfToken = null; }
  };
  const controller = new ServiceSessionController({ gateway });
  const pending = controller.restore();
  controller.cancel();
  release({ authenticated: true, csrfToken: "late-token" });
  assert.equal(await pending, false);
  assert.equal(controller.state, "disconnected");
  assert.equal(gateway.csrfToken, null);
  assert.equal(gateway.invalidations, 1);
});

test("login reports password, throttle, network and server failures distinctly", async () => {
  const cases = [
    [Object.assign(new Error("wrong"), { status: 401, code: "invalid_password" }), "denied"],
    [Object.assign(new Error("slow"), { status: 429 }), "throttled"],
    [new TypeError("offline"), "network-error"],
    [Object.assign(new Error("failed"), { status: 503 }), "server-error"]
  ];
  for (const [failure, expected] of cases) {
    const gateway = { csrfToken: null, async login() { throw failure; } };
    const controller = new ServiceSessionController({ gateway });
    await assert.rejects(() => controller.login("password"), failure);
    assert.equal(controller.state, expected);
    assert.equal(gateway.csrfToken, null);
  }
});
