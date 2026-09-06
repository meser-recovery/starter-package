import { readFileSync } from "node:fs";
import { DEFAULT_PART_BYTES, MAX_PART_BYTES } from "./validation.mjs";

function required(env, name) {
  const value = env[name];
  if (typeof value !== "string" || !value.trim()) throw new Error(`${name} is required`);
  return value;
}

function positiveInteger(value, fallback, maximum, name) {
  const parsed = value === undefined ? fallback : Number(value);
  if (!Number.isSafeInteger(parsed) || parsed < 1 || parsed > maximum) throw new Error(`${name} is invalid`);
  return parsed;
}

function secretFromFile(env, variable, readTextFile) {
  const filename = required(env, variable);
  let value;
  try {
    value = readTextFile(filename, "utf8");
  } catch {
    throw new Error(`${variable} could not be read`);
  }
  if (Buffer.isBuffer(value)) value = value.toString("utf8");
  if (typeof value !== "string") throw new Error(`${variable} did not contain text`);
  value = value.replace(/\r?\n$/, "");
  if (!value.trim()) throw new Error(`${variable} is empty`);
  return value;
}

export function loadConfig(env = process.env, readTextFile = readFileSync) {
  const allowedOrigin = required(env, "ALLOWED_ORIGIN").replace(/\/$/, "");
  const parsedOrigin = new URL(allowedOrigin);
  if (parsedOrigin.protocol !== "https:" || parsedOrigin.origin !== allowedOrigin) throw new Error("ALLOWED_ORIGIN must be one HTTPS origin");
  if (allowedOrigin !== "https://meser-recovery.github.io") throw new Error("ALLOWED_ORIGIN must remain https://meser-recovery.github.io");
  const storageOwner = env.STORAGE_OWNER || "meser-recovery";
  const storageRepository = env.STORAGE_REPOSITORY || "audio-archive";
  if (storageOwner !== "meser-recovery" || storageRepository !== "audio-archive") throw new Error("Storage target must remain meser-recovery/audio-archive");
  return Object.freeze({
    port: positiveInteger(env.PORT, 8080, 65535, "PORT"),
    allowedOrigin,
    storageOwner,
    storageRepository,
    storageBranch: env.STORAGE_BRANCH || "main",
    acceptedPartBytes: positiveInteger(env.ACCEPTED_PART_BYTES, DEFAULT_PART_BYTES, MAX_PART_BYTES, "ACCEPTED_PART_BYTES"),
    sessionLifetimeSeconds: positiveInteger(env.SESSION_LIFETIME_SECONDS, 4 * 60 * 60, 24 * 60 * 60, "SESSION_LIFETIME_SECONDS"),
    githubAppId: required(env, "GITHUB_APP_ID"),
    githubAppInstallationId: required(env, "GITHUB_APP_INSTALLATION_ID"),
    githubAppPrivateKey: secretFromFile(env, "GITHUB_APP_PRIVATE_KEY_FILE", readTextFile),
    sharedPasswordVerifier: secretFromFile(env, "SHARED_PASSWORD_VERIFIER_FILE", readTextFile),
    sessionSigningSecret: secretFromFile(env, "SESSION_SIGNING_SECRET_FILE", readTextFile)
  });
}
