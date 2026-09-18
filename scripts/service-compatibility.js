(() => {
  const origin = "https://meserproject.duckdns.org";
  const path = document.body.dataset.servicePath || "/";
  const params = new URLSearchParams(location.search);
  const keys = [...params.keys()];
  let suffix = "";

  const unique = new Set(keys).size === keys.length;
  const uuid = value => /^[0-9a-f]{8}-[0-9a-f]{4}-[1-8][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(value || "");
  if (!location.hash && unique && path === "/Audio-Archive.html" && keys.every(key => key === "session")) {
    const session = params.get("session");
    if (session && uuid(session)) suffix = `?session=${encodeURIComponent(session)}`;
  }
  if (!location.hash && unique && path === "/Audio-Editor.html" && keys.every(key => ["session", "workflow", "projectRevision", "speakerOutput"].includes(key))) {
    const session = params.get("session");
    const workflow = params.get("workflow");
    const revision = params.get("projectRevision");
    const output = params.get("speakerOutput");
    if ((!session || uuid(session)) && (!workflow || ["announcement", "speaker"].includes(workflow)) &&
        (!revision || (/^\d+$/.test(revision) && Number(revision) >= 1)) && (!output || uuid(output))) {
      const clean = new URLSearchParams();
      if (session) clean.set("session", session);
      if (workflow) clean.set("workflow", workflow);
      if (revision) clean.set("projectRevision", revision);
      if (output) clean.set("speakerOutput", output);
      if (clean.size) suffix = `?${clean}`;
    }
  }

  const target = `${origin}${path}${suffix}`;
  const link = document.getElementById("service-forward-link");
  if (link) link.href = target;
  location.replace(target);
})();
