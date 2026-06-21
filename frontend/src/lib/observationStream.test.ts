import { describe, it, expect } from "vitest";
import { groupEvents } from "./observationStream";
import type { ObservationEvent } from "./types";

const ev = (over: Partial<ObservationEvent>): ObservationEvent => ({
  observation_id: "o1",
  slug: "pothole",
  lat: 19.4,
  lng: -99.1,
  sweep_id: "s1",
  sweep: "SWP-S1AA",
  zone: "Cuauhtémoc",
  observed_at: "2026-06-21T10:00:00Z",
  ...over,
});

const label = (slug: string) => (slug === "pothole" ? "Bache" : slug);

describe("groupEvents", () => {
  it("returns a single-point draft for one event with a zone", () => {
    const out = groupEvents([ev({})], label);
    expect(out).toEqual([
      {
        kind: "single",
        message: "Nueva observación · Bache en Cuauhtémoc",
        target: { type: "point", observationId: "o1", lat: 19.4, lng: -99.1 },
      },
    ]);
  });

  it("drops ' en <zona>' when zone is null", () => {
    const out = groupEvents([ev({ zone: null })], label);
    expect(out[0].message).toBe("Nueva observación · Bache");
  });

  it("aggregates same-sweep events into one batch draft with bounds", () => {
    const out = groupEvents(
      [
        ev({ observation_id: "a", lat: 1, lng: 2 }),
        ev({ observation_id: "b", lat: 3, lng: 4 }),
        ev({ observation_id: "c", lat: 5, lng: 6 }),
      ],
      label,
    );
    expect(out).toEqual([
      {
        kind: "batch",
        message: "3 nuevas · barrido SWP-S1AA",
        target: {
          type: "bounds",
          points: [
            { lat: 1, lng: 2 },
            { lat: 3, lng: 4 },
            { lat: 5, lng: 6 },
          ],
        },
      },
    ]);
  });

  it("keeps distinct sweeps in separate drafts, null sweep_id stays single", () => {
    const out = groupEvents(
      [
        ev({ observation_id: "a", sweep_id: "s1", sweep: "SWP-S1AA" }),
        ev({ observation_id: "b", sweep_id: "s1", sweep: "SWP-S1AA" }),
        ev({ observation_id: "z", sweep_id: null, sweep: null }),
      ],
      label,
    );
    expect(out.map((d) => d.kind)).toEqual(["batch", "single"]);
    expect(out[0].message).toBe("2 nuevas · barrido SWP-S1AA");
  });

  it("returns [] for no events", () => {
    expect(groupEvents([], label)).toEqual([]);
  });
});
