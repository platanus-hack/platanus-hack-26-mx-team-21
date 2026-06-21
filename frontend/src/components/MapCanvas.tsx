import { memo, useEffect, useRef } from "react";
import L from "leaflet";
import type { Observation, PlanResult, Roi } from "../lib/types";
import { volumeColor } from "../lib/geo";
import { riskLabel } from "../lib/analysis";

interface Props {
  observations: Observation[];
  boundary: unknown | null;
  showPins: boolean;
  showRois: boolean;
  activeTypes: Record<string, boolean>;
  plan: PlanResult | null; // non-null while previewing a generated plan
  rois: Roi[];
  selectedId: string | null;
  accent: string;
  dockOpen: boolean;
  panTarget: { lat: number; lng: number; n: number } | null;
  onSelect: (id: string) => void;
}

const CARTO_LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";
const PIN_RADIUS = 6; // fixed — pins encode volume by COLOR only, never by size
const ROI_LABEL_ZOOM = 13; // risk-zone labels only appear once zoomed in this far

export const MapCanvas = memo(function MapCanvas(props: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const groups = useRef<Record<string, L.LayerGroup>>({});
  const fitKeyRef = useRef<string>("");
  const onSelectRef = useRef(props.onSelect);
  onSelectRef.current = props.onSelect;
  const showRoisRef = useRef(props.showRois);
  showRoisRef.current = props.showRois;

  // Show/hide the ROI label layer depending on zoom (and the ROI toggle).
  const syncRoiLabels = () => {
    const map = mapRef.current;
    const labels = groups.current.roiLabels;
    if (!map || !labels) return;
    const visible = showRoisRef.current && map.getZoom() >= ROI_LABEL_ZOOM;
    if (visible && !map.hasLayer(labels)) labels.addTo(map);
    else if (!visible && map.hasLayer(labels)) map.removeLayer(labels);
  };

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
      roiLabels: L.layerGroup(), // added/removed by zoom, see syncRoiLabels
      pins: L.layerGroup().addTo(map),
      plan: L.layerGroup().addTo(map),
    };
    map.on("zoomend", syncRoiLabels);
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

  // ---- risk-ROIs (external dataset) — toggleable standalone layer ----------
  // Polygons live in the `rois` group; labels live in `roiLabels`, which is only
  // attached when zoomed in (ROI_LABEL_ZOOM) so labels never clutter the overview.
  useEffect(() => {
    const g = groups.current.rois;
    const gl = groups.current.roiLabels;
    if (!g || !gl) return;
    g.clearLayers();
    gl.clearLayers();
    if (!props.showRois) {
      syncRoiLabels();
      return;
    }
    for (const roi of props.rois) {
      try {
        L.geoJSON({ type: "Feature", geometry: roi.geojson, properties: {} } as never, {
          interactive: false,
          style: {
            color: "#e5484d",
            weight: 1.6,
            opacity: 0.7,
            dashArray: "5 4",
            fill: true,
            fillColor: "#e5484d",
            fillOpacity: 0.06,
          },
        }).addTo(g);
      } catch {
        /* ignore */
      }
      L.marker([roi.lat, roi.lng], {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html: `<div style="background:#fff;color:#c2333a;font:600 9.5px IBM Plex Mono,monospace;padding:2px 7px;border-radius:6px;white-space:nowrap;border:1px solid #f4cdcd;box-shadow:0 3px 9px -3px rgba(197,51,58,.4);transform:translate(-50%,-50%);">${riskLabel(roi.riskDimension)}</div>`,
          iconSize: [0, 0],
        }),
      }).addTo(gl);
    }
    syncRoiLabels();
  }, [props.rois, props.showRois]);

  // ---- pins — fixed size, colored by volume metadata only -----------------
  useEffect(() => {
    const g = groups.current.pins;
    const r = rendererRef.current;
    if (!g || !r) return;
    g.clearLayers();
    if (!props.showPins) return;
    const vols = props.observations
      .filter((o) => props.activeTypes[o.slug] && o.volume != null)
      .map((o) => o.volume as number);
    const maxVol = vols.length ? Math.max(...vols) : 1;
    for (const o of props.observations) {
      if (!props.activeTypes[o.slug]) continue;
      if (o.volume == null) {
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
  }, [props.observations, props.showPins, props.activeTypes]);

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

  return <div ref={elRef} style={{ position: "absolute", inset: 0, zIndex: 0 }} />;
});
