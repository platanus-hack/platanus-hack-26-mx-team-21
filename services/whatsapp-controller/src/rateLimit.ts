/**
 * Lightweight in-memory per-key fixed-window rate limiter (no external deps).
 *
 * Each key (a client IP) gets a counter that resets every `windowMs`. The state map is
 * bounded two ways so the limiter cannot itself become a memory-exhaustion vector:
 *  - stale windows are swept opportunistically on each call, and
 *  - if the map exceeds `maxKeys`, the oldest windows are evicted.
 *
 * Intended to stop floods, not to perfectly meter legitimate (low-cardinality) traffic.
 */
export interface RateLimitDecision {
  allowed: boolean;
  /** Requests already counted in the current window (including this one when allowed). */
  count: number;
  limit: number;
}

interface Window {
  count: number;
  /** Epoch ms when this window resets. */
  resetAt: number;
}

export class FixedWindowRateLimiter {
  private windows = new Map<string, Window>();

  constructor(
    private readonly limit: number,
    private readonly windowMs = 60_000,
    private readonly maxKeys = 10_000,
  ) {}

  /** Record a hit for `key` and decide whether it is within the limit. */
  hit(key: string, now = Date.now()): RateLimitDecision {
    this.sweep(now);

    let w = this.windows.get(key);
    if (!w || w.resetAt <= now) {
      w = { count: 0, resetAt: now + this.windowMs };
      this.windows.set(key, w);
    }

    if (w.count >= this.limit) {
      return { allowed: false, count: w.count, limit: this.limit };
    }
    w.count += 1;
    this.enforceBound();
    return { allowed: true, count: w.count, limit: this.limit };
  }

  /** Drop windows that have already reset. */
  private sweep(now: number): void {
    for (const [k, w] of this.windows) {
      if (w.resetAt <= now) this.windows.delete(k);
    }
  }

  /** Hard cap on map size: evict oldest-resetting windows first. */
  private enforceBound(): void {
    if (this.windows.size <= this.maxKeys) return;
    const overflow = this.windows.size - this.maxKeys;
    const oldest = [...this.windows.entries()]
      .sort((a, b) => a[1].resetAt - b[1].resetAt)
      .slice(0, overflow);
    for (const [k] of oldest) this.windows.delete(k);
  }
}

/**
 * Best-effort client IP behind Fly's proxy. Express's `req.ip` is unreliable without
 * trust-proxy, so we read the proxy headers directly:
 *   Fly-Client-IP > first X-Forwarded-For entry > socket remote address.
 */
export function clientIp(req: {
  headers: Record<string, string | string[] | undefined>;
  socket?: { remoteAddress?: string };
}): string {
  const fly = headerValue(req.headers["fly-client-ip"]);
  if (fly) return fly;

  const xff = headerValue(req.headers["x-forwarded-for"]);
  if (xff) {
    const first = xff.split(",")[0]?.trim();
    if (first) return first;
  }

  return req.socket?.remoteAddress ?? "unknown";
}

function headerValue(v: string | string[] | undefined): string | undefined {
  const s = Array.isArray(v) ? v[0] : v;
  const trimmed = s?.trim();
  return trimmed ? trimmed : undefined;
}
