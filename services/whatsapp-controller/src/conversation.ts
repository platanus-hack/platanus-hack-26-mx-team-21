import { config } from "./config";
import { logger, redactPhone } from "./logger";
import * as copy from "./messages";
import { KapsoGateway } from "./kapso";
import {
  DedupeStore,
  InMemorySessionStore,
  newSession,
  type Session,
  type SessionStore,
} from "./session";
import { makeWriteApi, type WriteApi } from "./writeApi";
import type { NormalizedMessage } from "./types";

/**
 * The two-message intake state machine.
 *
 *   IDLE ──image──▶ AWAITING_LOCATION ──location──▶ SUBMIT
 *   IDLE ──location▶ AWAITING_PHOTO   ──image─────▶ SUBMIT
 *
 * WhatsApp strips EXIF from in-chat photos, so a photo is unplaceable on its own:
 * we require a shared location pin and join the two messages per sender.
 */
export class ConversationEngine {
  constructor(
    private kapso: KapsoGateway,
    private writeApi: WriteApi = makeWriteApi(),
    private sessions: SessionStore = new InMemorySessionStore(),
    private dedupe: DedupeStore = new DedupeStore(),
  ) {}

  async handle(msg: NormalizedMessage): Promise<void> {
    if (!msg.from) {
      logger.warn("message without sender, ignoring", { id: msg.id });
      return;
    }
    if (this.dedupe.seenBefore(msg.id)) {
      logger.info("duplicate message ignored", { id: msg.id });
      return;
    }

    const phone = msg.from;
    const session = this.sessions.get(phone) ?? newSession(phone, msg.conversationId);
    logger.info("inbound", { from: redactPhone(phone), kind: msg.kind, state: session.state });

    switch (msg.kind) {
      case "image":
        await this.onImage(session, msg);
        break;
      case "location":
        await this.onLocation(session, msg);
        break;
      case "text":
        await this.onText(session);
        break;
      default:
        await this.kapso.sendText(phone, copy.unsupported());
        break;
    }
  }

  private async onImage(session: Session, msg: NormalizedMessage): Promise<void> {
    session.pendingImageMsgId = msg.id;
    session.pendingMediaId = msg.media?.id;
    session.pendingMediaUrl = msg.media?.url;
    session.pendingMediaContentType = msg.media?.contentType;
    session.pendingMediaFilename = msg.media?.filename;
    session.pendingCaption = msg.text;
    session.pendingObservedAt = msg.timestamp;
    session.pendingType = session.pendingType ?? config.defaultObservationType;

    if (session.pendingLocation) {
      await this.submit(session);
      return;
    }
    session.state = "AWAITING_LOCATION";
    this.sessions.set(session);
    await this.kapso.sendText(session.phone, copy.photoReceivedAskLocation());
  }

  private async onLocation(session: Session, msg: NormalizedMessage): Promise<void> {
    session.pendingLocation = msg.location;
    if (this.hasImage(session)) {
      await this.submit(session);
      return;
    }
    session.state = "AWAITING_PHOTO";
    this.sessions.set(session);
    await this.kapso.sendText(session.phone, copy.locationReceivedAskPhoto());
  }

  private async onText(session: Session): Promise<void> {
    this.sessions.set(session); // touch (extend TTL)
    if (session.state === "AWAITING_LOCATION") {
      await this.kapso.sendText(session.phone, copy.remindLocation());
    } else if (session.state === "AWAITING_PHOTO") {
      await this.kapso.sendText(session.phone, copy.remindPhoto());
    } else {
      await this.kapso.sendText(session.phone, copy.help());
    }
  }

  private hasImage(s: Session): boolean {
    return Boolean(s.pendingMediaUrl || s.pendingMediaId);
  }

  private async submit(session: Session): Promise<void> {
    const loc = session.pendingLocation;
    if (!loc) return;

    let image;
    try {
      image = await this.kapso.downloadImage({
        id: session.pendingMediaId,
        url: session.pendingMediaUrl,
        contentType: session.pendingMediaContentType,
        filename: session.pendingMediaFilename,
      });
    } catch (err) {
      logger.error("media download failed", { err: String(err) });
      session.state = "AWAITING_PHOTO";
      session.pendingMediaId = undefined;
      session.pendingMediaUrl = undefined;
      this.sessions.set(session);
      await this.kapso.sendText(session.phone, copy.downloadError());
      return;
    }

    const type = session.pendingType ?? config.defaultObservationType;
    try {
      const result = await this.writeApi.createCitizenObservation({
        reporterWaId: session.phone,
        observationType: type,
        lat: loc.lat,
        lng: loc.lng,
        observedAt: session.pendingObservedAt ?? new Date().toISOString(),
        caption: session.pendingCaption,
        kapsoMessageId: session.pendingImageMsgId ?? `${session.phone}:${session.pendingObservedAt ?? ""}`,
        image,
      });

      logger.info("citizen observation created", {
        observationId: result.observationId,
        inBoundary: result.inBoundary,
        deduped: result.deduped,
      });

      this.sessions.delete(session.phone);
      const label = copy.typeLabel(type);
      const reply =
        result.inBoundary === false ? copy.confirmationOutOfArea(label) : copy.confirmation(label);
      await this.kapso.sendText(session.phone, reply);
    } catch (err) {
      logger.error("submit failed", { err: String(err) });
      // Keep the session so the user can retry by re-sharing the location.
      session.state = "AWAITING_LOCATION";
      this.sessions.set(session);
      await this.kapso.sendText(session.phone, copy.submitError());
    }
  }
}
