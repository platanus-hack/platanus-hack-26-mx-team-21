import { WhatsAppClient } from "@kapso/whatsapp-cloud-api";
import { config } from "./config";
import { logger, redactPhone, redactUrl } from "./logger";
import type { InboundMedia } from "./types";

export interface DownloadedImage {
  bytes: ArrayBuffer;
  contentType: string;
  filename: string;
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
   * Download an inbound image. Prefers the Kapso-hosted media URL (auth headers applied
   * automatically by client.fetch), falling back to media.download() by media id.
   */
  async downloadImage(media: InboundMedia): Promise<DownloadedImage> {
    if (!media.url && !media.id) throw new Error("inbound message has no media url or id");

    // Prefer the Kapso-hosted URL; fall back to download-by-id if it fails.
    if (media.url) {
      try {
        logger.debug("downloading media via url", { host: redactUrl(media.url) });
        const res = await this.client.fetch(media.url);
        if (!res.ok) throw new Error(`media fetch failed: ${res.status}`);
        const bytes = await res.arrayBuffer();
        const contentType = media.contentType ?? res.headers.get("content-type") ?? "image/jpeg";
        return { bytes, contentType, filename: media.filename ?? defaultName(contentType) };
      } catch (err) {
        if (!media.id) throw err;
        logger.warn("media url download failed, falling back to media id", { err: String(err) });
      }
    }

    logger.debug("downloading media via id");
    const bytes = (await this.client.media.download({
      mediaId: media.id!,
      phoneNumberId: config.kapso.phoneNumberId,
    })) as ArrayBuffer;
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
