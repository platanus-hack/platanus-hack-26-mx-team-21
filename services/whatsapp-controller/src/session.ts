import { config } from "./config";
import { logger } from "./logger";
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
  /** Number of failed submit attempts for this session (caps retry abuse). */
  submitAttempts?: number;
  updatedAt: number;
  expiresAt: number;
}

export interface SessionStore {
  get(phone: string): Session | undefined;
  set(session: Session): void;
  delete(phone: string): void;
}

/** How often the background sweeper reclaims expired entries. */
const SWEEP_INTERVAL_MS = 60_000;

/**
 * In-memory session store with TTL. Fine for a single-instance sandbox controller.
 * Swap for a Postgres/Redis-backed store (same interface) to survive restarts and
 * scale horizontally.
 *
 * Memory-bounded against `from`-spoofing floods:
 *  - Hard cap of `config.maxSessions`; on insert past the cap the least-recently-used
 *    entry (Map insertion order = LRU, since set() re-inserts) is evicted.
 *  - A periodic unref'd timer reclaims expired sessions for phones that never return,
 *    instead of relying only on lazy eviction in get().
 */
export class InMemorySessionStore implements SessionStore {
  private map = new Map<string, Session>();
  private sweeper: ReturnType<typeof setInterval>;

  constructor(private maxEntries = config.maxSessions) {
    this.sweeper = setInterval(() => this.sweep(), SWEEP_INTERVAL_MS);
    this.sweeper.unref();
  }

  get(phone: string): Session | undefined {
    const s = this.map.get(phone);
    if (!s) return undefined;
    if (s.expiresAt < Date.now()) {
      this.map.delete(phone);
      return undefined;
    }
    // Mark as most-recently-used (move to the back of the Map's iteration order).
    this.map.delete(phone);
    this.map.set(phone, s);
    return s;
  }

  set(session: Session): void {
    session.updatedAt = Date.now();
    session.expiresAt = Date.now() + config.sessionTtlMs;
    // Re-insert so this phone becomes most-recently-used (moves to the back).
    this.map.delete(session.phone);
    this.map.set(session.phone, session);
    this.evictOverflow();
  }

  delete(phone: string): void {
    this.map.delete(phone);
  }

  /** Drop least-recently-used entries until at or below the cap. */
  private evictOverflow(): void {
    while (this.map.size > this.maxEntries) {
      const oldest = this.map.keys().next().value;
      if (oldest === undefined) break;
      this.map.delete(oldest);
      logger.warn("session store at capacity, evicted LRU session", {
        size: this.map.size,
        max: this.maxEntries,
      });
    }
  }

  /** Reclaim expired sessions in bulk (cheaper amortized than per-get for cold phones). */
  private sweep(): void {
    const now = Date.now();
    for (const [phone, s] of this.map) {
      if (s.expiresAt < now) this.map.delete(phone);
    }
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

/**
 * TTL set for idempotency: drop webhook redeliveries of the same message id.
 *
 * Memory-bounded against `id`-spoofing floods:
 *  - Hard cap of `config.maxDedupe`; on insert past the cap the soonest-expiring entry
 *    (Map insertion order = first-seen order) is evicted. Worst case this can drop a
 *    still-valid id, weakening dedupe for that one id — acceptable vs. unbounded growth.
 *  - A periodic unref'd timer evicts expired ids in bulk. Previously every call swept the
 *    ENTIRE map (O(n) per message → O(n^2) under sustained flooding); seenBefore() is now
 *    O(1) and steady-state memory stays bounded.
 */
export class DedupeStore {
  private seen = new Map<string, number>();
  private sweeper: ReturnType<typeof setInterval>;

  constructor(
    private ttlMs = 10 * 60_000,
    private maxEntries = config.maxDedupe,
  ) {
    this.sweeper = setInterval(() => this.sweep(), SWEEP_INTERVAL_MS);
    this.sweeper.unref();
  }

  seenBefore(id: string): boolean {
    const t = this.seen.get(id);
    if (t !== undefined && t >= Date.now() - this.ttlMs) return true;
    // New (or expired-but-still-present) id: (re)record as first-seen now.
    this.seen.delete(id);
    this.seen.set(id, Date.now());
    this.evictOverflow();
    return false;
  }

  /** Drop oldest (soonest-expiring) entries until at or below the cap. */
  private evictOverflow(): void {
    while (this.seen.size > this.maxEntries) {
      const oldest = this.seen.keys().next().value;
      if (oldest === undefined) break;
      this.seen.delete(oldest);
    }
  }

  private sweep(): void {
    const cutoff = Date.now() - this.ttlMs;
    for (const [k, t] of this.seen) {
      if (t < cutoff) this.seen.delete(k);
    }
  }
}
