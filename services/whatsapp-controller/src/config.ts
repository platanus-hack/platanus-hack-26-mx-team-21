import "dotenv/config";

function bool(v: string | undefined, def: boolean): boolean {
  if (v === undefined || v === "") return def;
  return ["1", "true", "yes", "on"].includes(v.toLowerCase());
}

function int(v: string | undefined, def: number): number {
  const n = v ? Number(v) : NaN;
  return Number.isFinite(n) ? n : def;
}

export type WriteApiMode = "http" | "dry-run";

export interface Config {
  port: number;
  kapso: {
    apiKey: string;
    baseUrl: string;
    phoneNumberId: string;
  };
  webhook: {
    verifyToken: string;
    secret: string;
    signatureHeader: string;
    signatureRequired: boolean;
    rateLimitPerMin: number;
  };
  writeApi: {
    mode: WriteApiMode;
    baseUrl: string;
    token: string;
  };
  media: {
    maxBytes: number;
    fetchTimeoutMs: number;
  };
  defaultObservationType: string;
  sessionTtlMs: number;
}

export const config: Config = {
  port: int(process.env.PORT, 8080),
  kapso: {
    apiKey: process.env.KAPSO_API_KEY ?? "",
    baseUrl: process.env.KAPSO_BASE_URL ?? "https://api.kapso.ai/meta/whatsapp",
    phoneNumberId: process.env.KAPSO_PHONE_NUMBER_ID ?? "",
  },
  webhook: {
    verifyToken: process.env.KAPSO_VERIFY_TOKEN ?? "",
    secret: process.env.KAPSO_WEBHOOK_SECRET ?? "",
    signatureHeader: (process.env.KAPSO_SIGNATURE_HEADER ?? "x-webhook-signature").toLowerCase(),
    signatureRequired: bool(process.env.KAPSO_SIGNATURE_REQUIRED, false),
    rateLimitPerMin: int(process.env.WEBHOOK_RATE_LIMIT_PER_MIN, 120),
  },
  writeApi: {
    mode: (process.env.WRITE_API_MODE as WriteApiMode) === "http" ? "http" : "dry-run",
    baseUrl: process.env.WRITE_API_BASE_URL ?? "",
    token: process.env.WRITE_API_TOKEN ?? "",
  },
  media: {
    maxBytes: int(process.env.MAX_MEDIA_BYTES, 16 * 1024 * 1024),
    fetchTimeoutMs: int(process.env.MEDIA_FETCH_TIMEOUT_MS, 15_000),
  },
  defaultObservationType: process.env.DEFAULT_OBSERVATION_TYPE ?? "pothole",
  sessionTtlMs: int(process.env.SESSION_TTL_MINUTES, 15) * 60_000,
};

/** Returns a list of human-readable config problems (empty when healthy). */
export function validateConfig(): string[] {
  const problems: string[] = [];
  if (!config.kapso.phoneNumberId) problems.push("KAPSO_PHONE_NUMBER_ID is required");
  if (!config.kapso.apiKey) problems.push("KAPSO_API_KEY is required (to send replies / download media)");
  if (config.writeApi.mode === "http" && !config.writeApi.baseUrl) {
    problems.push("WRITE_API_BASE_URL is required when WRITE_API_MODE=http");
  }
  if (config.webhook.signatureRequired && !config.webhook.secret) {
    problems.push("KAPSO_WEBHOOK_SECRET is required when KAPSO_SIGNATURE_REQUIRED=true");
  }
  if (config.webhook.rateLimitPerMin <= 0) {
    problems.push("WEBHOOK_RATE_LIMIT_PER_MIN must be a positive integer");
  }
  if (config.media.maxBytes <= 0) problems.push("MAX_MEDIA_BYTES must be a positive integer");
  if (config.media.fetchTimeoutMs <= 0) problems.push("MEDIA_FETCH_TIMEOUT_MS must be a positive integer");
  return problems;
}
