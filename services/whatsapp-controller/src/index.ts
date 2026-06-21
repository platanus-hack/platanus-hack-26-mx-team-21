import express from "express";
import { config, validateConfig } from "./config";
import { logger } from "./logger";
import { ConversationEngine } from "./conversation";
import { KapsoGateway } from "./kapso";
import { parseInbound, verifyWebhookSignature } from "./webhook";

const problems = validateConfig();
if (problems.length) logger.warn("config issues (continuing)", { problems });

const app = express();
const engine = new ConversationEngine(new KapsoGateway());

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
  const raw = req.body as Buffer;
  const signature = req.header(config.webhook.signatureHeader);

  // TEMP: surface signature-like headers so we can confirm Kapso's signing scheme.
  const sigHeaders = Object.keys(req.headers).filter((h) => /sign|hub|kapso|hmac/i.test(h));
  if (sigHeaders.length) {
    logger.info("webhook sig headers", {
      headers: sigHeaders.map((h) => `${h}: ${String(req.headers[h]).slice(0, 24)}`),
    });
  }

  if (!verifyWebhookSignature(raw, signature)) {
    logger.warn("invalid webhook signature");
    res.sendStatus(401);
    return;
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
