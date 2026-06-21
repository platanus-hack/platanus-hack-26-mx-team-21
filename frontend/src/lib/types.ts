// Presentation config (app-owned) for observation types — color/unit/cost-step/
// fallback label. Rendering is data-driven over the live type catalog; this map
// only supplies styling. Unknown slugs fall back to neutral.

export interface TypePresentation {
  label: string; // Spanish fallback; DB label is preferred when present
  unit: string; // display unit for the "fact" quantity
  step: number; // cost-basis increment (MXN) for the ± controls
  color: string;
}

export const TYPE_PRESENTATION: Record<string, TypePresentation> = {
  pothole: { label: "Bache", unit: "m²", step: 100, color: "#e5484d" },
  open_drain: { label: "Coladera abierta", unit: "m lin", step: 200, color: "#2f64e6" },
  broken_light: { label: "Luminaria dañada", unit: "pza", step: 1000, color: "#f5a623" },
  missing_signage: { label: "Señalización faltante", unit: "pza", step: 1000, color: "#7c3aed" },
  damaged_sidewalk: { label: "Banqueta dañada", unit: "m²", step: 100, color: "#0f9b8e" },
};

export const NEUTRAL_COLOR = "#9aa3b1";

export function typeColor(slug: string): string {
  return TYPE_PRESENTATION[slug]?.color ?? NEUTRAL_COLOR;
}
export function typeUnit(slug: string): string {
  return TYPE_PRESENTATION[slug]?.unit ?? "pza";
}
export function typeStep(slug: string): number {
  return TYPE_PRESENTATION[slug]?.step ?? 1000;
}

// Default unit costs (MXN) used as the editable cost basis — mirrors the reference.
export const DEFAULT_COSTS: Record<string, number> = {
  pothole: 1800,
  open_drain: 6300,
  broken_light: 24000,
  missing_signage: 12000,
  damaged_sidewalk: 2400,
};

// ---- Live data shapes (mapped from the public.app_* RPCs) -------------------

export interface Tenant {
  id: string;
  name: string;
  accent: string;
}

export interface TypeCount {
  slug: string;
  label: string;
  category: string;
  isLatent: boolean;
  count: number;
}

export type ObsState = "scored" | "pending";

export interface Observation {
  id: string;
  slug: string;
  lat: number;
  lng: number;
  weight: number | null; // legacy priority weight — no longer drives pin styling
  volume: number | null; // size/quantity metadata — the pin decoration driver (§3)
  state: ObsState;
  zone: string | null;
  districtCve: string | null;
  districtName: string | null;
  source: string | null; // detector/provenance — "whatsapp-citizen" for citizen reports
  thumbPath: string | null; // R2 path of the ready thumbnail (citizen photo), else null
  sweep: string | null; // inspection sweep label (e.g. "SWP-6E79") — drives the "Ver recorrido" highlight
}

export interface ObservationDetail {
  id: string;
  slug: string;
  label: string;
  lat: number;
  lng: number;
  weight: number | null;
  state: ObsState;
  qty: number | null;
  unit: string | null;
  confirmations: number;
  misses: number;
  conf: number | null;
  observedAt: string;
  sweep: string;
  recordingId: string | null;
  frameRef: string | null;
  imageBbox: { x: number; y: number; w: number; h: number } | null;
  detector: string;
  districtName: string | null;
  zone: string | null;
}

// The coverage footprint + metadata for one inspection sweep ("recorrido"), resolved
// from a single observation. `coverage` is a GeoJSON geometry (the area the sweep
// covered — not a GPS track); the rest frames the sweep-view overlay and banner.
export interface SweepRoute {
  sweep: string;
  startedAt: string;
  endedAt: string;
  obsCount: number;
  areaKm2: number;
  coverage: unknown;
  originLat: number;
  originLng: number;
  // Recorded inspection footage (R2 sweep-video), null when the sweep has none. The
  // path is served through the broker; the "Ver recorrido" overlay plays it inline.
  videoBucket: string | null;
  videoPath: string | null;
  videoDurationMs: number | null;
  videoFps: number | null;
}

export interface Roi {
  id: string;
  riskDimension: string;
  lat: number;
  lng: number;
  riskScore: number;
  dominantType: string;
  description: string;
  signalCount: number | null;
  geojson: unknown;
}

export interface DimensionCount {
  dimension: string;
  count: number;
  maxRisk: number | null;
}

export interface RunSummary {
  id: string;
  kind: string; // legacy live kinds — relabeled to the single plan kind in the UI
  budget: number;
  status: string; // queued | running | succeeded | failed | cancelled
  createdAt: string;
  isLatent: boolean;
}

// ---- Action-plan model (§2) -------------------------------------------------

// Which issue types are selectable in the launcher. Potholes only for now; the
// rest render disabled ("Próximamente") until their data + module support land.
export const ACTIVE_ISSUE_TYPES = new Set<string>(["pothole"]);

// Default cluster/squad count when the user does not override it (§2.3.4).
export const DEFAULT_SQUADS = 3;
export const MAX_SQUADS = 8;

// Budget slider bounds (MXN). The mock bounds the selection with a flat nominal
// per pothole (MOCK_UNIT_COST) — see analysis.ts — so these are tuned to make the
// slider visibly bound the in-region selection, NOT a real cost model.
export const BUDGET_MIN = 250_000;
export const BUDGET_MAX = 4_000_000;
export const BUDGET_STEP = 250_000;
export const DEFAULT_BUDGET = 2_000_000;

// Flat, throwaway nominal cost per pothole used ONLY so the budget slider visibly
// bounds the selection. NOT a cost model — the real optimization module computes
// monetary cost from the cost-basis config. See analysis.ts §2.3.
export const MOCK_UNIT_COST = 150_000;

// Distinct per-squad colors (cycled if squads > palette length).
export const SQUAD_COLORS = [
  "#2f64e6",
  "#e5484d",
  "#0f9b8e",
  "#f5a623",
  "#7c3aed",
  "#d6409f",
  "#1d7a4d",
  "#c2410c",
];

// A region option for the alcaldía multi-select, derived from loaded observations.
export interface RegionOption {
  cve: string;
  name: string;
  count: number;
}

// A model-provided priority cluster (POTHOLE-specific). The frontend RECEIVES a list
// of these from the optimization model and only VISUALIZES them — it never computes
// priority. `weight` is the model's cluster priority (0..1). Reserved for the server-
// side planning endpoint (see citycrawlApi.clusterPriorities); not rendered on the map.
export interface ClusteredPriority {
  id: string;
  weight: number; // model-provided, normalized 0..1 — the region color driver
  polygon: [number, number][]; // region hull, [lat,lng] pairs
  centroid: { lat: number; lng: number };
  count: number;
}

// What the optimization module receives (mock today, Cloudflare Worker later).
export interface AnalysisPoint {
  id: string;
  lat: number;
  lng: number;
  slug: string;
  volume: number;
  zone: string | null;
  districtCve: string | null;
}

export interface AnalysisRequest {
  issueType: string;
  budget: number;
  regionFilter: string[]; // included INEGI cve_mun codes; empty = all
  squadCount?: number; // optional override; omitted = DEFAULT_SQUADS
  costs: Record<string, number>; // cost-basis config, passed THROUGH to the module
  points: AnalysisPoint[];
}

// Editable draft returned by the LLM draft-parser endpoint (/v1/llm/drafts:parse). Scalars
// may be null; list fields are always arrays. Populates the dock for review — never auto-runs.
export interface PlanDraft {
  issueType: string | null;
  budget: number | null;
  regionFilter: string[];
  squadCount: number | null;
  unresolvedTerms: string[];
  warnings: string[];
}

// One turn in the agent conversation. The full history is sent to /v1/llm/chat each turn.
export interface ChatMessage {
  role: "user" | "assistant";
  content: string;
}

// Response from /v1/llm/chat: the assistant's Spanish reply plus the full, merged draft.
// `generate` is true only when the user asked to run the plan now — the frontend then
// triggers optimization and opens the plan preview.
export interface DraftChatResponse {
  reply: string;
  draft: PlanDraft;
  generate: boolean;
}

export interface TopCritical {
  id: string;
  slug: string;
  lat: number;
  lng: number;
  volume: number;
  cost: number; // module output (placeholder in the mock)
  zone: string | null;
  rank: number;
}

export interface Squad {
  idx: number;
  color: string;
  weight: number; // model-provided cluster priority, normalized 0..1 — the region color driver
  members: string[]; // pothole ids in this squad's cluster
  polygon: [number, number][]; // convex hull, [lat,lng] pairs
  centroid: { lat: number; lng: number };
  cost: number;
  count: number;
}

export interface PlanStats {
  spent: number; // module output (placeholder in the mock)
  count: number;
  squads: number;
  regions: number;
  volume: number;
  budgetPct: number; // module output (placeholder in the mock)
}

export interface PlanResult {
  issueType: string;
  budget: number;
  regionFilter: string[];
  squadCountUsed: number;
  topCritical: TopCritical[];
  squads: Squad[];
  stats: PlanStats;
}

// ---- Real-time observation stream (§realtime listener) ----------------------

// The lean payload broadcast by community.broadcast_observation() on a tenant's
// private Realtime topic when a new observation becomes visible. Used only for the
// toast/pulse/locate — pin styling stays authoritative from getObservations().
export interface ObservationEvent {
  observation_id: string;
  slug: string;
  lat: number;
  lng: number;
  sweep_id: string | null;
  sweep: string | null; // 'SWP-XXXX'
  zone: string | null;
  observed_at: string;
}
