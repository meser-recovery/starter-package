export function nodeResponseHeaders(headers) {
  const result = Object.fromEntries([...headers.entries()].filter(([name]) => name.toLowerCase() !== "set-cookie"));
  const cookies = typeof headers.getSetCookie === "function" ? headers.getSetCookie() : [];
  if (cookies.length) result["Set-Cookie"] = cookies;
  else if (headers.has("set-cookie")) result["Set-Cookie"] = headers.get("set-cookie");
  return result;
}
