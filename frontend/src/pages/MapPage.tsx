import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapCanvas } from "../components/MapCanvas";
import { LayersPanel } from "../components/LayersPanel";
import { AgentPanel } from "../components/AgentPanel";
import { AnalysisDock } from "../components/AnalysisDock";
import { HistoryPopover, type PlanHistoryItem } from "../components/HistoryPopover";
import { ObservationCard } from "../components/ObservationCard";
import { useAuth } from "../lib/auth";
import * as api from "../lib/api";
import { optimizePlan, parseDraft } from "../lib/citycrawlApi";
import {
  ACTIVE_ISSUE_TYPES,
  DEFAULT_BUDGET,
  DEFAULT_COSTS,
  BUDGET_MAX,
  BUDGET_MIN,
} from "../lib/types";
import type {
  AnalysisPoint,
  AnalysisRequest,
  Observation,
  ObservationDetail,
  PlanDraft,
  PlanResult,
  RegionOption,
  Roi,
  RunSummary,
  TypeCount,
} from "../lib/types";

const ISSUE_DEFAULT = "pothole";

interface PlanRun {
  id: string;
  createdAt: string;
  request: AnalysisRequest;
  result: PlanResult;
}

interface PlanConfig {
  issueType: string;
  budget: number;
  regionFilter: string[];
  squadOverride: number | null;
}

// Assemble the region-filtered points (with volume) the optimization module receives.
function buildPoints(
  obs: Observation[],
  issueType: string,
  regionFilter: string[],
): AnalysisPoint[] {
  return obs
    .filter(
      (o) =>
        o.slug === issueType &&
        o.volume != null &&
        (regionFilter.length === 0 ||
          (o.districtCve != null && regionFilter.includes(o.districtCve))),
    )
    .map((o) => ({
      id: o.id,
      lat: o.lat,
      lng: o.lng,
      slug: o.slug,
      volume: o.volume as number,
      zone: o.zone,
      districtCve: o.districtCve,
    }));
}

function buildRequest(
  cfg: PlanConfig,
  costs: Record<string, number>,
  obs: Observation[],
): AnalysisRequest {
  return {
    issueType: cfg.issueType,
    budget: cfg.budget,
    regionFilter: cfg.regionFilter,
    squadCount: cfg.squadOverride ?? undefined,
    costs,
    points: buildPoints(obs, cfg.issueType, cfg.regionFilter),
  };
}

export function MapPage() {
  const { signOut } = useAuth();

  // ---- live data ----------------------------------------------------------
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [accent, setAccent] = useState("#2f64e6");
  const [types, setTypes] = useState<TypeCount[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  const [rois, setRois] = useState<Roi[]>([]);
  const [boundary, setBoundary] = useState<unknown | null>(null);
  const [liveRuns, setLiveRuns] = useState<RunSummary[]>([]);

  // ---- layer toggles ------------------------------------------------------
  const [showPins, setShowPins] = useState(true);
  const [showRois, setShowRois] = useState(true);
  const [activeTypes, setActiveTypes] = useState<Record<string, boolean>>({});

  // ---- config (the dock) --------------------------------------------------
  const [issueType, setIssueType] = useState(ISSUE_DEFAULT);
  const [budget, setBudget] = useState(DEFAULT_BUDGET);
  const [regionFilter, setRegionFilter] = useState<string[]>([]);
  const [squadOverride, setSquadOverride] = useState<number | null>(null);
  const [costs, setCosts] = useState<Record<string, number>>({ ...DEFAULT_COSTS });

  // ---- dock (the bottom config bar) collapse toggle -----------------------
  const [dockOpen, setDockOpen] = useState(true);
  const [dockHeight, setDockHeight] = useState(210);

  // Keep a consistent gap between the layers panel and whatever sits bottom-left
  // (the open dock, height-measured; or the 52px launcher when collapsed).
  const LAUNCHER_H = 52;
  const PANEL_GAP = 16;
  const layersBottom = 18 + (dockOpen ? dockHeight : LAUNCHER_H) + PANEL_GAP;

  // ---- plan lifecycle -----------------------------------------------------
  const [previewing, setPreviewing] = useState(false);
  const [history, setHistory] = useState<PlanRun[]>([]);
  const [activeHistId, setActiveHistId] = useState<string | null>(null);
  const [histOpen, setHistOpen] = useState(false);
  const [generating, setGenerating] = useState(false);
  const [planError, setPlanError] = useState<string | null>(null);

  // ---- selection ----------------------------------------------------------
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [detail, setDetail] = useState<ObservationDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [panTarget, setPanTarget] = useState<{ lat: number; lng: number; n: number } | null>(null);

  const seq = useRef(1);
  const nextId = () => `plan-${seq.current++}`;
  // Re-entry guard for plan generation — independent of any panel, so the dock's
  // "Generar plan" button, the quick-action chips, and history replay can't overlap.
  const generatingRef = useRef(false);

  // ---- initial load -------------------------------------------------------
  useEffect(() => {
    let alive = true;
    (async () => {
      try {
        const [tenant, tc, obs, ro, bnd, live] = await Promise.all([
          api.getActiveTenant(),
          api.getTypeCounts(),
          api.getObservations(),
          api.getRois(),
          api.getBoundary(),
          api.listRuns(),
        ]);
        if (!alive) return;
        if (tenant?.accent) {
          setAccent(tenant.accent);
          document.documentElement.style.setProperty("--acc", tenant.accent);
        }
        setTypes(tc);
        setActiveTypes(Object.fromEntries(tc.map((t) => [t.slug, true])));
        setObservations(obs);
        setRois(ro);
        setBoundary(bnd);
        setLiveRuns(live);
        setLoaded(true);
      } catch (e) {
        if (alive) setLoadError(e instanceof Error ? e.message : String(e));
      }
    })();
    return () => {
      alive = false;
    };
  }, []);

  // ---- derived ------------------------------------------------------------
  const typeLabels = useMemo(
    () => Object.fromEntries(types.map((t) => [t.slug, t.label])),
    [types],
  );

  const regions = useMemo<RegionOption[]>(() => {
    const m = new Map<string, RegionOption>();
    for (const o of observations) {
      if (o.slug !== issueType || !o.districtCve) continue;
      const cur = m.get(o.districtCve);
      if (cur) cur.count++;
      else m.set(o.districtCve, { cve: o.districtCve, name: o.districtName ?? o.districtCve, count: 1 });
    }
    return [...m.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }, [observations, issueType]);

  const request = useMemo<AnalysisRequest>(
    () => buildRequest({ issueType, budget, regionFilter, squadOverride }, costs, observations),
    [issueType, budget, regionFilter, squadOverride, costs, observations],
  );

  // The plan is a SNAPSHOT captured when "Generar/Actualizar plan" is pressed
  // (startPlan stores the result in history). It is NOT recomputed live as the config
  // changes — changing budget/region/etc. only takes effect on the next Generate.
  const activePlan = useMemo<PlanResult | null>(
    () => (previewing ? history.find((h) => h.id === activeHistId)?.result ?? null : null),
    [previewing, activeHistId, history],
  );

  const pointCount = request.points.length;

  const historyItems = useMemo<PlanHistoryItem[]>(() => {
    const local: PlanHistoryItem[] = history.map((h) => ({
      id: h.id,
      budget: h.request.budget,
      status: "succeeded",
      createdAt: h.createdAt,
      count: h.result.stats.count,
    }));
    const live: PlanHistoryItem[] = liveRuns.map((r) => ({
      id: r.id,
      budget: r.budget,
      status: r.status,
      createdAt: r.createdAt,
      count: null,
    }));
    return [...local, ...live];
  }, [history, liveRuns]);

  // ---- plan handlers ------------------------------------------------------
  // The action plan is computed server-side by the Fly planning API (/v1/planning/optimize);
  // the result is captured as a history snapshot. There is no client-side computation.
  const startPlan = useCallback(
    async (cfg: PlanConfig) => {
      if (generatingRef.current) return;
      generatingRef.current = true;
      setIssueType(cfg.issueType);
      setBudget(cfg.budget);
      setRegionFilter(cfg.regionFilter);
      setSquadOverride(cfg.squadOverride);
      const req = buildRequest(cfg, costs, observations);
      const id = nextId();
      setPlanError(null);
      setGenerating(true);
      setHistOpen(false);
      try {
        const result = await optimizePlan(req);
        setHistory((h) => [{ id, createdAt: new Date().toISOString(), request: req, result }, ...h]);
        setActiveHistId(id);
        setPreviewing(true);
      } catch (e) {
        setPlanError(e instanceof Error ? e.message : String(e));
      } finally {
        setGenerating(false);
        generatingRef.current = false;
      }
    },
    [costs, observations],
  );

  const onGenerate = () => startPlan({ issueType, budget, regionFilter, squadOverride });

  const closePreview = () => {
    setPreviewing(false);
    setActiveHistId(null);
  };

  const openHistory = (id: string) => {
    setHistOpen(false);
    const local = history.find((h) => h.id === id);
    if (local) {
      setIssueType(local.request.issueType);
      setBudget(local.request.budget);
      setRegionFilter(local.request.regionFilter);
      setSquadOverride(local.request.squadCount ?? null);
      setCosts(local.request.costs);
      setActiveHistId(id);
      setPreviewing(true);
    } else {
      // live run (no local snapshot) — regenerate from current config
      onGenerate();
    }
  };

  // ---- selection ----------------------------------------------------------
  const onSelect = useCallback((id: string) => {
    setSelectedId(id);
    setDetailLoading(true);
    setDetail(null);
    api
      .getObservationDetail(id)
      .then((d) => setDetail(d))
      .catch(() => setDetail(null))
      .finally(() => setDetailLoading(false));
  }, []);

  const onToggleType = (slug: string) =>
    setActiveTypes((at) => ({ ...at, [slug]: !at[slug] }));

  const onToggleRegion = (cve: string) =>
    setRegionFilter((rf) => (rf.includes(cve) ? rf.filter((c) => c !== cve) : [...rf, cve]));

  const onAdjCost = (slug: string, delta: number) =>
    setCosts((cs) => ({ ...cs, [slug]: Math.max(0, (cs[slug] ?? 0) + delta) }));

  const locateSquad = (lat: number, lng: number) =>
    setPanTarget({ lat, lng, n: (panTarget?.n ?? 0) + 1 });

  // Natural-language command — parse via the Fly LLM endpoint and POPULATE the dock for the
  // user to review. It never starts optimization. Returns parser notes (warnings/unresolved
  // terms) for the panel to surface, or null when the draft was applied cleanly.
  const onSubmitPrompt = useCallback(
    async (prompt: string): Promise<string | null> => {
      const draft: PlanDraft = await parseDraft(prompt, types, regions);
      if (draft.issueType && ACTIVE_ISSUE_TYPES.has(draft.issueType)) setIssueType(draft.issueType);
      if (typeof draft.budget === "number" && draft.budget > 0)
        setBudget(Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, draft.budget)));
      if (Array.isArray(draft.regionFilter)) {
        const valid = new Set(regions.map((r) => r.cve));
        setRegionFilter(draft.regionFilter.filter((c) => valid.has(c)));
      }
      if (typeof draft.squadCount === "number") setSquadOverride(draft.squadCount);
      setDockOpen(true);
      const notes = [...draft.unresolvedTerms, ...draft.warnings];
      return notes.length ? notes.join(" · ") : null;
    },
    [types, regions],
  );

  // ---- quick-action chips -------------------------------------------------
  const chips = [
    {
      label: "⚡ Plan de baches",
      run: () => startPlan({ issueType: ISSUE_DEFAULT, budget: DEFAULT_BUDGET, regionFilter: [], squadOverride: null }),
    },
    {
      label: "◎ Plan amplio $4M",
      run: () => startPlan({ issueType: ISSUE_DEFAULT, budget: BUDGET_MAX, regionFilter: [], squadOverride: null }),
    },
    {
      label: "▦ 5 cuadrillas",
      run: () => startPlan({ issueType: ISSUE_DEFAULT, budget: DEFAULT_BUDGET, regionFilter: [], squadOverride: 5 }),
    },
  ];

  // ---- render -------------------------------------------------------------
  if (loadError) {
    return (
      <div style={centerMsg}>
        <div style={{ maxWidth: 420, textAlign: "center" }}>
          <div style={{ fontSize: 15, fontWeight: 700, marginBottom: 8 }}>
            No se pudieron cargar los datos
          </div>
          <div style={{ fontSize: 12.5, color: "#8a94a3", lineHeight: 1.5 }}>{loadError}</div>
          <button onClick={() => signOut()} style={signOutBtn}>
            Cerrar sesión
          </button>
        </div>
      </div>
    );
  }

  if (!loaded) {
    return (
      <div style={centerMsg}>
        <span style={spinner} /> Cargando mapa de CDMX…
      </div>
    );
  }

  return (
    <div style={{ position: "fixed", inset: 0, background: "#eef1f5", color: "#1b2430", overflow: "hidden" }}>
      <MapCanvas
        observations={observations}
        boundary={boundary}
        showPins={showPins}
        showRois={showRois}
        activeTypes={activeTypes}
        plan={activePlan}
        rois={rois}
        selectedId={selectedId}
        accent={accent}
        dockOpen={dockOpen}
        panTarget={panTarget}
        onSelect={onSelect}
      />

      <LayersPanel
        types={types}
        totalObs={observations.length}
        roiCount={rois.length}
        showPins={showPins}
        showRois={showRois}
        activeTypes={activeTypes}
        lastSweepLabel={`${observations.length} obs · en vivo`}
        bottom={layersBottom}
        onTogglePins={() => setShowPins((v) => !v)}
        onToggleRois={() => setShowRois((v) => !v)}
        onToggleType={onToggleType}
        onSignOut={signOut}
      />

      <AgentPanel
        previewing={previewing}
        plan={activePlan}
        typeLabels={typeLabels}
        chips={chips}
        onSubmitPrompt={onSubmitPrompt}
        onClosePreview={closePreview}
        onLocateObs={onSelect}
        onLocateSquad={locateSquad}
      />

      <AnalysisDock
        issueType={issueType}
        budget={budget}
        regions={regions}
        regionFilter={regionFilter}
        squadOverride={squadOverride}
        costs={costs}
        types={types}
        typeLabels={typeLabels}
        pointCount={pointCount}
        previewing={previewing}
        generating={generating}
        planError={planError}
        hasHistory={historyItems.length > 0}
        open={dockOpen}
        onToggleOpen={() => setDockOpen((v) => !v)}
        onSetIssueType={setIssueType}
        onBudget={setBudget}
        onToggleRegion={onToggleRegion}
        onClearRegions={() => setRegionFilter([])}
        onSetSquadOverride={setSquadOverride}
        onAdjCost={onAdjCost}
        onGenerate={onGenerate}
        onToggleHistory={() => setHistOpen((v) => !v)}
        onHeight={setDockHeight}
      />

      {histOpen && (
        <HistoryPopover
          items={historyItems}
          activeId={activeHistId}
          dockOpen
          onOpen={openHistory}
        />
      )}

      {selectedId && (
        <ObservationCard
          detail={detail}
          loading={detailLoading}
          onClose={() => {
            setSelectedId(null);
            setDetail(null);
          }}
        />
      )}
    </div>
  );
}

const centerMsg: React.CSSProperties = {
  position: "fixed",
  inset: 0,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#eef1f5",
  color: "#8a94a3",
  fontSize: 13,
  gap: 11,
};
const spinner: React.CSSProperties = {
  width: 22,
  height: 22,
  border: "3px solid #e3e7ee",
  borderTopColor: "#2f64e6",
  borderRadius: "50%",
  animation: "ppspin .7s linear infinite",
  display: "inline-block",
};
const signOutBtn: React.CSSProperties = {
  marginTop: 16,
  height: 34,
  padding: "0 16px",
  border: "1px solid #e6e9ee",
  background: "#fff",
  borderRadius: 9,
  fontSize: 12,
  fontWeight: 600,
  color: "#5b6675",
  cursor: "pointer",
};
