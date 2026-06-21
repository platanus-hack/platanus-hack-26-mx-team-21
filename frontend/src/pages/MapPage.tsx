import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { MapCanvas } from "../components/MapCanvas";
import { LayersPanel } from "../components/LayersPanel";
import { AgentPanel } from "../components/AgentPanel";
import { AnalysisDock } from "../components/AnalysisDock";
import { HistoryPopover, type PlanHistoryItem } from "../components/HistoryPopover";
import { ObservationCard } from "../components/ObservationCard";
import { ToastStack } from "../components/ToastStack";
import { Button } from "@/components/ui/button";
import { Panel } from "@/components/ui/panel";
import { Spinner } from "@/components/ui/spinner";
import { useAuth } from "../lib/auth";
import * as api from "../lib/api";
import { useObservationStream, type Toast } from "../lib/observationStream";
import { fetchObjectUrl, THUMBNAIL_BUCKET } from "../lib/objects";
import { optimizePlan, chatDraft } from "../lib/citycrawlApi";
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
  ChatMessage,
  DimensionCount,
  DraftChatResponse,
  Observation,
  ObservationDetail,
  PlanDraft,
  PlanResult,
  RegionOption,
  Roi,
  RunSummary,
  SweepRoute,
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
  const { session, signOut } = useAuth();

  // ---- live data ----------------------------------------------------------
  const [loaded, setLoaded] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [accent, setAccent] = useState("#2f64e6");
  const [tenantId, setTenantId] = useState<string | null>(null);
  const [types, setTypes] = useState<TypeCount[]>([]);
  const [observations, setObservations] = useState<Observation[]>([]);
  // blob: URLs for citizen-report thumbnails (WhatsApp photos), keyed by observation id.
  // Streamed from the R2 broker once observations load; revoked on unmount.
  const [thumbUrls, setThumbUrls] = useState<Record<string, string>>({});
  const [dimensionCounts, setDimensionCounts] = useState<DimensionCount[]>([]);
  const roiCache = useRef<Map<string, Roi[]>>(new Map());
  const [roiVersion, setRoiVersion] = useState(0); // bump after a lazy ROI fetch resolves
  const [boundary, setBoundary] = useState<unknown | null>(null);
  const [liveRuns, setLiveRuns] = useState<RunSummary[]>([]);

  // ---- layer toggles ------------------------------------------------------
  const [showPins, setShowPins] = useState(true);
  const [riskMaster, setRiskMaster] = useState(true);
  const [riskExpanded, setRiskExpanded] = useState(true);
  const [activeDimensions, setActiveDimensions] = useState<Record<string, boolean>>({});
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
  const [cardHeight, setCardHeight] = useState(0);

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

  // ---- sweep ("recorrido") view -------------------------------------------
  const [sweepRoute, setSweepRoute] = useState<SweepRoute | null>(null);
  const [sweepLoading, setSweepLoading] = useState(false);

  // ---- live observation stream -------------------------------------------
  const [toasts, setToasts] = useState<Toast[]>([]);
  const [pulseIds, setPulseIds] = useState<Set<string>>(() => new Set());
  const [fitTarget, setFitTarget] = useState<{ points: { lat: number; lng: number }[]; n: number } | null>(null);
  const fitSeq = useRef(0);
  const panSeq = useRef(0); // bumps panTarget.n so the fly-to re-triggers per "Ver"

  // The layers panel must clear whatever sits bottom-left: the dock/launcher
  // (always) and the observation card (only while one is open). Both are
  // anchored at bottom:18, so the taller wins.
  const dockClearance = 18 + (dockOpen ? dockHeight : LAUNCHER_H) + PANEL_GAP;
  const cardClearance = selectedId && cardHeight ? 18 + cardHeight + PANEL_GAP : 0;
  const layersBottom = Math.max(dockClearance, cardClearance);

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
        const [tenant, tc, obs, dc, bnd, live] = await Promise.all([
          api.getActiveTenant(),
          api.getTypeCounts(),
          api.getObservations(),
          api.getRoiDimensionCounts(),
          api.getBoundary(),
          api.listRuns(),
        ]);
        if (!alive) return;
        if (tenant?.accent) {
          setAccent(tenant.accent);
          document.documentElement.style.setProperty("--acc", tenant.accent);
        }
        if (tenant?.id) setTenantId(tenant.id);
        setTypes(tc);
        setActiveTypes(Object.fromEntries(tc.map((t) => [t.slug, true])));
        setObservations(obs);
        setDimensionCounts(dc);
        // Enable every dimension that has data; pre-fetch their ROIs so the layer
        // paints on first load (later toggles fetch lazily — see ensureDimLoaded).
        const enabled = Object.fromEntries(dc.filter((d) => d.count > 0).map((d) => [d.dimension, true]));
        setActiveDimensions(enabled);
        const dims = Object.keys(enabled);
        const fetched = await Promise.all(dims.map((d) => api.getRois([d])));
        if (!alive) return;
        dims.forEach((d, i) => roiCache.current.set(d, fetched[i]));
        setRoiVersion((v) => v + 1);
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

  // ---- citizen-report thumbnails ------------------------------------------
  // Each observation with a thumb_path (today: WhatsApp citizen reports) gets its photo
  // streamed from the broker and shown as the map marker. Fetched once per id; the loaded
  // set is tracked in a ref so this effect never re-fetches, and all blob: URLs are revoked
  // when the page unmounts to avoid leaks.
  const loadedThumbs = useRef<Set<string>>(new Set());
  const thumbUrlsRef = useRef<Record<string, string>>({});
  thumbUrlsRef.current = thumbUrls;
  useEffect(() => {
    let alive = true;
    (async () => {
      for (const o of observations) {
        if (!o.thumbPath || loadedThumbs.current.has(o.id)) continue;
        loadedThumbs.current.add(o.id);
        const url = await fetchObjectUrl(THUMBNAIL_BUCKET, o.thumbPath);
        if (!alive) {
          if (url) URL.revokeObjectURL(url);
          return;
        }
        if (url) setThumbUrls((m) => ({ ...m, [o.id]: url }));
      }
    })();
    return () => {
      alive = false;
    };
  }, [observations]);
  // Revoke every loaded thumbnail URL when the page unmounts.
  useEffect(
    () => () => {
      for (const url of Object.values(thumbUrlsRef.current)) URL.revokeObjectURL(url);
    },
    [],
  );

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

  // Risk zones to draw: union of the toggled-on dimensions' cached ROIs (empty when
  // the master is off). roiVersion forces recompute after a lazy fetch fills the cache.
  const roisToRender = useMemo<Roi[]>(() => {
    if (!riskMaster) return [];
    const out: Roi[] = [];
    for (const [dim, on] of Object.entries(activeDimensions)) {
      if (!on) continue;
      const cached = roiCache.current.get(dim);
      if (cached) out.push(...cached);
    }
    return out;
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [riskMaster, activeDimensions, roiVersion]);

  const totalRoiCount = useMemo(
    () => dimensionCounts.reduce((s, d) => s + d.count, 0),
    [dimensionCounts],
  );

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

  // ---- live observation stream wiring ------------------------------------
  // Authoritative refetch folded into the map state; debounced upstream by the hook.
  const refetchObservations = useCallback(() => {
    api.getObservations().then(setObservations).catch(() => {});
  }, []);

  const pushToast = useCallback((t: Toast) => {
    setToasts((cur) => [t, ...cur].slice(0, 4)); // cap the stack
    // Pulse the new pin(s) for ~3s.
    const ids =
      t.target.type === "point"
        ? [t.target.observationId]
        : []; // batch ids aren't in the lean payload target; pulse resolves on refetch below
    if (ids.length) {
      setPulseIds((cur) => new Set([...cur, ...ids]));
      setTimeout(() => {
        setPulseIds((cur) => {
          const next = new Set(cur);
          for (const id of ids) next.delete(id);
          return next;
        });
      }, 3000);
    }
  }, []);

  useObservationStream({
    tenantId,
    accessToken: session?.access_token ?? null,
    labelFor: (slug) => typeLabels[slug] ?? slug,
    onRefetch: refetchObservations,
    onToast: pushToast,
  });

  const onToastAction = useCallback(
    (t: Toast) => {
      setToasts((cur) => cur.filter((x) => x.id !== t.id));
      if (t.target.type === "point") {
        onSelect(t.target.observationId);
        panSeq.current += 1;
        setPanTarget({ lat: t.target.lat, lng: t.target.lng, n: panSeq.current });
      } else {
        fitSeq.current += 1;
        setFitTarget({ points: t.target.points, n: fitSeq.current });
      }
    },
    [onSelect],
  );

  const dismissToast = useCallback((id: string) => {
    setToasts((cur) => cur.filter((x) => x.id !== id));
  }, []);

  // Resolve and show the inspection sweep behind an observation; fetch is fire-and-
  // forget with a loading flag so the banner can render immediately.
  const onViewSweep = useCallback((obsId: string) => {
    setSweepLoading(true);
    api
      .getSweepRoute(obsId)
      .then((sr) => setSweepRoute(sr))
      .catch(() => setSweepRoute(null))
      .finally(() => setSweepLoading(false));
  }, []);

  // Lazy per-dimension ROI fetch: a dimension's polygons load the first time it is
  // switched on, then stay cached. Never ships every dimension's geometry up front.
  const ensureDimLoaded = useCallback(async (dim: string) => {
    if (roiCache.current.has(dim)) return;
    const r = await api.getRois([dim]);
    roiCache.current.set(dim, r);
    setRoiVersion((v) => v + 1);
  }, []);

  const onToggleDimension = (dim: string) => {
    const turningOn = !activeDimensions[dim];
    setActiveDimensions((ad) => ({ ...ad, [dim]: !ad[dim] }));
    if (turningOn) void ensureDimLoaded(dim);
  };

  const onToggleRiskMaster = () => {
    const turningOn = !riskMaster;
    setRiskMaster(turningOn);
    if (turningOn) {
      for (const d of Object.keys(activeDimensions)) {
        if (activeDimensions[d]) void ensureDimLoaded(d);
      }
    }
  };

  const onToggleType = (slug: string) =>
    setActiveTypes((at) => ({ ...at, [slug]: !at[slug] }));

  const onToggleRegion = (cve: string) =>
    setRegionFilter((rf) => (rf.includes(cve) ? rf.filter((c) => c !== cve) : [...rf, cve]));

  const onAdjCost = (slug: string, delta: number) =>
    setCosts((cs) => ({ ...cs, [slug]: Math.max(0, (cs[slug] ?? 0) + delta) }));

  const locateSquad = (lat: number, lng: number) =>
    setPanTarget({ lat, lng, n: (panTarget?.n ?? 0) + 1 });

  // The draft accumulated across the agent conversation — sent back each turn as context so
  // the model only changes what the user asks for.
  const draftRef = useRef<PlanDraft | null>(null);

  // Conversational agent turn — sends the full message history plus the draft so far and
  // applies the merged draft to the dock. When the model reports generate=true (the user
  // asked to run it) and a runnable issue type is set, it also triggers the plan and opens
  // the preview. Returns the assistant's Spanish reply.
  const onChat = useCallback(
    async (messages: ChatMessage[]): Promise<string> => {
      const res: DraftChatResponse = await chatDraft(messages, draftRef.current, types, regions);
      const draft = res.draft;
      draftRef.current = draft;

      // Resolve the draft into a concrete config, falling back to current dock state for any
      // field this turn didn't set. Held as locals so a generate turn can run the plan now
      // without waiting for the setState calls below to flush.
      const nextIssue =
        draft.issueType && ACTIVE_ISSUE_TYPES.has(draft.issueType) ? draft.issueType : issueType;
      const nextBudget =
        typeof draft.budget === "number" && draft.budget > 0
          ? Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, draft.budget))
          : budget;
      const validCves = new Set(regions.map((r) => r.cve));
      const nextRegions = Array.isArray(draft.regionFilter)
        ? draft.regionFilter.filter((c) => validCves.has(c))
        : regionFilter;
      const nextSquad = typeof draft.squadCount === "number" ? draft.squadCount : squadOverride;

      setIssueType(nextIssue);
      setBudget(nextBudget);
      setRegionFilter(nextRegions);
      setSquadOverride(nextSquad);
      setDockOpen(true);

      // Trigger optimization only on an explicit generate intent with a runnable issue type;
      // fire-and-forget so the reply bubble renders before the preview takes over.
      if (res.generate && draft.issueType && ACTIVE_ISSUE_TYPES.has(draft.issueType)) {
        void startPlan({
          issueType: nextIssue,
          budget: nextBudget,
          regionFilter: nextRegions,
          squadOverride: nextSquad,
        });
      }
      return res.reply;
    },
    [types, regions, issueType, budget, regionFilter, squadOverride, startPlan],
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
      <div className={CENTER_MSG}>
        <div className="max-w-[420px] text-center">
          <div className="mb-2 text-[15px] font-bold">No se pudieron cargar los datos</div>
          <div className="text-[12.5px] leading-[1.5] text-muted-foreground">{loadError}</div>
          <Button
            variant="outline"
            onClick={() => signOut()}
            className="mt-4 h-[34px] rounded-[9px] px-4 text-[12px] font-semibold text-[var(--ink-2)]"
          >
            Cerrar sesión
          </Button>
        </div>
      </div>
    );
  }

  if (!loaded) {
    return (
      <div className={CENTER_MSG}>
        <Spinner size={22} /> Cargando mapa de CDMX…
      </div>
    );
  }

  return (
    <div className="fixed inset-0 overflow-hidden bg-background text-foreground">
      <MapCanvas
        observations={observations}
        thumbUrls={thumbUrls}
        boundary={boundary}
        showPins={showPins}
        showRois={riskMaster}
        activeTypes={activeTypes}
        regionFilter={regionFilter}
        plan={activePlan}
        rois={roisToRender}
        highlightSweep={sweepRoute?.sweep ?? null}
        selectedId={selectedId}
        accent={accent}
        panTarget={panTarget}
        pulseIds={pulseIds}
        fitTarget={fitTarget}
        onSelect={onSelect}
      />

      {(sweepRoute || sweepLoading) && (
        <SweepBanner
          route={sweepRoute}
          loading={sweepLoading}
          accent={accent}
          onClose={() => {
            setSweepRoute(null);
            setSweepLoading(false);
          }}
        />
      )}

      <LayersPanel
        types={types}
        totalObs={observations.length}
        showPins={showPins}
        riskMaster={riskMaster}
        riskExpanded={riskExpanded}
        dimensionCounts={dimensionCounts}
        activeDimensions={activeDimensions}
        totalRoiCount={totalRoiCount}
        activeTypes={activeTypes}
        lastSweepLabel={`${observations.length} obs · en vivo`}
        bottom={layersBottom}
        onTogglePins={() => setShowPins((v) => !v)}
        onToggleRiskMaster={onToggleRiskMaster}
        onToggleRiskExpanded={() => setRiskExpanded((v) => !v)}
        onToggleDimension={onToggleDimension}
        onToggleType={onToggleType}
        onSignOut={signOut}
      />

      <AgentPanel
        previewing={previewing}
        plan={activePlan}
        typeLabels={typeLabels}
        chips={chips}
        onChat={onChat}
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
          onViewSweep={onViewSweep}
          onHeight={setCardHeight}
          onClose={() => {
            setSelectedId(null);
            setDetail(null);
          }}
        />
      )}

      <ToastStack toasts={toasts} onAction={onToastAction} onDismiss={dismissToast} />
    </div>
  );
}

const CENTER_MSG =
  "fixed inset-0 flex items-center justify-center gap-[11px] bg-background text-[13px] text-muted-foreground";

// Formats a sweep's [start, end] window. Same-day windows collapse to one date with a
// time range; multi-day windows show both dates. Spanish, CDMX time.
const DATE_FMT = new Intl.DateTimeFormat("es-MX", { day: "numeric", month: "short", timeZone: "America/Mexico_City" });
const TIME_FMT = new Intl.DateTimeFormat("es-MX", { hour: "2-digit", minute: "2-digit", timeZone: "America/Mexico_City" });

function sweepWindow(startIso: string, endIso: string): string {
  const s = new Date(startIso);
  const e = new Date(endIso);
  if (Number.isNaN(s.getTime()) || Number.isNaN(e.getTime())) return "—";
  const sameDay = DATE_FMT.format(s) === DATE_FMT.format(e);
  return sameDay
    ? `${DATE_FMT.format(s)} · ${TIME_FMT.format(s)}–${TIME_FMT.format(e)}`
    : `${DATE_FMT.format(s)} – ${DATE_FMT.format(e)}`;
}

// Top-center banner shown while the sweep ("recorrido") coverage overlay is active.
function SweepBanner({
  route,
  loading,
  accent,
  onClose,
}: {
  route: SweepRoute | null;
  loading: boolean;
  accent: string;
  onClose: () => void;
}) {
  return (
    <Panel className="absolute left-1/2 top-[18px] z-[540] flex -translate-x-1/2 items-center gap-3 py-2 pl-3 pr-2">
      <span className="size-2.5 shrink-0 rounded-full" style={{ background: accent }} />
      {loading || !route ? (
        <div className="flex items-center gap-2 text-[12px] text-muted-foreground">
          <Spinner size={14} /> Cargando recorrido…
        </div>
      ) : (
        <div className="flex items-center gap-2.5 text-[12px]">
          <span className="font-mono text-[12px] font-bold tracking-[-0.2px]">{route.sweep}</span>
          <span className="text-[var(--line-strong)]">·</span>
          <span className="text-muted-foreground">{route.obsCount.toLocaleString("es-MX")} obs</span>
          <span className="text-[var(--line-strong)]">·</span>
          <span className="text-muted-foreground">{route.areaKm2.toFixed(1)} km²</span>
          <span className="text-[var(--line-strong)]">·</span>
          <span className="text-muted-foreground">{sweepWindow(route.startedAt, route.endedAt)}</span>
        </div>
      )}
      <Button
        variant="secondary"
        size="icon-xs"
        onClick={onClose}
        title="Salir del recorrido"
        className="size-[25px] shrink-0 rounded-[7px] bg-[#f1f4f8] text-base leading-none text-[var(--ink-2)]"
      >
        ×
      </Button>
    </Panel>
  );
}
