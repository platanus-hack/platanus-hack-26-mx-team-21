// Subscribes the browser to its tenant's private Realtime topic so it receives a
// broadcast each time a new observation becomes visible. The topic name and event
// match supabase/migrations/0301_observation_broadcast.sql.
import { supabase } from "./supabase";
import type { ObservationEvent } from "./types";

export function subscribeNewObservations(
  tenantId: string,
  accessToken: string,
  onEvent: (e: ObservationEvent) => void,
): () => void {
  // Private channels require the access token on the Realtime socket for authorization.
  supabase.realtime.setAuth(accessToken);

  const channel = supabase
    .channel(`tenant:${tenantId}`, { config: { private: true, broadcast: { self: false } } })
    .on("broadcast", { event: "observation_inserted" }, ({ payload }) => {
      onEvent(payload as ObservationEvent);
    })
    .subscribe((status) => {
      // Private channels fail silently on auth errors — log so misconfig is visible.
      if (status === "CHANNEL_ERROR" || status === "TIMED_OUT") {
        console.warn(`[observations] realtime channel ${status} for tenant:${tenantId}`);
      }
    });

  return () => {
    supabase.removeChannel(channel);
  };
}
