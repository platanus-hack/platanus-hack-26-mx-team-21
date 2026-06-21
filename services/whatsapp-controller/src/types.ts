export type InboundKind = "text" | "image" | "location" | "other";

export interface InboundMedia {
  id?: string;
  url?: string;
  contentType?: string;
  filename?: string;
  byteSize?: number;
}

export interface InboundLocation {
  lat: number;
  lng: number;
  name?: string;
  address?: string;
}

/** A WhatsApp inbound message, normalized across the Kapso platform and Meta Graph payload shapes. */
export interface NormalizedMessage {
  /** WhatsApp message id — the idempotency key across webhook retries. */
  id: string;
  /** Sender wa id / phone (digits only, no '+'). */
  from: string;
  conversationId?: string;
  kind: InboundKind;
  /** Text body, or the caption that accompanied an image. */
  text?: string;
  /** ISO-8601 capture time. */
  timestamp: string;
  media?: InboundMedia;
  location?: InboundLocation;
  phoneNumberId?: string;
}
