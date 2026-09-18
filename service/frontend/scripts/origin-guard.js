(() => {
  const serviceOrigin = "https://meserproject.duckdns.org";
  if (location.origin === serviceOrigin || ["127.0.0.1", "localhost", "::1"].includes(location.hostname)) return;
  location.replace(serviceOrigin + "/");
})();
