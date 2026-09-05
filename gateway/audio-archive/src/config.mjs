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

export function loadConfig(env = process.env) {
  const allowedOrigin = required(env, "ALLOWED_ORIGIN").replace(/\/$/, "");
  const parsedOrigin = new URL(allowedOrigin);
  if (parsedOrigin.protocol !== "https:" || parsedOrigin.origin !== allowedOrigin) throw new Error("ALLOWED_ORIGIN must be one HTTPS origin");
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
    githubAppPrivateKey: required(env, "GITHUB_APP_PRIVATE_KEY"),
    sharedPasswordVerifier: required(env, "SHARED_PASSWORD_VERIFIER"),
    sessionSigningSecret: required(env, "SESSION_SIGNING_SECRET")
  });
}
