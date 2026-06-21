import { memo, useEffect, useRef } from "react";
import L from "leaflet";
import type { Observation, PlanResult, Roi } from "../lib/types";
import { volumeColor } from "../lib/geo";
import { dimensionColor, dimensionLabel } from "../lib/dimensions";

function escapeHtml(s: string): string {
  return s.replace(
    /[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c] as string,
  );
}

// Popup shown when a risk zone is clicked: dimension, risk score, dominant type,
// signal count, and the generated inspection brief — the payoff of the real data.
function roiPopupHtml(roi: Roi): string {
  const color = dimensionColor(roi.riskDimension);
  const sc = roi.signalCount != null ? ` · ${roi.signalCount} señales` : "";
  const score = typeof roi.riskScore === "number" ? roi.riskScore.toFixed(1) : roi.riskScore;
  return `
    <div style="font-family:Public Sans,sans-serif;max-width:240px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <span style="width:9px;height:9px;border-radius:50%;background:${color};display:inline-block;"></span>
        <strong style="font-size:12px;color:#1b2430;">${dimensionLabel(roi.riskDimension)}</strong>
      </div>
      <div style="font-family:IBM Plex Mono,monospace;font-size:10px;color:#7a8493;margin-bottom:5px;">
        riesgo ${score} · ${escapeHtml(roi.dominantType ?? "")}${sc}
      </div>
      <div style="font-size:11px;line-height:1.4;color:#3a4250;">${escapeHtml(roi.description ?? "")}</div>
    </div>`;
}

interface Props {
  observations: Observation[];
  thumbUrls: Record<string, string>; // observation id → blob: URL of its citizen-report photo
  boundary: unknown | null;
  showPins: boolean;
  showRois: boolean;
  activeTypes: Record<string, boolean>;
  regionFilter: string[]; // included alcaldía cve_mun codes; empty = show all regions
  plan: PlanResult | null; // non-null while previewing a generated plan
  rois: Roi[];
  highlightSweep: string | null; // when set, only this sweep's pins stay lit ("Ver recorrido")
  selectedId: string | null;
  accent: string;
  panTarget: { lat: number; lng: number; n: number } | null;
  pulseIds: Set<string>;
  fitTarget: { points: { lat: number; lng: number }[]; n: number } | null;
  onSelect: (id: string) => void;
}

const CARTO_LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
const PIN_RADIUS = 6; // fixed — pins encode volume by COLOR only, never by size

export const MapCanvas = memo(function MapCanvas(props: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const groups = useRef<Record<string, L.LayerGroup>>({});
  const fitKeyRef = useRef<string>("");
  const sweepFitRef = useRef<string>("");
  const regionFitRef = useRef<string>("");
  const onSelectRef = useRef(props.onSelect);
  onSelectRef.current = props.onSelect;

  // ---- init once ----------------------------------------------------------
  useEffect(() => {
    if (!elRef.current || mapRef.current) return;
    const map = L.map(elRef.current, {
      zoomControl: false,
      attributionControl: true,
    }).setView([19.4, -99.13], 11);
    const renderer = L.canvas({ padding: 1 });
    renderer.addTo(map);
    L.control.zoom({ position: "bottomright" }).addTo(map);
    L.tileLayer(CARTO_LIGHT, {
      subdomains: "abcd",
      maxZoom: 19,
      attribution: "© OpenStreetMap © CARTO",
    }).addTo(map);
    mapRef.current = map;
    rendererRef.current = renderer;
    groups.current = {
      boundary: L.layerGroup().addTo(map),
      rois: L.layerGroup().addTo(map),
      pins: L.layerGroup().addTo(map),
      pulse: L.layerGroup().addTo(map),
      photos: L.layerGroup().addTo(map), // citizen-report thumbnail markers (WhatsApp photos)
      plan: L.layerGroup().addTo(map),
    };
    setTimeout(() => map.invalidateSize(false), 0);
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ---- boundary (subtle administrative outline, no heavy fill) -------------
  useEffect(() => {
    const g = groups.current.boundary;
    if (!g || !props.boundary) return;
    g.clearLayers();
    try {
      L.geoJSON({ type: "Feature", geometry: props.boundary, properties: {} } as never, {
        interactive: false,
        style: {
          color: "#aab2bd",
          weight: 1.3,
          opacity: 0.75,
          fill: true,
          fillColor: "#aab2bd",
          fillOpacity: 0.04,
        },
      }).addTo(g);
    } catch {
      /* ignore malformed geometry */
    }
  }, [props.boundary]);

  // ---- risk-ROIs (external dataset) — per-dimension toggleable layer --------
  // Dashed polygons colored by risk dimension; fill scaled by risk_score within the
  // dimension; click opens the inspection-brief popup. Kept label-free (no clutter).
  useEffect(() => {
    const g = groups.current.rois;
    if (!g) return;
    g.clearLayers();
    if (!props.showRois) return;
    const maxByDim: Record<string, number> = {};
    for (const roi of props.rois) {
      maxByDim[roi.riskDimension] = Math.max(maxByDim[roi.riskDimension] ?? 0, roi.riskScore ?? 0);
    }
    for (const roi of props.rois) {
      const color = dimensionColor(roi.riskDimension);
      const share = Math.max(0, Math.min(1, (roi.riskScore ?? 0) / (maxByDim[roi.riskDimension] || 1)));
      const fillOpacity = 0.08 + share * 0.24; // 0.08–0.32 within the dimension
      try {
        L.geoJSON({ type: "Feature", geometry: roi.geojson, properties: {} } as never, {
          interactive: true,
          style: {
            color,
            weight: 1.6,
            opacity: 0.75,
            dashArray: "5 4",
            fill: true,
            fillColor: color,
            fillOpacity,
          },
        })
          .bindPopup(roiPopupHtml(roi), { maxWidth: 260 })
          .addTo(g);
      } catch {
        /* ignore */
      }
    }
  }, [props.rois, props.showRois]);

  // ---- pins — fixed size, colored by volume metadata only -----------------
  useEffect(() => {
    const g = groups.current.pins;
    const r = rendererRef.current;
    if (!g || !r) return;
    g.clearLayers();
    if (!props.showPins) return;
    // Region filter: when alcaldías are selected, only observations bound to one of them
    // (by cve_mun) are drawn; empty filter shows every region. Unbound observations
    // (districtCve == null) are hidden whenever any region is selected.
    const regionSet = props.regionFilter.length ? new Set(props.regionFilter) : null;
    const inRegion = (o: Observation) =>
      !regionSet || (o.districtCve != null && regionSet.has(o.districtCve));
    // Sweep highlight ("Ver recorrido"): when a sweep is active, pins NOT in it are
    // faded to a faint grey so the sweep's continuous cluster stands out; its own pins
    // keep their full volume color. No active sweep → everything renders normally.
    const hl = props.highlightSweep;
    const inSweep = (o: Observation) => !hl || o.sweep === hl;
    const vols = props.observations
      .filter((o) => props.activeTypes[o.slug] && o.volume != null && inRegion(o))
      .map((o) => o.volume as number);
    const maxVol = vols.length ? Math.max(...vols) : 1;
    for (const o of props.observations) {
      if (!props.activeTypes[o.slug]) continue;
      if (!inRegion(o)) continue;
      if (props.thumbUrls[o.id]) continue; // shown as a photo marker instead of a dot
      const dim = hl != null && !inSweep(o);
      if (dim) {
        // not in the active sweep → faint grey wash, non-interactive so it can't steal clicks
        L.circleMarker([o.lat, o.lng], {
          renderer: r,
          radius: PIN_RADIUS - 2,
          stroke: false,
          fillColor: "#9aa3b1",
          fillOpacity: 0.18,
          interactive: false,
        }).addTo(g);
      } else if (o.volume == null) {
        // pending / no volume → neutral dashed (same size as the rest)
        L.circleMarker([o.lat, o.lng], {
          renderer: r,
          radius: PIN_RADIUS,
          color: "#9aa3b1",
          weight: 1.3,
          opacity: 0.85,
          fillColor: "#fff",
          fillOpacity: 0.85,
          dashArray: "2 2",
        })
          .on("click", () => onSelectRef.current(o.id))
          .addTo(g);
      } else {
        L.circleMarker([o.lat, o.lng], {
          renderer: r,
          radius: PIN_RADIUS,
          color: "#fff",
          weight: 1.3,
          opacity: 0.95,
          fillColor: volumeColor(o.volume, maxVol),
          fillOpacity: 0.92,
        })
          .on("click", () => onSelectRef.current(o.id))
          .addTo(g);
      }
    }
  }, [props.observations, props.showPins, props.activeTypes, props.thumbUrls, props.regionFilter, props.highlightSweep]);

  // ---- transient pulse halos on freshly-arrived pins ----------------------
  useEffect(() => {
    const g = groups.current.pulse;
    if (!g) return;
    g.clearLayers();
    if (props.pulseIds.size === 0) return;
    for (const o of props.observations) {
      if (!props.pulseIds.has(o.id)) continue;
      L.marker([o.lat, o.lng], {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html: `<div style="width:14px;height:14px;border-radius:50%;background:${props.accent};animation:obs-pulse 1.4s ease-out 2;"></div>`,
          iconSize: [0, 0],
        }),
      }).addTo(g);
    }
  }, [props.pulseIds, props.observations, props.accent]);

  // ---- fit to the selected region(s) -------------------------------------
  // When the region filter changes to a non-empty selection, frame the bounding box of
  // the in-region observations (panel-aware padding). Keyed on the sorted cve set so it
  // fits once per distinct selection and never fights the user's manual pan/zoom.
  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;
    const key = props.regionFilter.slice().sort().join(",");
    if (key === regionFitRef.current) return;
    regionFitRef.current = key;
    if (!props.regionFilter.length) return;
    const set = new Set(props.regionFilter);
    const ll: [number, number][] = props.observations
      .filter((o) => o.districtCve != null && set.has(o.districtCve))
      .map((o) => [o.lat, o.lng]);
    if (!ll.length) return;
    try {
      map.fitBounds(L.latLngBounds(ll).pad(0.08), {
        maxZoom: 13,
        animate: true,
        paddingTopLeft: [80, 80],
        paddingBottomRight: [404, 220],
      });
    } catch {
      /* ignore */
    }
  }, [props.regionFilter, props.observations]);

  // ---- citizen-report photo markers (WhatsApp) ----------------------------
  // Observations carrying a thumbnail (today: WhatsApp citizen reports) render as their
  // actual photo instead of a dot, with a white frame + accent ring so they read as
  // citizen-sourced. Same toggles as the pins (showPins + per-type). Clicking selects.
  useEffect(() => {
    const g = groups.current.photos;
    if (!g) return;
    g.clearLayers();
    if (!props.showPins) return;
    const regionSet = props.regionFilter.length ? new Set(props.regionFilter) : null;
    for (const o of props.observations) {
      if (!props.activeTypes[o.slug]) continue;
      if (regionSet && (o.districtCve == null || !regionSet.has(o.districtCve))) continue;
      const url = props.thumbUrls[o.id];
      if (!url) continue;
      L.marker([o.lat, o.lng], {
        icon: L.divIcon({
          className: "",
          html: `<div style="width:40px;height:40px;border-radius:11px;overflow:hidden;background:#e7ebf1;border:2.5px solid #fff;box-shadow:0 0 0 2px ${props.accent},0 4px 11px -3px rgba(20,30,50,.5);transform:translate(-50%,-50%);cursor:pointer;"><img src="${url}" loading="lazy" style="width:100%;height:100%;object-fit:cover;display:block;" /></div>`,
          iconSize: [0, 0],
        }),
      })
        .on("click", () => onSelectRef.current(o.id))
        .addTo(g);
    }
  }, [props.observations, props.showPins, props.activeTypes, props.thumbUrls, props.accent, props.regionFilter]);

  // ---- plan preview overlay (crew clusters + ranked markers) --------------
  // Crews (cuadrillas) are a DISPATCH concept: each gets a categorical color so they
  // read as distinct teams — NOT the priority ramp (that's the priority-zone layer).
  // Nothing here renders unless a plan is present.
  useEffect(() => {
    const g = groups.current.plan;
    const r = rendererRef.current;
    if (!g || !r) return;
    g.clearLayers();
    const plan = props.plan;
    if (!plan) return;

    // 1. Crew regions — categorical color per crew, drawn as the cluster's hull polygon.
    // (A cluster needs ≥3 points to form a polygon; smaller ones show only their hub chip.)
    for (const sq of plan.squads) {
      if (sq.polygon.length < 3) continue;
      L.polygon(sq.polygon, {
        renderer: r,
        color: sq.color,
        weight: 1.5,
        opacity: 0.85,
        fill: true,
        fillColor: sq.color,
        fillOpacity: 0.14,
        interactive: false,
      }).addTo(g);
    }

    // 2. Centroid hubs — chip in the crew color.
    for (const sq of plan.squads) {
      L.marker([sq.centroid.lat, sq.centroid.lng], {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html: `<div style="background:${sq.color};color:#fff;font:700 9px IBM Plex Mono,monospace;padding:2px 7px;border-radius:7px;white-space:nowrap;box-shadow:0 3px 9px -3px rgba(20,30,50,.4);transform:translate(-50%,-50%);">C${sq.idx} · ${sq.count}</div>`,
          iconSize: [0, 0],
        }),
      }).addTo(g);
    }

    // 3. Ranked top-critical markers (a plan annotation — numbered, not a data pin).
    for (const tc of plan.topCritical) {
      L.circleMarker([tc.lat, tc.lng], {
        renderer: r,
        radius: 10,
        color: "#fff",
        weight: 2,
        fillColor: props.accent,
        fillOpacity: 1,
      })
        .on("click", () => onSelectRef.current(tc.id))
        .addTo(g);
      L.marker([tc.lat, tc.lng], {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html: `<div style="color:#fff;font:700 10px IBM Plex Mono,monospace;transform:translate(-50%,-50%);">${tc.rank}</div>`,
          iconSize: [0, 0],
        }),
      }).addTo(g);
    }
  }, [props.plan, props.accent]);

  // ---- fit to the highlighted sweep ("Ver recorrido") --------------------
  // Frame the bounding box of the active sweep's observations (panel-aware padding),
  // once per distinct sweep so it never fights the user's manual pan/zoom.
  useEffect(() => {
    const map = mapRef.current;
    const hl = props.highlightSweep;
    if (!map) return;
    if (hl === sweepFitRef.current) return;
    sweepFitRef.current = hl ?? "";
    if (!hl) return;
    const ll: [number, number][] = props.observations
      .filter((o) => o.sweep === hl)
      .map((o) => [o.lat, o.lng]);
    if (!ll.length) return;
    try {
      map.fitBounds(L.latLngBounds(ll).pad(0.08), {
        maxZoom: 14,
        animate: true,
        paddingTopLeft: [80, 80],
        paddingBottomRight: [360, 220],
      });
    } catch {
      /* ignore */
    }
  }, [props.highlightSweep, props.observations]);

  // ---- fit to the plan (panel-aware padding) ------------------------------
  // NOTE: intentionally NOT keyed on dockOpen. Refitting fires a synchronous full-map
  // reprojection; doing that on every dock open/close stutters the panel animation.
  // A fixed bottom padding keeps plan content clear of the dock at its open height.
  useEffect(() => {
    const map = mapRef.current;
    const plan = props.plan;
    if (!map || !plan) return;
    const ll: [number, number][] = plan.topCritical.map((t) => [t.lat, t.lng]);
    for (const sq of plan.squads) for (const p of sq.polygon) ll.push(p);
    if (!ll.length) return;
    const key = `${plan.stats.count}_${plan.stats.spent}_${plan.squadCountUsed}`;
    if (key === fitKeyRef.current) return;
    fitKeyRef.current = key;
    try {
      map.fitBounds(L.latLngBounds(ll).pad(0.2), {
        maxZoom: 14,
        animate: false,
        paddingTopLeft: [80, 80],
        paddingBottomRight: [404, 200],
      });
    } catch {
      /* ignore */
    }
  }, [props.plan]);

  // ---- pan to selection ---------------------------------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !props.selectedId) return;
    const o = props.observations.find((x) => x.id === props.selectedId);
    if (o) map.panTo([o.lat, o.lng], { animate: true });
  }, [props.selectedId, props.observations]);

  // ---- fly to an arbitrary target (locate a squad) ------------------------
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !props.panTarget) return;
    map.flyTo([props.panTarget.lat, props.panTarget.lng], 14, { animate: true });
  }, [props.panTarget]);

  // ---- fit to a batch of new observations ("Ver" on a batch toast) --------
  const fitNRef = useRef(0);
  useEffect(() => {
    const map = mapRef.current;
    const ft = props.fitTarget;
    if (!map || !ft || ft.n === fitNRef.current || ft.points.length === 0) return;
    fitNRef.current = ft.n;
    const ll = ft.points.map((p) => [p.lat, p.lng]) as [number, number][];
    try {
      map.fitBounds(L.latLngBounds(ll).pad(0.2), {
        maxZoom: 15,
        animate: true,
        paddingTopLeft: [80, 80],
        paddingBottomRight: [320, 220],
      });
    } catch {
      /* ignore */
    }
  }, [props.fitTarget]);

  return <div ref={elRef} className="absolute inset-0 z-0" />;
});
