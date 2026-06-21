// MOCK optimization provider — placeholder for the Cloudflare-Worker optimization
// module (§2.3). It deliberately does NOT model monetary cost: it ranks by volume,
// bounds the selection with a flat throwaway nominal so the budget slider matters,
// and clusters the selection into squads. The real module replaces this one call;
// the rest of the app (request/result shapes) is unaffected.
import type { AnalysisRequest, PlanResult, Squad, TopCritical } from "./types";
import { DEFAULT_SQUADS, MAX_SQUADS, MOCK_UNIT_COST, SQUAD_COLORS } from "./types";
import { centroidOf, clusterIndices, convexHull } from "./geo";

const RISK_LABEL: Record<string, string> = {
  crash: "Zona de choques",
  violation: "Infracciones recurrentes",
  flooding: "Riesgo de inundación",
  road_surface: "Pavimento deteriorado",
  crime: "Incidencia delictiva",
};
export function riskLabel(dim: string): string {
  return RISK_LABEL[dim] ?? "Zona de riesgo";
}

function clampSquads(override?: number): number {
  const k = override ?? DEFAULT_SQUADS;
  return Math.max(1, Math.min(MAX_SQUADS, Math.round(k)));
}

// Turn a single analysis request into one action plan: top-critical (budget-funded,
// criticality-ranked) + squads (the selection clustered, one squad per cluster).
export function runAnalysis(req: AnalysisRequest): PlanResult {
  const squadTarget = clampSquads(req.squadCount);

  // 1. Eligible = region/type-filtered points that have a known volume.
  const eligible = req.points.filter((p) => typeof p.volume === "number" && p.volume > 0);

  // 2. Criticality ranks by volume (larger/worse first).
  const ranked = [...eligible].sort((a, b) => b.volume - a.volume);

  // 3. Budget selection — trivial throwaway proxy (flat nominal per pothole). This is
  //    NOT a cost model; real monetary-cost computation is the module's job (deferred).
  const selected: typeof ranked = [];
  let spent = 0;
  for (const p of ranked) {
    if (spent + MOCK_UNIT_COST > req.budget) break;
    selected.push(p);
    spent += MOCK_UNIT_COST;
  }

  const topCritical: TopCritical[] = selected.map((p, i) => ({
    id: p.id,
    slug: p.slug,
    lat: p.lat,
    lng: p.lng,
    volume: p.volume,
    cost: MOCK_UNIT_COST, // placeholder — replaced by the module's real cost
    zone: p.zone,
    rank: i + 1,
  }));

  // 4. Cluster the selected set into K squads (one squad per cluster).
  const groups = clusterIndices(selected, squadTarget);
  const rawWeights = groups.map((idxs) => idxs.reduce((s, j) => s + selected[j].volume, 0));
  const maxWeight = Math.max(1, ...rawWeights);
  const squads: Squad[] = groups.map((idxs, i) => {
    const members = idxs.map((j) => selected[j]);
    return {
      idx: i + 1,
      color: SQUAD_COLORS[i % SQUAD_COLORS.length],
      // MOCK cluster priority — the optimization module supplies the real weight.
      // Here we proxy it by the cluster's total volume (normalized 0..1) only so the
      // region color ramp renders. NOT a model. The app never derives priority itself.
      weight: rawWeights[i] / maxWeight,
      members: members.map((m) => m.id),
      polygon: convexHull(members),
      centroid: centroidOf(members),
      cost: members.length * MOCK_UNIT_COST,
      count: members.length,
    };
  });

  // 5. Stats — placeholder spent/budgetPct (faked by the mock).
  const regions = new Set(selected.map((p) => p.districtCve).filter(Boolean)).size;
  const volume = selected.reduce((s, p) => s + p.volume, 0);
  const budgetPct = req.budget > 0 ? Math.min(100, Math.round((spent / req.budget) * 100)) : 0;

  return {
    issueType: req.issueType,
    budget: req.budget,
    regionFilter: req.regionFilter,
    squadCountUsed: squads.length,
    topCritical,
    squads,
    stats: {
      spent,
      count: selected.length,
      squads: squads.length,
      regions,
      volume,
      budgetPct,
    },
  };
}
