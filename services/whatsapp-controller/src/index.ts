import { createHash } from "node:crypto";
import express from "express";
import { config, validateConfig } from "./config";
import { logger } from "./logger";
import { ConversationEngine } from "./conversation";
import { KapsoGateway } from "./kapso";
import { parseInbound, checkWebhookSignature } from "./webhook";
import { FixedWindowRateLimiter, clientIp } from "./rateLimit";

const problems = validateConfig();
if (problems.length) logger.warn("config issues (continuing)", { problems });

const app = express();
// Behind Fly's edge proxy: let Express populate req.ip from the proxy chain. We still do
// our own spoof-resistant keying in clientIp() (socket peer + trusted Fly-Client-IP only).
app.set("trust proxy", true);
const engine = new ConversationEngine(new KapsoGateway());
// Per-client limiter: spoof-resistant key (see clientIp).
const webhookLimiter = new FixedWindowRateLimiter(config.webhook.rateLimitPerMin);
// Global flood ceiling: a single fixed bucket NOT keyed by the (spoofable) client IP, so a
// header-rotating flood that dodges the per-client limiter still hits an absolute cap.
// Sized generously vs. the per-client limit so it never throttles normal multi-user load.
const globalLimiter = new FixedWindowRateLimiter(config.webhook.globalRateLimitPerMin, 60_000, 1);

app.get("/health", (_req, res) => {
  res.json({ ok: true, mode: config.writeApi.mode });
});

// Meta-style verification handshake (harmless for the Kapso platform webhook).
app.get("/webhook", (req, res) => {
  const mode = req.query["hub.mode"];
  const token = req.query["hub.verify_token"];
  const challenge = req.query["hub.challenge"];
  if (mode === "subscribe" && token === config.webhook.verifyToken && challenge) {
    res.status(200).send(String(challenge));
    return;
  }
  res.sendStatus(403);
});

app.post("/webhook", express.raw({ type: "*/*", limit: "10mb" }), (req, res) => {
  // (a) Rate limit first — reject floods cheaply before any parsing/crypto.
  // Global flood ceiling (not keyed by the spoofable IP) catches header-rotating floods.
  const gl = globalLimiter.hit("global");
  if (!gl.allowed) {
    logger.warn("webhook globally rate limited", { limit: gl.limit });
    res.sendStatus(429);
    return;
  }
  // Per-client limit (spoof-resistant key) for normal abuse.
  const ip = clientIp(req);
  const rl = webhookLimiter.hit(ip);
  if (!rl.allowed) {
    logger.warn("webhook rate limited", { ip, limit: rl.limit });
    res.sendStatus(429);
    return;
  }

  const raw = req.body as Buffer;
  const signature = req.header(config.webhook.signatureHeader);

  // (b) Always compute the signature result (shadow mode). Never log secrets,
  // the signature value, or the body.
  const sig = checkWebhookSignature(raw, signature);
  logger.info("webhook signature check", {
    matched: sig.matched,
    variant: sig.variant,
    hadSecret: sig.hadSecret,
    hadSignature: sig.hadSignature,
    enforced: config.webhook.signatureRequired,
  });

  // (c) Enforcement (fail-closed). In shadow mode (signatureRequired=false) we never reject.
  if (config.webhook.signatureRequired) {
    if (!sig.hadSecret) {
      logger.error("signature enforcement enabled but no webhook secret configured (failing closed)");
      res.sendStatus(401);
      return;
    }
    if (!sig.matched) {
      logger.warn("invalid webhook signature (enforced)");
      res.sendStatus(401);
      return;
    }
  }

  let payload: unknown;
  try {
    payload = JSON.parse(raw.toString("utf8"));
  } catch {
    logger.warn("invalid JSON body");
    res.sendStatus(400);
    return;
  }

  const messages = parseInbound(payload);
  logger.info("webhook received", { count: messages.length });
  if (messages.length === 0) {
    // Nothing recognized. Do NOT log the raw attacker-controlled body (PII + log-volume
    // abuse, and it bypasses redactPhone/redactUrl). Log only the structural shape:
    // top-level key names, body byte length, and a short sha256 prefix for correlation.
    const topLevelKeys =
      payload && typeof payload === "object" && !Array.isArray(payload)
        ? Object.keys(payload as Record<string, unknown>)
        : [];
    logger.warn("no inbound messages parsed", {
      topLevelKeys,
      bytes: raw.length,
      bodySha256: createHash("sha256").update(raw).digest("hex").slice(0, 12),
    });
  }

  // Ack immediately so Kapso doesn't retry on slow downstream work; process after.
  res.sendStatus(200);

  void (async () => {
    for (const m of messages) {
      try {
        await engine.handle(m);
      } catch (err) {
        logger.error("handler error", { id: m.id, err: String(err) });
      }
    }
  })();
});

app.listen(config.port, () => {
  logger.info("whatsapp-controller listening", { port: config.port, mode: config.writeApi.mode });
});
