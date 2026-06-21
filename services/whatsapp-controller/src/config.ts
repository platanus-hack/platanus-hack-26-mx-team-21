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
  };
  writeApi: {
    mode: WriteApiMode;
    baseUrl: string;
    token: string;
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
  },
  writeApi: {
    mode: (process.env.WRITE_API_MODE as WriteApiMode) === "http" ? "http" : "dry-run",
    baseUrl: process.env.WRITE_API_BASE_URL ?? "",
    token: process.env.WRITE_API_TOKEN ?? "",
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
  return problems;
}
