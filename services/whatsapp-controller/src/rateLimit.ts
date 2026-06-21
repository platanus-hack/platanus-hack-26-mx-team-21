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
 * Rate-limit key for the requester.
 *
 * We do NOT trust attacker-settable forwarding headers for keying: a client can set
 * `X-Forwarded-For` (and even `Fly-Client-IP`) to any value to get a fresh bucket per
 * request and defeat the limiter. We therefore key on the SOCKET peer address.
 *
 * On Fly, all inbound traffic arrives through Fly's edge proxy, so the socket peer is the
 * proxy and `Fly-Client-IP` carries the real client IP. We only trust `Fly-Client-IP`
 * when the peer is a private/loopback address (i.e. a same-host/intra-Fly hop, which is
 * where the proxy sits) — never when the peer is a public address, since a public peer is
 * a direct connection whose headers are fully attacker-controlled.
 *
 * `X-Forwarded-For` is never trusted for keying.
 */
export function clientIp(req: {
  ip?: string;
  headers: Record<string, string | string[] | undefined>;
  socket?: { remoteAddress?: string };
}): string {
  const peer = req.socket?.remoteAddress;

  // Trust Fly-Client-IP only when the connection came through a trusted (private) hop.
  if (peer && isPrivatePeer(peer)) {
    const fly = headerValue(req.headers["fly-client-ip"]);
    if (fly) return fly;
  }

  // Express's req.ip (with trust proxy enabled) or the raw socket peer otherwise.
  return peer ?? req.ip ?? "unknown";
}

/** Cheap private/loopback check for the socket peer (proxy hops are private). */
function isPrivatePeer(addr: string): boolean {
  const a = addr.toLowerCase().replace(/^::ffff:/, "");
  if (a === "::1" || a === "127.0.0.1" || a.startsWith("127.")) return true;
  if (a.startsWith("10.")) return true;
  if (a.startsWith("192.168.")) return true;
  if (a.startsWith("169.254.")) return true; // link-local
  const m = a.match(/^172\.(\d+)\./);
  if (m) {
    const second = Number(m[1]);
    if (second >= 16 && second <= 31) return true;
  }
  if (a.startsWith("fc") || a.startsWith("fd")) return true; // fc00::/7 unique-local
  if (a.startsWith("fe8") || a.startsWith("fe9") || a.startsWith("fea") || a.startsWith("feb")) {
    return true; // fe80::/10 link-local
  }
  return false;
}

function headerValue(v: string | string[] | undefined): string | undefined {
  const s = Array.isArray(v) ? v[0] : v;
  const trimmed = s?.trim();
  return trimmed ? trimmed : undefined;
}
