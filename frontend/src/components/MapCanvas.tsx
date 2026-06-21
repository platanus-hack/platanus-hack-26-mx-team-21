import { useEffect, useRef } from "react";
import L from "leaflet";
import type { Observation, PlanResult, Roi } from "../lib/types";
import { clusterIndices, convexHull, volumeColor, volumeRadius } from "../lib/geo";
import { riskLabel } from "../lib/analysis";

interface Props {
  observations: Observation[];
  boundary: unknown | null;
  showPins: boolean;
  showZones: boolean;
  showRois: boolean;
  activeTypes: Record<string, boolean>;
  issueType: string;
  squadTarget: number;
  plan: PlanResult | null; // non-null while previewing
  rois: Roi[];
  selectedId: string | null;
  accent: string;
  dockOpen: boolean;
  panTarget: { lat: number; lng: number; n: number } | null;
  onSelect: (id: string) => void;
}

const CARTO_LIGHT = "https://{s}.basemaps.cartocdn.com/light_all/{z}/{x}/{y}{r}.png";

export function MapCanvas(props: Props) {
  const elRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<L.Map | null>(null);
  const rendererRef = useRef<L.Canvas | null>(null);
  const groups = useRef<Record<string, L.LayerGroup>>({});
  const fitKeyRef = useRef<string>("");
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
      zones: L.layerGroup().addTo(map),
      rois: L.layerGroup().addTo(map),
      pins: L.layerGroup().addTo(map),
      plan: L.layerGroup().addTo(map),
    };
    setTimeout(() => map.invalidateSize(false), 0);
    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  // ---- boundary -----------------------------------------------------------
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
          opacity: 0.8,
          dashArray: "2 5",
          fill: true,
          fillColor: "#9aa3b1",
          fillOpacity: 0.02,
        },
      }).addTo(g);
    } catch {
      /* ignore malformed geometry */
    }
  }, [props.boundary]);

  // ---- generic cluster zones (always-available spatial-priority view) ------
  // Hidden while a plan is previewing (the plan's squads take over).
  useEffect(() => {
    const g = groups.current.zones;
    const r = rendererRef.current;
    if (!g || !r) return;
    g.clearLayers();
    if (!props.showZones || props.plan) return;
    const pts = props.observations.filter(
      (o) => o.slug === props.issueType && props.activeTypes[o.slug] && o.volume != null,
    );
    if (pts.length < 2) return;
    const groupsIdx = clusterIndices(pts, props.squadTarget);
    for (const idxs of groupsIdx) {
      const members = idxs.map((i) => pts[i]);
      if (members.length >= 3) {
        L.polygon(convexHull(members), {
          renderer: r,
          color: props.accent,
          weight: 1.4,
          opacity: 0.6,
          dashArray: "5 4",
          fill: true,
          fillColor: props.accent,
          fillOpacity: 0.06,
          interactive: false,
        }).addTo(g);
      } else {
        const c = members[0];
        L.circle([c.lat, c.lng], {
          renderer: r,
          radius: 380,
          color: props.accent,
          weight: 1.4,
          opacity: 0.6,
          dashArray: "5 4",
          fill: true,
          fillColor: props.accent,
          fillOpacity: 0.06,
          interactive: false,
        }).addTo(g);
      }
    }
  }, [
    props.observations,
    props.showZones,
    props.plan,
    props.activeTypes,
    props.issueType,
    props.squadTarget,
    props.accent,
  ]);

  // ---- risk-ROIs (external dataset) — toggleable standalone layer ----------
  useEffect(() => {
    const g = groups.current.rois;
    if (!g) return;
    g.clearLayers();
    if (!props.showRois) return;
    for (const roi of props.rois) {
      try {
        L.geoJSON({ type: "Feature", geometry: roi.geojson, properties: {} } as never, {
          interactive: false,
          style: {
            color: "#e5484d",
            weight: 1.8,
            dashArray: "5 4",
            fill: true,
            fillColor: "#e5484d",
            fillOpacity: 0.07,
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
      }).addTo(g);
    }
  }, [props.rois, props.showRois]);

  // ---- pins by volume -----------------------------------------------------
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
        // pending / no volume → neutral dashed
        L.circleMarker([o.lat, o.lng], {
          renderer: r,
          radius: 4.5,
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
          radius: volumeRadius(o.volume, maxVol),
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

  // ---- plan preview overlay (squad clusters + top-critical markers) -------
  useEffect(() => {
    const g = groups.current.plan;
    const r = rendererRef.current;
    if (!g || !r) return;
    g.clearLayers();
    const plan = props.plan;
    if (!plan) return;

    for (const sq of plan.squads) {
      if (sq.polygon.length >= 3) {
        L.polygon(sq.polygon, {
          renderer: r,
          color: sq.color,
          weight: 2,
          opacity: 0.9,
          fill: true,
          fillColor: sq.color,
          fillOpacity: 0.12,
          interactive: false,
        }).addTo(g);
      } else {
        L.circle([sq.centroid.lat, sq.centroid.lng], {
          renderer: r,
          radius: 420,
          color: sq.color,
          weight: 2,
          opacity: 0.9,
          fill: true,
          fillColor: sq.color,
          fillOpacity: 0.12,
          interactive: false,
        }).addTo(g);
      }
      L.marker([sq.centroid.lat, sq.centroid.lng], {
        interactive: false,
        icon: L.divIcon({
          className: "",
          html: `<div style="background:${sq.color};color:#fff;font:700 9px IBM Plex Mono,monospace;padding:2px 6px;border-radius:6px;white-space:nowrap;box-shadow:0 3px 9px -3px rgba(20,30,50,.5);transform:translate(-50%,-50%);">C${sq.idx} · ${sq.count}</div>`,
          iconSize: [0, 0],
        }),
      }).addTo(g);
    }

    for (const tc of plan.topCritical) {
      L.circleMarker([tc.lat, tc.lng], {
        renderer: r,
        radius: 11,
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

  // ---- fit to the plan (dock/panel-aware padding) -------------------------
  useEffect(() => {
    const map = mapRef.current;
    const plan = props.plan;
    if (!map || !plan) return;
    const ll: [number, number][] = plan.topCritical.map((t) => [t.lat, t.lng]);
    for (const sq of plan.squads) for (const p of sq.polygon) ll.push(p);
    if (!ll.length) return;
    const key = `${plan.stats.count}_${plan.stats.spent}_${plan.squadCountUsed}_${props.dockOpen}`;
    if (key === fitKeyRef.current) return;
    fitKeyRef.current = key;
    try {
      map.fitBounds(L.latLngBounds(ll).pad(0.2), {
        maxZoom: 14,
        animate: false,
        paddingTopLeft: [80, 80],
        paddingBottomRight: [404, props.dockOpen ? 200 : 90],
      });
    } catch {
      /* ignore */
    }
  }, [props.plan, props.dockOpen]);

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
}
