// Offline smoke test: drives the parser + state machine with fake Kapso I/O.
//   npx tsx scripts/smoke.ts
import { ConversationEngine } from "../src/conversation";
import { parseInbound } from "../src/webhook";
import { DryRunWriteApi } from "../src/writeApi";
import { DedupeStore, InMemorySessionStore } from "../src/session";
import type { DownloadedImage, KapsoGateway } from "../src/kapso";

const sent: Array<{ to: string; body: string }> = [];
const fakeKapso = {
  async sendText(to: string, body: string): Promise<void> {
    sent.push({ to, body });
    console.log(`  ↩︎  reply: ${body.split("\n")[0]}`);
  },
  async downloadImage(): Promise<DownloadedImage> {
    return { bytes: new Uint8Array([1, 2, 3, 4, 5, 6]).buffer, contentType: "image/jpeg", filename: "report.jpg" };
  },
} as unknown as KapsoGateway;

const engine = new ConversationEngine(
  fakeKapso,
  new DryRunWriteApi(),
  new InMemorySessionStore(),
  new DedupeStore(),
);

const PHONE_A = "5215512345678";
const PHONE_B = "5215511112222";

function kapsoEnvelope(message: Record<string, unknown>) {
  return { type: "whatsapp.message.received", batch: true, data: [{ message }] };
}

const imageMsg = kapsoEnvelope({
  whatsapp_message_id: "wamid.img1",
  phone_number: PHONE_A,
  message_type: "image",
  direction: "inbound",
  has_media: true,
  media_data: { url: "https://files.kapso.ai/abc.jpg", content_type: "image/jpeg", filename: "x.jpg", byte_size: 1234 },
  message_type_data: { caption: "bache enorme en la esquina" },
  created_at: "2026-06-20T18:00:00Z",
});

const locationMsg = kapsoEnvelope({
  whatsapp_message_id: "wamid.loc1",
  phone_number: PHONE_A,
  message_type: "location",
  direction: "inbound",
  message_type_data: { latitude: 19.4326, longitude: -99.1332, name: "Centro Histórico" },
  created_at: "2026-06-20T18:01:00Z",
});

// Meta Graph payload (location-first, then image) for a second user.
function metaPayload(message: Record<string, unknown>) {
  return {
    object: "whatsapp_business_account",
    entry: [
      {
        id: "WABA",
        changes: [
          {
            field: "messages",
            value: { messaging_product: "whatsapp", metadata: { phone_number_id: "PNID" }, messages: [message] },
          },
        ],
      },
    ],
  };
}

const metaLocation = metaPayload({
  from: PHONE_B,
  id: "wamid.meta.loc",
  timestamp: "1781042400",
  type: "location",
  location: { latitude: 19.42, longitude: -99.16 },
});
const metaImage = metaPayload({
  from: PHONE_B,
  id: "wamid.meta.img",
  timestamp: "1781042460",
  type: "image",
  image: { id: "MEDIA123", caption: "hoyo grande" },
});

async function feed(label: string, payload: unknown) {
  const msgs = parseInbound(payload);
  console.log(`\n• ${label} → parsed ${msgs.length} message(s): ${msgs.map((m) => m.kind).join(", ")}`);
  for (const m of msgs) await engine.handle(m);
}

async function main() {
  console.log("=== Scenario 1: Kapso envelope, photo then location ===");
  await feed("image", imageMsg);
  await feed("location", locationMsg);

  console.log("\n=== Scenario 2: Meta payload, location then photo (other user) ===");
  await feed("location", metaLocation);
  await feed("image", metaImage);

  console.log("\n=== Scenario 3: duplicate delivery of the image (should be ignored) ===");
  await feed("image (retry)", imageMsg);

  console.log(`\n✓ done. ${sent.length} replies sent.`);
}

void main();
