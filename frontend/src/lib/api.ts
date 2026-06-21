// Typed wrappers over the public.app_* RPC layer. The browser only ever calls
// these; it has no direct access to the custom schemas.
import { supabase } from "./supabase";
import type {
  DimensionCount,
  Observation,
  ObservationDetail,
  Roi,
  RunSummary,
  SweepRoute,
  Tenant,
  TypeCount,
} from "./types";

export async function getActiveTenant(): Promise<Tenant | null> {
  const { data, error } = await supabase.rpc("app_active_tenant");
  if (error) throw error;
  const row = data?.[0];
  return row ? { id: row.tenant_id, name: row.tenant_name, accent: row.accent } : null;
}

export async function getTypeCounts(): Promise<TypeCount[]> {
  const { data, error } = await supabase.rpc("app_observation_types_counts");
  if (error) throw error;
  return (data ?? []).map((r) => ({
    slug: r.slug,
    label: r.label,
    category: r.category,
    isLatent: r.is_latent,
    count: r.current_count,
  }));
}

export async function getObservations(): Promise<Observation[]> {
  const { data, error } = await supabase.rpc("app_map_observations");
  if (error) throw error;
  return (data ?? []).map((r) => ({
    id: r.id,
    slug: r.slug,
    lat: r.lat,
    lng: r.lng,
    weight: r.weight,
    volume: r.volume,
    state: (r.state as Observation["state"]) ?? "pending",
    zone: r.zone,
    districtCve: r.district_cve,
    districtName: r.district_name,
    source: r.source,
    thumbPath: r.thumb_path,
    sweep: r.sweep,
  }));
}

export async function getObservationDetail(id: string): Promise<ObservationDetail | null> {
  const { data, error } = await supabase.rpc("app_observation_detail", { p_id: id });
  if (error) throw error;
  const r = data?.[0];
  if (!r) return null;
  return {
    id: r.id,
    slug: r.slug,
    label: r.label,
    lat: r.lat,
    lng: r.lng,
    weight: r.weight,
    state: (r.state as ObservationDetail["state"]) ?? "pending",
    qty: r.qty,
    unit: r.unit,
    confirmations: r.confirmations,
    misses: r.misses,
    conf: r.conf,
    observedAt: r.observed_at,
    sweep: r.sweep,
    recordingId: r.recording_id,
    frameRef: r.frame_ref,
    imageBbox: (r.image_bbox as ObservationDetail["imageBbox"]) ?? null,
    detector: r.detector,
    districtName: r.district_name,
    zone: r.zone,
  };
}

// Resolve the inspection sweep behind one observation: its coverage footprint
// (GeoJSON), time window, observation count, and the originating point — for the
// "Ver recorrido" overlay. Returns null if the observation isn't visible.
export async function getSweepRoute(id: string): Promise<SweepRoute | null> {
  const { data, error } = await supabase.rpc("app_sweep_route", { p_observation_id: id });
  if (error) throw error;
  const r = data?.[0];
  if (!r) return null;
  return {
    sweep: r.sweep,
    startedAt: r.started_at,
    endedAt: r.ended_at,
    obsCount: r.obs_count,
    areaKm2: r.area_km2,
    coverage: r.coverage_geojson,
    originLat: r.origin_lat,
    originLng: r.origin_lng,
  };
}

export async function getRois(dimensions?: string[], limit?: number): Promise<Roi[]> {
  const { data, error } = await supabase.rpc("app_current_rois", {
    p_dimensions: dimensions && dimensions.length ? dimensions : undefined,
    p_limit: limit ?? undefined,
  });
  if (error) throw error;
  return (data ?? []).map((r) => ({
    id: r.id,
    riskDimension: r.risk_dimension,
    lat: r.centroid_lat,
    lng: r.centroid_lng,
    riskScore: r.risk_score,
    dominantType: r.dominant_type,
    description: r.description,
    signalCount: r.signal_count,
    geojson: r.geom_geojson,
  }));
}

export async function getRoiDimensionCounts(): Promise<DimensionCount[]> {
  const { data, error } = await supabase.rpc("app_roi_dimension_counts");
  if (error) throw error;
  return (data ?? []).map((r) => ({
    dimension: r.risk_dimension,
    count: r.roi_count,
    maxRisk: r.max_risk,
  }));
}

export async function getBoundary(): Promise<unknown | null> {
  const { data, error } = await supabase.rpc("app_tenant_boundary");
  if (error) throw error;
  return data ?? null;
}

export async function listRuns(): Promise<RunSummary[]> {
  const { data, error } = await supabase.rpc("app_list_runs");
  if (error) throw error;
  return (data ?? []).map((r) => ({
    id: r.id,
    kind: r.kind,
    budget: r.budget,
    status: r.status,
    createdAt: r.created_at,
    isLatent: r.is_latent,
  }));
}
