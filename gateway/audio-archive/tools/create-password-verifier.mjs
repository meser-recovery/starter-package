import { createPasswordVerifier } from "../src/auth.mjs";

const chunks = [];
for await (const chunk of process.stdin) chunks.push(chunk);
const password = Buffer.concat(chunks).toString("utf8").replace(/[\r\n]+$/, "");
if (!password) {
  console.error("Read the shared password from standard input; no password was received.");
  process.exitCode = 1;
} else {
  console.log(await createPasswordVerifier(password));
}
