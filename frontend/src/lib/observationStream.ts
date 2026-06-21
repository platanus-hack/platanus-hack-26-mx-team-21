// Pure grouping of buffered observation events into toast drafts. A burst from one
// sweep (many events sharing sweep_id) collapses to a single aggregated batch toast;
// a lone event (or one with no sweep_id) becomes a single toast. Kept pure so the
// grouping logic is unit-tested without Realtime/timers.
import { useEffect, useRef } from "react";
import type { ObservationEvent } from "./types";
import { subscribeNewObservations } from "./observationsRealtime";

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

export type Toast = ToastDraft & { id: string };

const FLUSH_MS = 700; // group a sweep's burst before raising toasts / refetching

export interface UseObservationStreamOpts {
  tenantId: string | null;
  accessToken: string | null;
  labelFor: (slug: string) => string;
  onRefetch: () => void;
  onToast: (t: Toast) => void;
}

// Subscribes to the tenant's realtime topic, buffers events for FLUSH_MS, groups
// them by sweep, raises toasts, and fires ONE authoritative refetch per flush.
export function useObservationStream(opts: UseObservationStreamOpts): void {
  const { tenantId, accessToken, labelFor, onRefetch, onToast } = opts;

  // Keep latest callbacks/label in refs so the subscribe effect only re-runs on identity.
  const labelRef = useRef(labelFor);
  labelRef.current = labelFor;
  const refetchRef = useRef(onRefetch);
  refetchRef.current = onRefetch;
  const toastRef = useRef(onToast);
  toastRef.current = onToast;
  const seq = useRef(0);

  useEffect(() => {
    if (!tenantId || !accessToken) return;

    let buffer: ObservationEvent[] = [];
    let timer: ReturnType<typeof setTimeout> | null = null;

    const flush = () => {
      timer = null;
      const events = buffer;
      buffer = [];
      if (events.length === 0) return;
      for (const draft of groupEvents(events, labelRef.current)) {
        toastRef.current({ ...draft, id: `obs-${seq.current++}` });
      }
      refetchRef.current(); // authoritative — folds new pins into the map state
    };

    const unsubscribe = subscribeNewObservations(tenantId, accessToken, (e) => {
      buffer.push(e);
      if (timer === null) timer = setTimeout(flush, FLUSH_MS);
    });

    return () => {
      if (timer !== null) clearTimeout(timer);
      unsubscribe();
    };
  }, [tenantId, accessToken]);
}
