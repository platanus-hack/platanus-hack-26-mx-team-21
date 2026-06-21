// Pure grouping of buffered observation events into toast drafts. A burst from one
// sweep (many events sharing sweep_id) collapses to a single aggregated batch toast;
// a lone event (or one with no sweep_id) becomes a single toast. Kept pure so the
// grouping logic is unit-tested without Realtime/timers.
import type { ObservationEvent } from "./types";

export type ToastTarget =
  | { type: "point"; observationId: string; lat: number; lng: number }
  | { type: "bounds"; points: { lat: number; lng: number }[] };

export interface ToastDraft {
  kind: "single" | "batch";
  message: string;
  target: ToastTarget;
}

function singleDraft(e: ObservationEvent, labelFor: (slug: string) => string): ToastDraft {
  const base = `Nueva observación · ${labelFor(e.slug)}`;
  return {
    kind: "single",
    message: e.zone ? `${base} en ${e.zone}` : base,
    target: { type: "point", observationId: e.observation_id, lat: e.lat, lng: e.lng },
  };
}

export function groupEvents(
  events: ObservationEvent[],
  labelFor: (slug: string) => string,
): ToastDraft[] {
  // Preserve first-seen order of sweep groups; null sweep_id never groups.
  const order: string[] = [];
  const groups = new Map<string, ObservationEvent[]>();
  let loose = 0;

  for (const e of events) {
    if (!e.sweep_id) {
      const key = `__loose_${loose++}`;
      order.push(key);
      groups.set(key, [e]);
      continue;
    }
    if (!groups.has(e.sweep_id)) {
      order.push(e.sweep_id);
      groups.set(e.sweep_id, []);
    }
    groups.get(e.sweep_id)!.push(e);
  }

  return order.map((key) => {
    const g = groups.get(key)!;
    if (g.length === 1) return singleDraft(g[0], labelFor);
    return {
      kind: "batch",
      message: `${g.length} nuevas · barrido ${g[0].sweep}`,
      target: { type: "bounds", points: g.map((e) => ({ lat: e.lat, lng: e.lng })) },
    };
  });
}
