import crypto from "node:crypto";
import { normalizeWebhook } from "@kapso/whatsapp-cloud-api/server";
import type { UnifiedMessage } from "@kapso/whatsapp-cloud-api";
import { config } from "./config";
import { logger } from "./logger";
import type { InboundKind, NormalizedMessage } from "./types";

/** Which payload encoding produced the matching HMAC (for shadow-mode logging). */
export type SignatureVariant = "raw" | "reserialized" | null;

export interface SignatureResult {
  /** True if the provided signature matched ANY accepted candidate. */
  matched: boolean;
  /** Which candidate matched (null when no match). */
  variant: SignatureVariant;
  /** Whether a webhook secret is configured. */
  hadSecret: boolean;
  /** Whether the request carried a signature header. */
  hadSignature: boolean;
}

/**
 * Verify Kapso's `x-webhook-signature` (hex HMAC-SHA256 of the payload, keyed by the
 * webhook secret) against the raw body, timing-safe.
 *
 * Kapso's docs sign `JSON.stringify(payload)` (a re-serialized form), but a sender may
 * instead sign the raw received bytes. We tolerate BOTH:
 *   - candidate A ("raw"):          HMAC over the raw body buffer as received.
 *   - candidate B ("reserialized"): HMAC over `JSON.stringify(JSON.parse(rawBody))`.
 * Either `<hex>` or `sha256=<hex>` header forms are accepted.
 *
 * Returns a rich result so callers can run a shadow (log-only) phase before enforcing.
 */
export function checkWebhookSignature(rawBody: Buffer, header: string | undefined): SignatureResult {
  const { secret } = config.webhook;
  const provided = header?.trim();
  const hadSecret = Boolean(secret);
  const hadSignature = Boolean(provided);
  if (!secret || !provided) {
    return { matched: false, variant: null, hadSecret, hadSignature };
  }

  const rawHex = hmacHex(secret, rawBody);
  if (matchesHeader(rawHex, provided)) {
    return { matched: true, variant: "raw", hadSecret, hadSignature };
  }

  // Re-serialized candidate. Parsing can fail on non-JSON bodies; that's fine — no match.
  try {
    const reserialized = JSON.stringify(JSON.parse(rawBody.toString("utf8")));
    const reHex = hmacHex(secret, Buffer.from(reserialized, "utf8"));
    if (matchesHeader(reHex, provided)) {
      return { matched: true, variant: "reserialized", hadSecret, hadSignature };
    }
  } catch {
    // not JSON -> no re-serialized candidate
  }

  return { matched: false, variant: null, hadSecret, hadSignature };
}

function hmacHex(secret: string, data: Buffer): string {
  return crypto.createHmac("sha256", secret).update(data).digest("hex");
}

/** Accept either `<hex>` or `sha256=<hex>` header forms, timing-safe. */
function matchesHeader(hex: string, provided: string): boolean {
  return safeEqual(hex, provided) || safeEqual(`sha256=${hex}`, provided);
}

function safeEqual(a: string, b: string): boolean {
  const ab = Buffer.from(a);
  const bb = Buffer.from(b);
  if (ab.length !== bb.length) return false;
  return crypto.timingSafeEqual(ab, bb);
}

/**
 * Parse a webhook delivery into normalized inbound messages. Handles:
 *  1. The Kapso platform delivery (payload v2): a single `{ message, conversation }`
 *     object, or `{ data: [ { message } ] }` / `{ messages: [...] }` batches.
 *  2. A raw Meta Graph payload (unwrapped via the SDK's normalizeWebhook).
 */
export function parseInbound(payload: unknown): NormalizedMessage[] {
  const collected = collectKapso(payload);
  if (collected) {
    return collected.msgs
      .map((m) => mapKapso(m, collected.envelope))
      .filter((m): m is NormalizedMessage => m !== null);
  }

  try {
    const norm = normalizeWebhook(payload);
    return norm.messages
      .filter((m) => (m.kapso?.direction ?? "inbound") === "inbound")
      .map((m) => mapMeta(m, norm.phoneNumberId))
      .filter((m): m is NormalizedMessage => m !== null);
  } catch (err) {
    logger.warn("normalizeWebhook failed", { err: String(err) });
    return [];
  }
}

// eslint-disable-next-line @typescript-eslint/no-explicit-any
function collectKapso(payload: unknown): { msgs: any[]; envelope: any } | null {
  if (!payload || typeof payload !== "object") return null;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const p = payload as any;
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const msgs: any[] = [];
  if (p.message && typeof p.message === "object") msgs.push(p.message);
  if (Array.isArray(p.messages)) msgs.push(...p.messages);
  if (Array.isArray(p.data)) {
    for (const ev of p.data) {
      if (ev && typeof ev === "object" && ev.message) msgs.push(ev.message);
      else if (ev) msgs.push(ev);
    }
  }
  return msgs.length ? { msgs, envelope: p } : null;
}

/**
 * Map one Kapso message (payload v2: Meta-style fields + a `kapso` extension block,
 * with `message_type`/`media_data` accepted as older-shape fallbacks).
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
function mapKapso(m: any, envelope: any): NormalizedMessage | null {
  if (!m || typeof m !== "object") return null;
  const k = m.kapso ?? {};
  const direction = k.direction ?? m.direction ?? "inbound";
  if (direction !== "inbound") return null;

  const id = m.id ?? m.whatsapp_message_id;
  if (!id) return null;

  const conv = envelope?.conversation ?? {};
  const base = {
    id: String(id),
    from: digits(m.from ?? m.phone_number ?? k.phone_number ?? conv.phone_number ?? ""),
    conversationId: conv.id ?? k.whatsapp_conversation_id ?? m.conversation_id,
    timestamp: toIso(m.timestamp ?? m.created_at),
    phoneNumberId: conv.phone_number_id ?? m.phone_number_id ?? k.phone_number_id,
  };

  const type = String(m.type ?? m.message_type ?? "").toLowerCase();
  const td = m.message_type_data ?? {};

  if (type === "image" || (m.image && typeof m.image === "object")) {
    const img = m.image ?? {};
    const md = k.media_data ?? m.media_data ?? {};
    return {
      ...base,
      kind: "image",
      text: img.caption ?? td.caption ?? strOrUndef(k.content),
      media: {
        id: img.id ?? m.media_id,
        url: md.url ?? img.link ?? img.url ?? m.media_url,
        contentType: md.content_type ?? md.contentType ?? img.mime_type,
        filename: md.filename,
        byteSize: md.byte_size ?? md.byteSize,
      },
    };
  }

  if (type === "location" || (m.location && typeof m.location === "object")) {
    const loc = m.location ?? td ?? {};
    const lat = num(loc.latitude ?? loc.lat);
    const lng = num(loc.longitude ?? loc.lng);
    if (lat === undefined || lng === undefined) return null;
    return { ...base, kind: "location", location: { lat, lng, name: loc.name, address: loc.address } };
  }

  if (type === "text") {
    return { ...base, kind: "text", text: m.text?.body ?? strOrUndef(k.content) ?? td.body };
  }

  return { ...base, kind: "other", text: strOrUndef(k.content) };
}

function mapMeta(m: UnifiedMessage, phoneNumberId?: string): NormalizedMessage | null {
  const type = String(m.type ?? "").toLowerCase();
  const base = {
    id: m.id,
    from: digits((m.from ?? m.kapso?.phoneNumber ?? "") as string),
    conversationId: m.kapso?.whatsappConversationId as string | undefined,
    timestamp: toIso(m.timestamp),
    phoneNumberId,
  };

  if (type === "image") {
    return {
      ...base,
      kind: "image",
      text: m.image?.caption,
      media: {
        id: m.image?.id,
        url: m.kapso?.mediaUrl ?? m.kapso?.mediaData?.url ?? m.image?.link,
        contentType: m.kapso?.mediaData?.contentType,
        filename: m.kapso?.mediaData?.filename,
        byteSize: m.kapso?.mediaData?.byteSize,
      },
    };
  }

  if (type === "location") {
    const lat = num(m.location?.latitude);
    const lng = num(m.location?.longitude);
    if (lat === undefined || lng === undefined) return null;
    return { ...base, kind: "location", location: { lat, lng, name: m.location?.name, address: m.location?.address } };
  }

  const kind: InboundKind = type === "text" ? "text" : "other";
  return { ...base, kind, text: m.text?.body };
}

function digits(s: unknown): string {
  return String(s ?? "").replace(/\D/g, "");
}

function strOrUndef(v: unknown): string | undefined {
  return typeof v === "string" ? v : undefined;
}

function num(x: unknown): number | undefined {
  if (x === null || x === undefined || x === "") return undefined;
  const n = Number(x);
  return Number.isFinite(n) ? n : undefined;
}

function toIso(v: unknown): string {
  if (v === null || v === undefined) return new Date().toISOString();
  if (typeof v === "number") return new Date(v < 1e12 ? v * 1000 : v).toISOString();
  const s = String(v);
  if (/^\d+$/.test(s)) {
    const n = Number(s);
    return new Date(n < 1e12 ? n * 1000 : n).toISOString();
  }
  const d = new Date(s);
  return Number.isNaN(d.getTime()) ? new Date().toISOString() : d.toISOString();
}
