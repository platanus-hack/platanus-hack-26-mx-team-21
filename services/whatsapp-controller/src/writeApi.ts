import { randomUUID } from "node:crypto";
import { config } from "./config";
import { logger } from "./logger";

export interface CitizenObservationInput {
  /** Reporter WhatsApp id / phone (digits). Provenance only. */
  reporterWaId: string;
  /** Observation type slug (e.g. "pothole"). */
  observationType: string;
  lat: number;
  lng: number;
  /** ISO-8601 capture time (the photo's message time). */
  observedAt: string;
  caption?: string;
  /** Idempotency key — stable per report (the inbound image's WhatsApp message id). */
  kapsoMessageId: string;
  image: { bytes: ArrayBuffer; contentType: string; filename: string };
}

export interface CitizenObservationResult {
  observationId: string;
  inBoundary?: boolean;
  thumbnailPath?: string;
  deduped?: boolean;
}

export interface WriteApi {
  createCitizenObservation(input: CitizenObservationInput): Promise<CitizenObservationResult>;
}

/** Logs the call and returns a synthetic id — use until the write API endpoint exists. */
export class DryRunWriteApi implements WriteApi {
  async createCitizenObservation(input: CitizenObservationInput): Promise<CitizenObservationResult> {
    const observationId = randomUUID();
    logger.info("DRY-RUN citizen observation", {
      observationId,
      type: input.observationType,
      lat: round(input.lat),
      lng: round(input.lng),
      bytes: input.image.bytes.byteLength,
      contentType: input.image.contentType,
      observedAt: input.observedAt,
      kapsoMessageId: input.kapsoMessageId,
    });
    return {
      observationId,
      inBoundary: true,
      thumbnailPath: `observations/${observationId}/report.jpg`,
      deduped: false,
    };
  }
}

/**
 * POSTs the report as multipart/form-data to the citycrawl-api. Contract:
 *   POST {WRITE_API_BASE_URL}/v1/observations/citizen   (header: X-Operator-Key)
 *   fields: reporter_wa_id, observation_type, lat, lng, observed_at, caption?,
 *           kapso_message_id, image (file)
 *   -> 200 { observationId, inBoundary, thumbnailPath }
 */
export class HttpWriteApi implements WriteApi {
  async createCitizenObservation(input: CitizenObservationInput): Promise<CitizenObservationResult> {
    const form = new FormData();
    form.set("reporter_wa_id", input.reporterWaId);
    form.set("observation_type", input.observationType);
    form.set("lat", String(input.lat));
    form.set("lng", String(input.lng));
    form.set("observed_at", input.observedAt);
    if (input.caption) form.set("caption", input.caption);
    form.set("kapso_message_id", input.kapsoMessageId);
    form.set(
      "image",
      new Blob([input.image.bytes], { type: input.image.contentType }),
      input.image.filename,
    );

    const url = `${config.writeApi.baseUrl.replace(/\/$/, "")}/v1/observations/citizen`;
    const headers: Record<string, string> = {};
    if (config.writeApi.token) headers["X-Operator-Key"] = config.writeApi.token;

    const res = await fetch(url, { method: "POST", body: form, headers });
    const text = await res.text();
    if (!res.ok) throw new Error(`write API ${res.status}: ${text.slice(0, 200)}`);

    const data = (text ? JSON.parse(text) : {}) as Record<string, unknown>;
    const observationId = (data.observation_id ?? data.observationId) as string | undefined;
    if (!observationId) throw new Error("write API response missing observation_id");
    return {
      observationId,
      inBoundary: (data.in_boundary ?? data.inBoundary) as boolean | undefined,
      thumbnailPath: (data.thumbnail_path ?? data.thumbnailPath) as string | undefined,
      deduped: data.deduped as boolean | undefined,
    };
  }
}

export function makeWriteApi(): WriteApi {
  return config.writeApi.mode === "http" ? new HttpWriteApi() : new DryRunWriteApi();
}

function round(n: number): number {
  return Math.round(n * 1e6) / 1e6;
}
