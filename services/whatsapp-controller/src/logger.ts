type Level = "debug" | "info" | "warn" | "error";

/** Mask a phone number, keeping only the last 4 digits (privacy in logs). */
export function redactPhone(p?: string): string {
  if (!p) return "unknown";
  const digits = p.replace(/\D/g, "");
  if (digits.length <= 4) return "***";
  return `***${digits.slice(-4)}`;
}

/** Reduce a URL to its host only (don't log signed/short-lived media URLs). */
export function redactUrl(u?: string): string {
  if (!u) return "";
  try {
    return new URL(u).host;
  } catch {
    return "invalid-url";
  }
}

function emit(level: Level, msg: string, meta?: Record<string, unknown>): void {
  const line = JSON.stringify({ t: new Date().toISOString(), level, msg, ...(meta ?? {}) });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

export const logger = {
  debug: (m: string, meta?: Record<string, unknown>) => emit("debug", m, meta),
  info: (m: string, meta?: Record<string, unknown>) => emit("info", m, meta),
  warn: (m: string, meta?: Record<string, unknown>) => emit("warn", m, meta),
  error: (m: string, meta?: Record<string, unknown>) => emit("error", m, meta),
};
