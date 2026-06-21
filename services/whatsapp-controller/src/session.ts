import { config } from "./config";
import type { InboundLocation } from "./types";

export type ConversationState = "IDLE" | "AWAITING_LOCATION" | "AWAITING_PHOTO";

export interface Session {
  phone: string;
  conversationId?: string;
  state: ConversationState;
  pendingImageMsgId?: string;
  pendingMediaId?: string;
  pendingMediaUrl?: string;
  pendingMediaContentType?: string;
  pendingMediaFilename?: string;
  pendingCaption?: string;
  pendingType?: string;
  pendingObservedAt?: string;
  pendingLocation?: InboundLocation;
  updatedAt: number;
  expiresAt: number;
}

export interface SessionStore {
  get(phone: string): Session | undefined;
  set(session: Session): void;
  delete(phone: string): void;
}

/**
 * In-memory session store with TTL. Fine for a single-instance sandbox controller.
 * Swap for a Postgres/Redis-backed store (same interface) to survive restarts and
 * scale horizontally.
 */
export class InMemorySessionStore implements SessionStore {
  private map = new Map<string, Session>();

  get(phone: string): Session | undefined {
    const s = this.map.get(phone);
    if (!s) return undefined;
    if (s.expiresAt < Date.now()) {
      this.map.delete(phone);
      return undefined;
    }
    return s;
  }

  set(session: Session): void {
    session.updatedAt = Date.now();
    session.expiresAt = Date.now() + config.sessionTtlMs;
    this.map.set(session.phone, session);
  }

  delete(phone: string): void {
    this.map.delete(phone);
  }
}

export function newSession(phone: string, conversationId?: string): Session {
  const now = Date.now();
  return {
    phone,
    conversationId,
    state: "IDLE",
    updatedAt: now,
    expiresAt: now + config.sessionTtlMs,
  };
}

/** TTL set for idempotency: drop webhook redeliveries of the same message id. */
export class DedupeStore {
  private seen = new Map<string, number>();

  constructor(private ttlMs = 10 * 60_000) {}

  seenBefore(id: string): boolean {
    this.sweep();
    if (this.seen.has(id)) return true;
    this.seen.set(id, Date.now());
    return false;
  }

  private sweep(): void {
    const cutoff = Date.now() - this.ttlMs;
    for (const [k, t] of this.seen) {
      if (t < cutoff) this.seen.delete(k);
    }
  }
}
