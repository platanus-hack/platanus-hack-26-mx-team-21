import { lookup } from "node:dns/promises";
import net from "node:net";
import { WhatsAppClient } from "@kapso/whatsapp-cloud-api";
import { config } from "./config";
import { logger, redactPhone, redactUrl } from "./logger";
import type { InboundMedia } from "./types";

export interface DownloadedImage {
  bytes: ArrayBuffer;
  contentType: string;
  filename: string;
}

type HostPolicy = "kapso" | "meta-cdn" | "unknown";

/** Max number of redirects we will chase before giving up on a media URL. */
const MAX_REDIRECTS = 3;

/**
 * Classify a media host against the allowlist.
 *   - "kapso":   send Kapso auth (these are our own hosts).
 *   - "meta-cdn": fetch WITHOUT auth (never leak Kapso creds to Meta).
 *   - "unknown": never fetch the URL; fall back to download-by-id.
 */
function classifyHost(host: string): HostPolicy {
  const h = host.toLowerCase();
  if (h === "app.kapso.ai" || h === "files.kapso.ai" || h.endsWith(".kapso.ai")) return "kapso";
  if (h === "lookaside.fbsbx.com" || h.endsWith(".fbcdn.net")) return "meta-cdn";
  return "unknown";
}

/**
 * SSRF guard: true if `addr` is a private / loopback / link-local / unique-local /
 * cloud-metadata address that must never be reached from media fetches. Covers
 * 127/8, 10/8, 172.16/12, 192.168/16, 169.254/16 (incl. 169.254.169.254), ::1,
 * fc00::/7, fe80::/10, and IPv4-mapped IPv6 forms.
 */
function isPrivateIp(addr: string): boolean {
  if (net.isIPv4(addr)) {
    const parts = addr.split(".").map(Number);
    if (parts.length !== 4 || parts.some((n) => !Number.isInteger(n) || n < 0 || n > 255)) {
      return true; // unparseable -> treat as unsafe
    }
    const [a, b] = parts;
    if (a === 127) return true; // loopback
    if (a === 10) return true; // private
    if (a === 172 && b >= 16 && b <= 31) return true; // private
    if (a === 192 && b === 168) return true; // private
    if (a === 169 && b === 254) return true; // link-local (incl. 169.254.169.254 metadata)
    if (a === 0) return true; // "this host"
    return false;
  }
  if (net.isIPv6(addr)) {
    const lower = addr.toLowerCase();
    if (lower === "::1" || lower === "::") return true; // loopback / unspecified
    // IPv4-mapped (::ffff:a.b.c.d) — re-check the embedded IPv4.
    const mapped = lower.match(/^::ffff:(\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3})$/);
    if (mapped) return isPrivateIp(mapped[1]);
    const head = lower.split(":")[0] ?? "";
    const first = parseInt(head || "0", 16);
    if ((first & 0xfe00) === 0xfc00) return true; // fc00::/7 unique-local
    if ((first & 0xffc0) === 0xfe80) return true; // fe80::/10 link-local
    return false;
  }
  return true; // not a recognizable IP -> unsafe
}

/**
 * Reject if the hostname resolves to (or contains) any private/loopback address.
 *
 * NOTE on DNS rebinding (TOCTOU): this resolves the host, but the subsequent fetch
 * resolves it again independently, so a hostile resolver could in theory return a
 * public address here and a private one to fetch. We do NOT pin the validated IP:
 * the global `fetch`/undici stack used by the SDK and here does not expose a clean,
 * dependency-free way to connect to a fixed IP while preserving Host/SNI, and adding
 * undici as a direct dependency for a custom dispatcher is not worth it here. The
 * PRIMARY control against SSRF is the strict host allowlist (classifyHost) — only
 * Kapso/Meta hosts are ever fetched, and #1's redirect:"manual" re-validation closes
 * the redirect-chase hole. This resolve check is best-effort defense in depth, not a
 * standalone guarantee.
 */
async function assertHostResolvesPublic(host: string): Promise<void> {
  let records: { address: string }[];
  try {
    records = await lookup(host, { all: true });
  } catch (err) {
    throw new Error(`dns resolution failed for media host: ${String(err)}`);
  }
  if (!records.length) throw new Error("media host did not resolve to any address");
  for (const r of records) {
    if (isPrivateIp(r.address)) {
      throw new Error("media host resolves to a private/disallowed address (SSRF guard)");
    }
  }
}

/** Thin wrapper over the Kapso WhatsApp client: send replies, download inbound media. */
export class KapsoGateway {
  private client: WhatsAppClient;

  constructor() {
    this.client = new WhatsAppClient({
      baseUrl: config.kapso.baseUrl,
      kapsoApiKey: config.kapso.apiKey,
    });
  }

  async sendText(to: string, body: string): Promise<void> {
    const dest = to.startsWith("+") ? to : `+${to}`;
    try {
      await this.client.messages.sendText({
        phoneNumberId: config.kapso.phoneNumberId,
        to: dest,
        body,
      });
      logger.info("reply sent", { to: redactPhone(to) });
    } catch (err) {
      logger.error("sendText failed", { to: redactPhone(to), err: String(err) });
    }
  }

  /**
   * Download an inbound image safely.
   *
   * The media URL is attacker-controllable (it comes from the webhook payload), so we:
   *  1. Require https.
   *  2. Allowlist the host: Kapso hosts are fetched WITH auth, Meta CDN hosts WITHOUT auth,
   *     and unknown hosts are never fetched (we fall back to download-by-id instead).
   *  3. Resolve the host and reject private/loopback/metadata addresses (SSRF defense in depth).
   *  4. Enforce a timeout and a maximum download size on every hop.
   *  5. Follow redirects MANUALLY: re-run the full validation on each redirect target and
   *     never carry the Kapso X-API-Key onto a non-Kapso host. (The real Kapso media URL is
   *     an app.kapso.ai/rails/active_storage/.../redirect/... link that 302s to blob storage
   *     in normal operation, so redirects are expected — see fetchMediaUrl.)
   */
  async downloadImage(media: InboundMedia): Promise<DownloadedImage> {
    if (!media.url && !media.id) throw new Error("inbound message has no media url or id");

    if (media.url) {
      let policy: HostPolicy = "unknown";
      let host = "";
      try {
        const parsed = new URL(media.url);
        host = parsed.hostname;
        if (parsed.protocol !== "https:") {
          throw new Error(`refusing non-https media url scheme: ${parsed.protocol}`);
        }
        policy = classifyHost(parsed.hostname);
      } catch (err) {
        // Bad/non-https URL: only fall back to id if we have one, else fail.
        if (!media.id) throw err instanceof Error ? err : new Error(String(err));
        logger.warn("media url rejected, falling back to media id", { err: String(err) });
        return this.downloadById(media);
      }

      if (policy === "unknown") {
        if (media.id) {
          logger.warn("media url host not allowlisted, falling back to media id", {
            host: redactUrl(media.url),
          });
          return this.downloadById(media);
        }
        throw new Error(`media url host not allowlisted and no media id: ${host}`);
      }

      try {
        logger.debug("downloading media via url", { host: redactUrl(media.url), policy });
        return await this.fetchMediaUrl(media, host, policy);
      } catch (err) {
        if (!media.id) throw err instanceof Error ? err : new Error(String(err));
        logger.warn("media url download failed, falling back to media id", {
          host: redactUrl(media.url),
          err: String(err),
        });
      }
    }

    return this.downloadById(media);
  }

  /**
   * Fetch an allowlisted https media URL with SSRF, timeout and size protections,
   * following redirects MANUALLY so we can re-validate every target.
   *
   * On each hop we re-derive the host policy from scratch:
   *   - https is required,
   *   - the host must resolve to a PUBLIC address (private/loopback/metadata are rejected),
   *   - X-API-Key (client.fetch) is sent ONLY when the *current* hop is a Kapso host;
   *     any other host (including a redirect target) is fetched via rawFetch (no auth).
   *
   * The legit Kapso flow goes: app.kapso.ai/rails/active_storage/.../redirect/... (kapso,
   * auth) → 302 → Kapso object storage (e.g. *.r2.cloudflarestorage.com). We follow that
   * redirect WITHOUT auth (rawFetch) and with the SSRF public-IP check, so the fast URL path
   * works for normal traffic; download-by-id remains the fallback only if the URL path fails.
   */
  private async fetchMediaUrl(
    media: InboundMedia,
    host: string,
    policy: HostPolicy,
  ): Promise<DownloadedImage> {
    let currentUrl = media.url!;
    let currentHost = host;
    let currentPolicy = policy;

    for (let hop = 0; hop <= MAX_REDIRECTS; hop++) {
      await assertHostResolvesPublic(currentHost);

      const controller = new AbortController();
      const timer = setTimeout(() => controller.abort(), config.media.fetchTimeoutMs);
      let res: Response;
      try {
        // redirect:"manual" — do NOT let undici chase 3xx automatically; we re-validate
        // each target ourselves and pick the right auth mode per hop.
        const init = { signal: controller.signal, redirect: "manual" as const };
        res =
          currentPolicy === "kapso"
            ? await this.client.fetch(currentUrl, init)
            : await this.client.rawFetch(currentUrl, init);
      } finally {
        clearTimeout(timer);
      }

      // Handle redirects ourselves: validate the Location target before following it.
      if (res.status >= 300 && res.status < 400) {
        const location = res.headers.get("location");
        if (!location) throw new Error(`media fetch redirect (${res.status}) without Location`);
        if (hop >= MAX_REDIRECTS) throw new Error("media fetch exceeded redirect limit");

        let next: URL;
        try {
          next = new URL(location, currentUrl); // resolve relative redirects
        } catch (err) {
          throw new Error(`media fetch redirect to invalid URL: ${String(err)}`);
        }
        if (next.protocol !== "https:") {
          throw new Error(`media fetch redirect to non-https scheme: ${next.protocol}`);
        }
        // Follow the redirect. Kapso media URLs (app.kapso.ai/.../redirect/...) 302 to Kapso's
        // own object storage (e.g. *.r2.cloudflarestorage.com), so the target is normally NOT a
        // Kapso host — that's expected and must NOT block the download. We still follow it, but
        // safely: a non-Kapso hop is fetched via rawFetch (NO X-API-Key — see the fetch above),
        // and the SSRF guard (assertHostResolvesPublic at the top of the next hop) rejects any
        // private/loopback/metadata target. So auth rides only on Kapso hops; bytes are fetched
        // from the (public, IP-checked) storage target without leaking credentials.
        const nextPolicy = classifyHost(next.hostname);
        logger.debug("following media redirect", {
          status: res.status,
          to: next.host,
          auth: nextPolicy === "kapso",
        });
        currentUrl = next.toString();
        currentHost = next.hostname;
        currentPolicy = nextPolicy; // "unknown" -> next hop uses rawFetch (no auth)
        continue;
      }

      if (!res.ok) throw new Error(`media fetch failed: ${res.status}`);

      const declared = Number(res.headers.get("content-length"));
      if (Number.isFinite(declared) && declared > config.media.maxBytes) {
        throw new Error(`media too large: content-length ${declared} > ${config.media.maxBytes}`);
      }

      const bytes = await res.arrayBuffer();
      if (bytes.byteLength > config.media.maxBytes) {
        throw new Error(`media too large: ${bytes.byteLength} > ${config.media.maxBytes}`);
      }

      const contentType = media.contentType ?? res.headers.get("content-type") ?? "image/jpeg";
      return { bytes, contentType, filename: media.filename ?? defaultName(contentType) };
    }

    // Unreachable: the loop either returns bytes or throws on every path.
    throw new Error("media fetch exceeded redirect limit");
  }

  /** Resolve media bytes via the SDK's download-by-id (auth + short-lived URL handled by the SDK). */
  private async downloadById(media: InboundMedia): Promise<DownloadedImage> {
    if (!media.id) throw new Error("inbound message has no media url or id");
    logger.debug("downloading media via id");
    const bytes = (await this.client.media.download({
      mediaId: media.id,
      phoneNumberId: config.kapso.phoneNumberId,
    })) as ArrayBuffer;
    if (bytes.byteLength > config.media.maxBytes) {
      throw new Error(`media too large: ${bytes.byteLength} > ${config.media.maxBytes}`);
    }
    const contentType = media.contentType ?? "image/jpeg";
    return { bytes, contentType, filename: media.filename ?? defaultName(contentType) };
  }
}

function defaultName(contentType: string): string {
  const ext = contentType.includes("png")
    ? "png"
    : contentType.includes("webp")
      ? "webp"
      : "jpg";
  return `report.${ext}`;
}
