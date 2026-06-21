// Captures the CURRENT TypeScript planning outputs (runAnalysis + mockClusteredPriorities)
// into planning_parity.json. The Python parity test asserts MockPlanningEngine reproduces
// these byte-for-byte. Run with: node tests/integration/capture_ts_planning.mts
// (Node >= 23 strips TS types natively.)
import { runAnalysis, mockClusteredPriorities } from "../../../../frontend/src/lib/analysis.ts";
import type { AnalysisPoint, AnalysisRequest } from "../../../../frontend/src/lib/types.ts";
import { writeFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { dirname, join } from "node:path";

const here = dirname(fileURLToPath(import.meta.url));

// Deterministic spread of points across two districts.
const pts: AnalysisPoint[] = [];
for (let i = 0; i < 14; i++) {
  pts.push({
    id: `p${i}`,
    lat: 19.40 + (i % 7) * 0.012 + (i % 3) * 0.004,
    lng: -99.20 + Math.floor(i / 2) * 0.015 - (i % 4) * 0.003,
    slug: "pothole",
    volume: 30 + ((i * 37) % 220),
    zone: i % 2 ? "Centro" : "Norte",
    districtCve: i % 3 === 0 ? "005" : i % 3 === 1 ? "006" : "007",
  });
}

function req(over: Partial<AnalysisRequest>): AnalysisRequest {
  return {
    issueType: "pothole",
    budget: 2_000_000,
    regionFilter: [],
    costs: {},
    points: pts,
    ...over,
  };
}

const requests: { name: string; input: AnalysisRequest }[] = [
  { name: "empty", input: req({ points: [] }) },
  { name: "single", input: req({ points: [pts[0]] }) },
  { name: "budget_below_one", input: req({ budget: 100_000 }) },
  { name: "budget_two_items", input: req({ budget: 300_000 }) },
  { name: "default_full", input: req({ budget: 4_000_000 }) },
  { name: "excessive_squads", input: req({ budget: 4_000_000, squadCount: 50 }) },
  { name: "negative_squads", input: req({ budget: 4_000_000, squadCount: -3 }) },
  { name: "region_filtered", input: req({ regionFilter: ["005", "006"] }) },
];

const clusters: { name: string; points: AnalysisPoint[]; k: number | null }[] = [
  { name: "all", points: pts, k: null },
  { name: "k5", points: pts, k: 5 },
  { name: "single", points: [pts[0]], k: null },
];

const out = {
  requests: requests.map((r) => ({ name: r.name, input: r.input, plan: runAnalysis(r.input) })),
  clusters: clusters.map((c) => ({
    name: c.name,
    points: c.points,
    k: c.k,
    result: c.k == null ? mockClusteredPriorities(c.points) : mockClusteredPriorities(c.points, c.k),
  })),
};

writeFileSync(join(here, "fixtures", "planning_parity.json"), JSON.stringify(out, null, 2) + "\n");
console.log(
  `wrote planning_parity.json: ${out.requests.length} requests, ${out.clusters.length} cluster cases`,
);
