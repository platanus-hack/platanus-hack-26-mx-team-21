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
const engine = new ConversationEngine(new KapsoGateway());
const webhookLimiter = new FixedWindowRateLimiter(config.webhook.rateLimitPerMin);

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
  // (a) Per-IP rate limit first — reject floods cheaply before any parsing/crypto.
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
    // Nothing recognized — surface the raw shape so we can adjust the parser.
    logger.warn("no inbound messages parsed", { body: raw.toString("utf8").slice(0, 1000) });
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
