// User-facing copy (Spanish — CDMX citizens). Kept in one place for easy tuning.

const TYPE_LABELS: Record<string, string> = {
  pothole: "bache",
  streetlight: "luminaria",
  sidewalk: "banqueta dañada",
  trash: "acumulación de basura",
  flooding: "encharcamiento",
};

export function typeLabel(slug: string): string {
  return TYPE_LABELS[slug] ?? slug.replace(/_/g, " ");
}

export function help(): string {
  return [
    "👋 Soy el asistente de reportes de tu ciudad.",
    "",
    "Para reportar un *bache* o anomalía en la vía pública:",
    "1️⃣ Envíame una *foto* del problema.",
    "2️⃣ Comparte tu *ubicación*.",
    "",
    "Con eso lo agregamos al mapa. 🗺️",
  ].join("\n");
}

// Sent right after a PHOTO arrives: confirm the photo (📷), then ask for the location (📍).
export function photoReceivedAskLocation(): string {
  return [
    "📷 ¡Foto recibida!",
    "",
    "Ahora comparte la *ubicación* del problema 📍",
    "Toca 📎 (adjuntar) → *Ubicación* → *Enviar mi ubicación actual*.",
  ].join("\n");
}

// Sent right after a LOCATION arrives: confirm the location (📍), then ask for the photo (📷).
export function locationReceivedAskPhoto(): string {
  return [
    "📍 ¡Ubicación recibida!",
    "",
    "Ahora envíame una *foto* del bache o anomalía 📷 para completar tu reporte.",
  ].join("\n");
}

// Reminders when the user sends text while we're still waiting for the missing piece.
export function remindLocation(): string {
  return "📍 Sigo esperando tu *ubicación*. Toca 📎 (adjuntar) → *Ubicación*.";
}

export function remindPhoto(): string {
  return "📷 Sigo esperando la *foto* del bache o anomalía.";
}

export function confirmation(label: string): string {
  return [
    `✅ ¡Reporte recibido! Registramos tu reporte de *${label}*.`,
    "",
    "Aparecerá en el mapa de la ciudad para su revisión. Gracias por ayudar a mejorar tu colonia. 🙌",
  ].join("\n");
}

export function confirmationOutOfArea(label: string): string {
  return [
    `✅ Registramos tu reporte de *${label}*.`,
    "",
    "La ubicación parece estar fuera del área que monitoreamos por ahora, pero quedó guardada. ¡Gracias! 🙌",
  ].join("\n");
}

export function downloadError(): string {
  return "⚠️ No pudimos descargar tu foto. ¿Puedes reenviarla, por favor?";
}

export function submitError(): string {
  return "⚠️ Tuvimos un problema al registrar tu reporte. Por favor, vuelve a compartir tu *ubicación* para reintentar.";
}

// Sent after too many failed submit attempts: stop retrying and reset the conversation.
export function submitGaveUp(): string {
  return [
    "⚠️ No pudimos registrar tu reporte tras varios intentos.",
    "",
    "Lo sentimos. Inténtalo más tarde enviando de nuevo la *foto* y tu *ubicación*.",
  ].join("\n");
}

export function unsupported(): string {
  return "🤔 Por ahora solo proceso *fotos* y *ubicaciones*. Envíame una foto del problema para empezar.";
}
