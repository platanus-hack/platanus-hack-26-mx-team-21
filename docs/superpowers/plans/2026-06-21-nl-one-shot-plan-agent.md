# One-Shot Natural-Language Plan Agent Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A single synchronous endpoint (`POST /v1/agent/plans:run`) that turns a natural-language prompt into a finished plan result by parsing parameters and running the planning engine in one request.

**Architecture:** A backend `PlanAgent` orchestrator composes the existing `DraftParser` (NL → params) and `PlanningEngine` (params → plan). It resolves/clamps the parsed parameters; if it cannot resolve an `issueType` it returns `status: "needs_clarification"` with no plan (no guessing), otherwise it runs the engine and returns the `PlanResult`. The frontend's NL input becomes one-shot, with the dock kept as the manual override path.

**Tech Stack:** Python 3 / FastAPI / Pydantic (v2) on the API; React + TypeScript + Vite on the frontend.

## Global Constraints

- Wire shapes are **camelCase** via Pydantic alias (`_Camel` base = `ConfigDict(alias_generator=to_camel, populate_by_name=True)`); Python internals stay snake_case. Routes use `response_model_by_alias=True`.
- Every route is auth-gated with `_user: User = Depends(require_user)`.
- Provider/orchestration concerns never leak raw upstream bodies — errors map to the existing `ApiError` envelope (the parser already does this; do not catch and re-wrap it).
- Reuse, don't reimplement: `DraftParser`/`AnthropicDraftParser`, `PlanningEngine`/`MockPlanningEngine`, `AnalysisRequest`/`PlanResult`, `IssueTypeChoice`/`RegionChoice` are used as-is.
- Squad bound constant: `MAX_SQUADS` (= 8) from `citycrawl_api.modules.planning.models`. Minimum squad count is `1`.
- Backend tests run through the route with `TestClient` and dependency overrides (the project has **no** async test runner configured — do not write `async def test_...`).
- Frontend verification is `npm run typecheck` then `npm run build` (light-testing working style; no new vitest suite required for wiring).
- UI copy is Spanish.

---

### Task 1: Backend — agent endpoint (`/v1/agent/plans:run`)

Delivers the orchestrator, its models, the config bounds it needs, the router, app registration, and route tests. One cohesive deliverable, tested through the HTTP route.

**Files:**
- Create: `services/api/src/citycrawl_api/modules/agent/__init__.py`
- Create: `services/api/src/citycrawl_api/modules/agent/models.py`
- Create: `services/api/src/citycrawl_api/modules/agent/orchestrator.py`
- Create: `services/api/src/citycrawl_api/routers/agent.py`
- Modify: `services/api/src/citycrawl_api/config.py` (add planning bounds)
- Modify: `services/api/src/citycrawl_api/main.py` (register router)
- Test: `services/api/tests/api/test_agent_plans_run.py`

**Interfaces:**
- Consumes (existing): `DraftParser.parse(DraftParseRequest) -> PlanDraft`; `PlanningEngine.optimize(AnalysisRequest) -> PlanResult`; `IssueTypeChoice{slug,label}`, `RegionChoice{cve,name}` from `modules/llm/models`; `AnalysisPoint`, `AnalysisRequest`, `PlanResult`, `MAX_SQUADS` from `modules/planning/models`; `Settings`/`get_settings` from `config`; `require_user`/`User` from `auth`.
- Produces:
  - `PlanRunRequest{prompt:str, issueTypes:IssueTypeChoice[], regions:RegionChoice[], points:AnalysisPoint[], costs:dict[str,float]}`
  - `ResolvedParams{issueType:str|None, budget:float, regionFilter:list[str], squadCount:int|None}`
  - `PlanRun{resolved:ResolvedParams, plan:PlanResult|None, notes:list[str], status:"ran"|"needs_clarification"}`
  - `PlanAgent(parser, engine, settings)` with `async run(PlanRunRequest) -> PlanRun`
  - Route `POST /v1/agent/plans:run` and DI provider `get_plan_agent`.

- [ ] **Step 1: Add planning bounds to config**

In `services/api/src/citycrawl_api/config.py`, add these fields to the `Settings` class (place them after the Anthropic block, before `operator_api_key`):

```python
    # --- Planning parameter bounds (server & client must agree) ---------------
    default_budget: float = 2_000_000
    budget_min: float = 250_000
    budget_max: float = 4_000_000
```

- [ ] **Step 2: Create the agent package marker**

Create `services/api/src/citycrawl_api/modules/agent/__init__.py`:

```python
"""Agent orchestration: compose the NL draft parser with the planning engine so a single
endpoint turns a natural-language prompt into a finished plan result."""
```

- [ ] **Step 3: Create the agent contract models**

Create `services/api/src/citycrawl_api/modules/agent/models.py`:

```python
"""Wire contract for the one-shot plan agent. Reuses the parser's choice models and the
planning engine's point/result models; adds only the request envelope, the resolved
parameters echo, and the run result. camelCase on the wire via the shared _Camel base."""
from __future__ import annotations
from pydantic import BaseModel, ConfigDict, Field
from pydantic.alias_generators import to_camel

from citycrawl_api.modules.llm.models import IssueTypeChoice, RegionChoice
from citycrawl_api.modules.planning.models import AnalysisPoint, PlanResult


class _Camel(BaseModel):
    model_config = ConfigDict(alias_generator=to_camel, populate_by_name=True)


class PlanRunRequest(_Camel):
    prompt: str
    issue_types: list[IssueTypeChoice] = []
    regions: list[RegionChoice] = []
    points: list[AnalysisPoint] = []
    costs: dict[str, float] = {}


class ResolvedParams(_Camel):
    # issue_type is None only when status == "needs_clarification".
    issue_type: str | None = None
    budget: float
    region_filter: list[str] = Field(default_factory=list)
    squad_count: int | None = None


class PlanRun(_Camel):
    resolved: ResolvedParams
    plan: PlanResult | None = None
    notes: list[str] = Field(default_factory=list)
    status: str  # "ran" | "needs_clarification"
```

- [ ] **Step 4: Create the orchestrator**

Create `services/api/src/citycrawl_api/modules/agent/orchestrator.py`:

```python
"""The one-shot plan agent. Parses the prompt into a draft, resolves and clamps the
parameters against the caller-supplied choices, then runs the planning engine. When no
issue type can be resolved it returns needs_clarification with no plan rather than guessing.
Parser provider errors propagate unchanged as the stable ApiError."""
from __future__ import annotations

from citycrawl_api.config import Settings
from citycrawl_api.modules.agent.models import PlanRun, PlanRunRequest, ResolvedParams
from citycrawl_api.modules.llm.models import DraftParseRequest
from citycrawl_api.modules.llm.protocol import DraftParser
from citycrawl_api.modules.planning.models import MAX_SQUADS, AnalysisRequest
from citycrawl_api.modules.planning.protocol import PlanningEngine


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, value))


class PlanAgent:
    name = "plan-agent"

    def __init__(self, parser: DraftParser, engine: PlanningEngine, settings: Settings) -> None:
        self._parser = parser
        self._engine = engine
        self._settings = settings

    async def run(self, request: PlanRunRequest) -> PlanRun:
        draft = await self._parser.parse(
            DraftParseRequest(
                prompt=request.prompt,
                issue_types=request.issue_types,
                regions=request.regions,
            )
        )
        notes = [*draft.unresolved_terms, *draft.warnings]

        budget = draft.budget if draft.budget is not None else self._settings.default_budget
        budget = _clamp(budget, self._settings.budget_min, self._settings.budget_max)

        squad_count = None
        if draft.squad_count is not None:
            squad_count = int(_clamp(draft.squad_count, 1, MAX_SQUADS))

        valid_regions = {r.cve for r in request.regions}
        region_filter = [c for c in draft.region_filter if c in valid_regions]

        valid_types = {t.slug for t in request.issue_types}
        issue_type = draft.issue_type if draft.issue_type in valid_types else None

        resolved = ResolvedParams(
            issue_type=issue_type,
            budget=budget,
            region_filter=region_filter,
            squad_count=squad_count,
        )

        if issue_type is None:
            return PlanRun(resolved=resolved, plan=None, notes=notes, status="needs_clarification")

        plan = self._engine.optimize(
            AnalysisRequest(
                issue_type=issue_type,
                budget=budget,
                region_filter=region_filter,
                squad_count=squad_count,
                costs=request.costs,
                points=request.points,
            )
        )
        return PlanRun(resolved=resolved, plan=plan, notes=notes, status="ran")
```

- [ ] **Step 5: Create the router**

Create `services/api/src/citycrawl_api/routers/agent.py`:

```python
"""One-shot plan agent route. Composes the Anthropic draft parser with the mock planning
engine behind a single endpoint; the bound engine is reported via X-Planning-Engine. The
agent is provided via a dependency so tests can inject fakes."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Response

from citycrawl_api.auth import User, require_user
from citycrawl_api.config import Settings, get_settings
from citycrawl_api.modules.agent.models import PlanRun, PlanRunRequest
from citycrawl_api.modules.agent.orchestrator import PlanAgent
from citycrawl_api.modules.llm.anthropic import AnthropicDraftParser
from citycrawl_api.modules.planning.mock import MockPlanningEngine

router = APIRouter(prefix="/v1/agent", tags=["agent"])

# Single bound engine, mirroring routers/planning.py. Swap when a real optimizer exists.
_engine = MockPlanningEngine()


def get_plan_agent(settings: Settings = Depends(get_settings)) -> PlanAgent:
    return PlanAgent(AnthropicDraftParser(settings), _engine, settings)


@router.post("/plans:run", response_model=PlanRun, response_model_by_alias=True)
async def run_plan(
    request: PlanRunRequest,
    response: Response,
    agent: PlanAgent = Depends(get_plan_agent),
    _user: User = Depends(require_user),
) -> PlanRun:
    response.headers["X-Planning-Engine"] = _engine.name
    return await agent.run(request)
```

- [ ] **Step 6: Register the router**

In `services/api/src/citycrawl_api/main.py`, add `agent` to the router import on line 17:

```python
from citycrawl_api.routers import agent, datasets, health, llm, observations, planning, video
```

And add this line in the "Explicit router registration" block (after `app.include_router(planning.router)`):

```python
    app.include_router(agent.router)
```

- [ ] **Step 7: Write the failing route tests**

Create `services/api/tests/api/test_agent_plans_run.py`:

```python
"""Agent route tests: auth gate, one-shot run, needs_clarification fallback, parameter
clamping/region filtering, and parser-error propagation. A fake parser + recording fake
engine are injected via dependency override (no live provider, no async test runner)."""
from citycrawl_api.config import get_settings
from citycrawl_api.errors import upstream_unavailable
from citycrawl_api.modules.agent.orchestrator import PlanAgent
from citycrawl_api.modules.llm.models import DraftParseRequest, PlanDraft
from citycrawl_api.modules.planning.models import AnalysisRequest, PlanResult, PlanStats
from citycrawl_api.routers.agent import get_plan_agent

POINTS = [
    {"id": "a", "lat": 19.43, "lng": -99.13, "slug": "pothole", "volume": 100, "districtCve": "005"},
    {"id": "c", "lat": 19.45, "lng": -99.10, "slug": "graffiti", "volume": 200, "districtCve": "006"},
]


def _req(**over):
    base = {
        "prompt": "baches 2 millones",
        "issueTypes": [{"slug": "pothole", "label": "Baches"}],
        "regions": [{"cve": "005", "name": "Cuauhtemoc"}],
        "points": POINTS,
        "costs": {},
    }
    base.update(over)
    return base


class FakeParser:
    name = "fake"

    def __init__(self, draft: PlanDraft) -> None:
        self._draft = draft

    async def parse(self, request: DraftParseRequest) -> PlanDraft:
        return self._draft


class RaisingParser:
    name = "fake-raise"

    async def parse(self, request: DraftParseRequest) -> PlanDraft:
        raise upstream_unavailable("llm_unavailable", "LLM provider is unavailable")


class RecordingEngine:
    name = "rec"

    def __init__(self) -> None:
        self.last: AnalysisRequest | None = None

    def optimize(self, request: AnalysisRequest) -> PlanResult:
        self.last = request
        return PlanResult(
            issue_type=request.issue_type,
            budget=request.budget,
            region_filter=request.region_filter,
            squad_count_used=request.squad_count or 3,
            top_critical=[],
            squads=[],
            stats=PlanStats(spent=0, count=0, squads=0, regions=0, volume=0, budget_pct=0),
        )

    def cluster_priorities(self, points, squad_count=None):
        return []


def _bind(app, parser, engine):
    app.dependency_overrides[get_plan_agent] = lambda: PlanAgent(parser, engine, get_settings())
    return engine


def test_run_requires_auth(raw_client):
    r = raw_client.post("/v1/agent/plans:run", json=_req())
    assert r.status_code == 401


def test_run_one_shot_returns_plan(app, client):
    engine = _bind(app, FakeParser(PlanDraft(issue_type="pothole", budget=2_000_000)), RecordingEngine())
    r = client.post("/v1/agent/plans:run", json=_req())
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ran"
    assert body["resolved"]["issueType"] == "pothole"
    assert body["plan"]["issueType"] == "pothole"
    assert engine.last.budget == 2_000_000


def test_needs_clarification_when_no_issue_type(app, client):
    engine = _bind(app, FakeParser(PlanDraft(issue_type=None, warnings=["sin tipo"])), RecordingEngine())
    r = client.post("/v1/agent/plans:run", json=_req())
    body = r.json()
    assert body["status"] == "needs_clarification"
    assert body["plan"] is None
    assert "sin tipo" in body["notes"]
    assert engine.last is None  # engine not called


def test_unknown_issue_type_is_dropped(app, client):
    # parser returns a slug not in issueTypes -> treated as unresolved
    engine = _bind(app, FakeParser(PlanDraft(issue_type="graffiti")), RecordingEngine())
    r = client.post("/v1/agent/plans:run", json=_req())
    assert r.json()["status"] == "needs_clarification"
    assert engine.last is None


def test_params_are_clamped_and_regions_filtered(app, client):
    draft = PlanDraft(
        issue_type="pothole",
        budget=99_000_000,
        squad_count=99,
        region_filter=["005", "999"],
    )
    engine = _bind(app, FakeParser(draft), RecordingEngine())
    r = client.post("/v1/agent/plans:run", json=_req())
    body = r.json()
    assert body["resolved"]["budget"] == 4_000_000  # budget_max
    assert body["resolved"]["squadCount"] == 8       # MAX_SQUADS
    assert body["resolved"]["regionFilter"] == ["005"]  # "999" dropped
    assert engine.last.budget == 4_000_000
    assert engine.last.squad_count == 8


def test_default_budget_when_absent(app, client):
    engine = _bind(app, FakeParser(PlanDraft(issue_type="pothole", budget=None)), RecordingEngine())
    r = client.post("/v1/agent/plans:run", json=_req())
    assert r.json()["resolved"]["budget"] == 2_000_000  # default_budget
    assert engine.last.budget == 2_000_000


def test_parser_error_propagates(app, client):
    app.dependency_overrides[get_plan_agent] = lambda: PlanAgent(
        RaisingParser(), RecordingEngine(), get_settings()
    )
    r = client.post("/v1/agent/plans:run", json=_req())
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "llm_unavailable"
```

- [ ] **Step 8: Run the tests to verify they fail**

Run: `cd services/api && python -m pytest tests/api/test_agent_plans_run.py -v`
Expected: collection/import errors or failures (the `agent` module/route do not exist yet). If Steps 1–6 are already applied, expect PASS instead — that is acceptable since this single task ships impl + tests together; the meaningful gate is Step 9.

- [ ] **Step 9: Run the full API test suite to verify green**

Run: `cd services/api && python -m pytest -q`
Expected: all tests pass, including the seven new `test_agent_plans_run.py` tests.

- [ ] **Step 10: Commit**

```bash
git add services/api/src/citycrawl_api/modules/agent services/api/src/citycrawl_api/routers/agent.py services/api/src/citycrawl_api/config.py services/api/src/citycrawl_api/main.py services/api/tests/api/test_agent_plans_run.py
git commit -m "feat(api): one-shot NL plan agent endpoint (/v1/agent/plans:run)"
```

---

### Task 2: Frontend — agent client function and types

Additive change: add the `AgentPlanRun`/`ResolvedParams` types and the `runPlanFromPrompt` client call. `parseDraft` stays for now so the build remains green; it is removed in Task 3.

**Files:**
- Modify: `frontend/src/lib/types.ts` (add types after `PlanResult`, ~line 256)
- Modify: `frontend/src/lib/citycrawlApi.ts` (add client function)

**Interfaces:**
- Consumes: backend `PlanRun` contract from Task 1; existing `AnalysisPoint`, `PlanResult`, `TypeCount`, `RegionOption` types.
- Produces: `AgentPlanRun` type and `runPlanFromPrompt(prompt, issueTypes, regions, points, costs, signal?) -> Promise<AgentPlanRun>`.

- [ ] **Step 1: Add the agent response types**

In `frontend/src/lib/types.ts`, immediately after the `PlanResult` interface (ends at line 256, before the `// ---- Real-time observation stream` comment), add:

```typescript
// Resolved parameters the agent actually used. issueType is null only when the agent
// could not resolve a type (status === "needs_clarification").
export interface ResolvedParams {
  issueType: string | null;
  budget: number;
  regionFilter: string[];
  squadCount: number | null;
}

// One-shot response from POST /v1/agent/plans:run. When status === "ran", `plan` is the
// finished PlanResult; when "needs_clarification", `plan` is null and the dock should be
// populated from `resolved` for the user to complete.
export interface AgentPlanRun {
  resolved: ResolvedParams;
  plan: PlanResult | null;
  notes: string[];
  status: "ran" | "needs_clarification";
}
```

- [ ] **Step 2: Add the client function**

In `frontend/src/lib/citycrawlApi.ts`, add `AgentPlanRun` to the type import block (after `AnalysisRequest`) and append this function after `parseDraft`:

```typescript
// One-shot natural-language plan: parse parameters AND run the optimizer in one request.
// Send ALL points across types and the union of districts — the server narrows by the
// resolved issueType and regionFilter.
export function runPlanFromPrompt(
  prompt: string,
  issueTypes: TypeCount[],
  regions: RegionOption[],
  points: AnalysisPoint[],
  costs: Record<string, number>,
  signal?: AbortSignal,
): Promise<AgentPlanRun> {
  return post<AgentPlanRun>(
    "/v1/agent/plans:run",
    {
      prompt,
      issueTypes: issueTypes.map((t) => ({ slug: t.slug, label: t.label })),
      regions: regions.map((r) => ({ cve: r.cve, name: r.name })),
      points,
      costs,
    },
    signal,
  );
}
```

The import line becomes:

```typescript
import type {
  AnalysisPoint,
  AnalysisRequest,
  AgentPlanRun,
  ClusteredPriority,
  PlanDraft,
  PlanResult,
  RegionOption,
  TypeCount,
} from "./types";
```

- [ ] **Step 3: Typecheck**

Run: `cd frontend && npm run typecheck`
Expected: no errors.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/lib/types.ts frontend/src/lib/citycrawlApi.ts
git commit -m "feat(web): add runPlanFromPrompt agent client + AgentPlanRun types"
```

---

### Task 3: Frontend — one-shot NL submit in MapPage

Switch `onSubmitPrompt` from parse-and-populate to one-shot run-and-preview, and remove the now-unused `parseDraft` from the client and the page.

**Files:**
- Modify: `frontend/src/pages/MapPage.tsx` (imports, add `buildAllPoints` + `allRegions`, rewrite `onSubmitPrompt`)
- Modify: `frontend/src/lib/citycrawlApi.ts` (remove `parseDraft` and the now-unused `PlanDraft` import)

**Interfaces:**
- Consumes: `runPlanFromPrompt`, `AgentPlanRun` from Task 2; existing `buildRequest`, `nextId`, `generatingRef`, history/preview state, `ACTIVE_ISSUE_TYPES`, `BUDGET_MIN`, `BUDGET_MAX`.
- Produces: a one-shot `onSubmitPrompt(prompt) => Promise<string | null>` (same signature the `AgentPanel` already consumes).

- [ ] **Step 1: Update MapPage imports**

In `frontend/src/pages/MapPage.tsx`:

Change the client import (line 14) from:

```typescript
import { optimizePlan, parseDraft } from "../lib/citycrawlApi";
```

to:

```typescript
import { optimizePlan, runPlanFromPrompt } from "../lib/citycrawlApi";
```

In the `import type { ... } from "../lib/types"` block (lines 22–34), remove `PlanDraft` and add `AgentPlanRun` (keep the rest):

```typescript
import type {
  AnalysisPoint,
  AnalysisRequest,
  AgentPlanRun,
  Observation,
  ObservationDetail,
  PlanResult,
  RegionOption,
  Roi,
  RunSummary,
  SweepRoute,
  TypeCount,
} from "../lib/types";
```

- [ ] **Step 2: Add `buildAllPoints` helper**

In `frontend/src/pages/MapPage.tsx`, immediately after the `buildPoints` function (ends at line 75), add:

```typescript
// All points across every issue type (no type/region filter) — the agent resolves the
// issueType server-side and the engine narrows from this set.
function buildAllPoints(obs: Observation[]): AnalysisPoint[] {
  return obs
    .filter((o) => o.volume != null)
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
```

- [ ] **Step 3: Add the union `allRegions` memo**

In `frontend/src/pages/MapPage.tsx`, immediately after the existing `regions` memo (ends at line 244), add an unfiltered union of districts:

```typescript
  // Districts across ALL types (union) — the agent needs this to resolve a region the user
  // names before any type is chosen. The per-type `regions` above still drives the dock.
  const allRegions = useMemo<RegionOption[]>(() => {
    const m = new Map<string, RegionOption>();
    for (const o of observations) {
      if (!o.districtCve) continue;
      const cur = m.get(o.districtCve);
      if (cur) cur.count++;
      else m.set(o.districtCve, { cve: o.districtCve, name: o.districtName ?? o.districtCve, count: 1 });
    }
    return [...m.values()].sort((a, b) => b.count - a.count || a.name.localeCompare(b.name));
  }, [observations]);
```

- [ ] **Step 4: Rewrite `onSubmitPrompt` as one-shot**

In `frontend/src/pages/MapPage.tsx`, replace the entire current `onSubmitPrompt` callback (lines 369–388, the block starting with the `// Natural-language command` comment through its closing `[types, regions]);`) with:

```typescript
  // Natural-language command — ONE-SHOT: parse parameters AND run the plan server-side in a
  // single call. On a resolved run, the result is captured as a history snapshot and previewed
  // (same path as startPlan); when the agent needs clarification, the dock is populated from
  // the partial resolved params for the user to complete. Returns a status note for the panel.
  const onSubmitPrompt = useCallback(
    async (prompt: string): Promise<string | null> => {
      if (generatingRef.current) return null;
      generatingRef.current = true;
      setGenerating(true);
      setHistOpen(false);
      try {
        const run: AgentPlanRun = await runPlanFromPrompt(
          prompt,
          types,
          allRegions,
          buildAllPoints(observations),
          costs,
        );
        const r = run.resolved;
        if (r.issueType && ACTIVE_ISSUE_TYPES.has(r.issueType)) setIssueType(r.issueType);
        setBudget(Math.min(BUDGET_MAX, Math.max(BUDGET_MIN, r.budget)));
        const valid = new Set(allRegions.map((x) => x.cve));
        setRegionFilter(r.regionFilter.filter((c) => valid.has(c)));
        setSquadOverride(typeof r.squadCount === "number" ? r.squadCount : null);

        if (run.status === "ran" && run.plan && r.issueType) {
          const req = buildRequest(
            {
              issueType: r.issueType,
              budget: r.budget,
              regionFilter: r.regionFilter,
              squadOverride: r.squadCount ?? null,
            },
            costs,
            observations,
          );
          const id = nextId();
          setHistory((h) => [
            { id, createdAt: new Date().toISOString(), request: req, result: run.plan as PlanResult },
            ...h,
          ]);
          setActiveHistId(id);
          setPreviewing(true);
          return ["Plan generado.", ...run.notes].join(" · ");
        }

        setDockOpen(true);
        return run.notes.length
          ? run.notes.join(" · ")
          : "Especifica el tipo de incidencia y genera el plan.";
      } finally {
        setGenerating(false);
        generatingRef.current = false;
      }
    },
    [types, allRegions, observations, costs],
  );
```

(Errors from `runPlanFromPrompt` propagate to the `AgentPanel`'s own `.catch`, which renders them — matching the prior behavior.)

- [ ] **Step 5: Remove `parseDraft` from the client**

In `frontend/src/lib/citycrawlApi.ts`, delete the entire `parseDraft` function (the `// Natural-language draft parsing` comment through its closing `}`), and remove `PlanDraft` from the `import type { ... } from "./types"` block.

- [ ] **Step 6: Typecheck and build**

Run: `cd frontend && npm run typecheck && npm run build`
Expected: no type errors (in particular, no "unused `PlanDraft`/`parseDraft`" or missing-symbol errors) and a successful build.

- [ ] **Step 7: Commit**

```bash
git add frontend/src/pages/MapPage.tsx frontend/src/lib/citycrawlApi.ts
git commit -m "feat(web): one-shot natural-language plan run in MapPage"
```

---

### Task 4: Remove the dead `drafts:parse` route

The standalone draft-parse route is no longer called by the frontend (the agent reuses the parser internally). Remove the route and its test; keep the `modules/llm` parser code.

**Files:**
- Modify: `services/api/src/citycrawl_api/routers/llm.py` (remove route + provider)
- Delete: `services/api/tests/api/test_llm_api.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: removal only. `AnthropicDraftParser`/`DraftParser`/`PlanDraft` remain importable (used by the agent).

- [ ] **Step 1: Delete the route**

Delete the file `services/api/src/citycrawl_api/routers/llm.py`, then remove its registration from `services/api/src/citycrawl_api/main.py`:
- In the router import (line 17), drop `llm`: `from citycrawl_api.routers import agent, datasets, health, observations, planning, video`
- Remove the line `app.include_router(llm.router)`.

- [ ] **Step 2: Delete the obsolete route test**

```bash
git rm services/api/tests/api/test_llm_api.py
```

- [ ] **Step 3: Run the full API suite**

Run: `cd services/api && python -m pytest -q`
Expected: all tests pass; no import error referencing `routers.llm` or `get_draft_parser`.

- [ ] **Step 4: Confirm no lingering references**

Run: `cd services/api && grep -rn "drafts:parse\|routers.llm\|routers import.*\bllm\b\|get_draft_parser" src tests`
Expected: no output (the parser module under `modules/llm` is fine; this checks only the route).

- [ ] **Step 5: Commit**

```bash
git add -A services/api
git commit -m "refactor(api): remove dead /v1/llm/drafts:parse route (superseded by agent)"
```

---

## Self-Review

**Spec coverage:**
- New `PlanAgent` orchestrator composing `DraftParser` + `PlanningEngine` → Task 1 (Steps 3–4).
- `POST /v1/agent/plans:run` with `PlanRunRequest`/`PlanRun`/`ResolvedParams` → Task 1 (Steps 3, 5, 6).
- Parameter resolution: budget default + clamp, squad clamp, region filter, issueType no-guess → orchestrator (Step 4) + tests (Step 7).
- `needs_clarification` graceful fallback → orchestrator + `test_needs_clarification_when_no_issue_type` / `test_unknown_issue_type_is_dropped`.
- Config bounds shared server/client → Task 1 Step 1; frontend already owns matching `BUDGET_MIN/MAX/DEFAULT_BUDGET`.
- Client sends all points + union regions → Task 3 Steps 2–4.
- Frontend one-shot `onSubmitPrompt` → Task 3 Step 4; client fn + types → Task 2.
- Remove dead `drafts:parse` route, keep parser module → Task 4.
- Error propagation as stable ApiError → `test_parser_error_propagates`.
- Light testing / Spanish UI / camelCase wire → Global Constraints, honored throughout.

**Placeholder scan:** No TBD/TODO/"handle edge cases"/"similar to" — every code step contains full content.

**Type consistency:** `PlanRunRequest`/`ResolvedParams`/`PlanRun` field names and `status` literals match between backend models, the orchestrator, the tests, and the frontend `AgentPlanRun`/`ResolvedParams`. Frontend response type is named `AgentPlanRun` to avoid colliding with the existing local `PlanRun` history interface in `MapPage.tsx`. `runPlanFromPrompt` signature is identical in its definition (Task 2) and call site (Task 3). `buildAllPoints`/`allRegions` are defined before use.
