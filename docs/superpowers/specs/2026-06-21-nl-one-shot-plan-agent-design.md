# One-Shot Natural-Language Plan Agent — Design

**Date:** 2026-06-21
**Status:** Approved — ready for implementation plan
**Branch context:** reimplements the "agents structured analysis" so a natural-language
prompt parses parameters *and* runs the plan in a single action.

## Problem

Today the natural-language path and plan execution are two disconnected steps:

1. `POST /v1/llm/drafts:parse` — Claude parses a Spanish/English prompt into an editable
   `PlanDraft` (`issueType`, `budget`, `regionFilter`, `squadCount`) and the frontend only
   uses it to *populate the dock*. It never runs anything.
2. `POST /v1/planning/optimize` — a separate "Generar plan" button click runs the
   `MockPlanningEngine` and returns a `PlanResult`.

The user wants a one-shot experience: type a prompt → parameters are extracted → the plan
runs → a result comes back, in a single synchronous request. The dock remains as the
manual override/refine path.

## Goal & non-goals

**Goal:** One synchronous backend endpoint that turns a natural-language prompt into a run
plan result, reusing the existing parser and planning engine.

**Non-goals (YAGNI):**
- No async jobs / worker / `analysis_runs` persistence. Execution is synchronous.
  (The eventual async CF-worker architecture is out of scope for this change.)
- No expansion of the parameter set beyond the existing four
  (`issueType`, `budget`, `regionFilter`, `squadCount`). The schema is structured so a
  fifth field is a localized change later.
- No cost-override inference (unchanged from the current parser contract).
- No conversational multi-turn / tool-chaining agent. Single parse → single run.

## Architecture

Approach: a backend **agent orchestrator** that composes the two existing protocols.

```
POST /v1/agent/plans:run
        │
        ▼
   routers/agent.py  ──depends──▶ PlanAgent (modules/agent/orchestrator.py)
                                     │   ├─ DraftParser  (existing, reused)
                                     │   └─ PlanningEngine (existing, reused)
                                     ▼
                                  PlanRun { resolved, plan, notes, status }
```

- **New module `services/api/src/citycrawl_api/modules/agent/`**
  - `orchestrator.py` — `PlanAgent`, composes an injected `DraftParser` and
    `PlanningEngine`. Single method `async run(request: PlanRunRequest) -> PlanRun`.
  - `models.py` — Pydantic models for the agent contract (camelCase wire aliases, matching
    the existing `_Camel` convention).
- **New router `routers/agent.py`** — `POST /v1/agent/plans:run`, guarded by `require_user`,
  reports the engine via the existing `X-Planning-Engine` response header. Wires the agent
  with the same dependency-injection style as `routers/llm.py` and `routers/planning.py`
  (so tests can inject fakes).
- **Reused unchanged:** `DraftParser` / `AnthropicDraftParser`,
  `PlanningEngine` / `MockPlanningEngine`, and the `AnalysisRequest` / `PlanResult` models.
  The agent only wires them together.
- **Removed:** the now-dead `POST /v1/llm/drafts:parse` route (the frontend no longer calls
  it). The `modules/llm` parser code stays — it is the agent's parsing primitive.

## Contract

### Request — `PlanRunRequest`

| field        | type                  | notes                                              |
|--------------|-----------------------|----------------------------------------------------|
| `prompt`     | `str`                 | the natural-language command                        |
| `issueTypes` | `IssueTypeChoice[]`   | `{slug,label}` — for the parser to resolve names    |
| `regions`    | `RegionChoice[]`      | `{cve,name}` — union of districts (not type-filtered)|
| `points`     | `AnalysisPoint[]`     | **all** observation points across types             |
| `costs`      | `dict[str,float]`     | cost-basis overrides, passed through to the engine  |

The client sends *all* points and the *union* of districts because the resolved
`issueType` is decided server-side; the engine narrows by `slug` and `regionFilter`.

### Response — `PlanRun`

| field      | type                            | notes                                          |
|------------|---------------------------------|------------------------------------------------|
| `resolved` | `ResolvedParams`                | `{issueType, budget, regionFilter, squadCount}`|
| `plan`     | `PlanResult \| null`            | present iff `status == "ran"`                   |
| `notes`    | `string[]`                      | parser `unresolvedTerms` + `warnings`          |
| `status`   | `"ran" \| "needs_clarification"`| see resolution rules                            |

`ResolvedParams.issueType` may be `null` when `status == "needs_clarification"`.

## Parameter resolution (in `PlanAgent.run`)

The parser returns nullable scalars; the agent resolves them into a runnable
`AnalysisRequest`:

- **budget** — if null, use configured `DEFAULT_BUDGET`; clamp to `[BUDGET_MIN, BUDGET_MAX]`.
- **squadCount** — if null, leave null (engine applies `DEFAULT_SQUADS`); else clamp to
  `[1, MAX_SQUADS]`.
- **regionFilter** — keep only codes present in the supplied `regions[]`; drop unknowns
  (already surfaced by the parser as `unresolvedTerms`).
- **issueType** — if resolved **and** active → run. If null/unresolved → **do not guess**:
  return `status: "needs_clarification"`, `plan: null`, `resolved` carrying whatever was
  parsed, plus `notes`. This degrades gracefully to today's dock-populate behavior.
- **points** — the engine filters by `slug == resolved.issueType` and `regionFilter`
  (the mock already does this). No client pre-filtering by type.

On a resolved `issueType`, the agent builds the `AnalysisRequest` and calls
`engine.optimize(...)`, returning `status: "ran"` with the `PlanResult`.

### Configuration

`DEFAULT_BUDGET`, `BUDGET_MIN`, `BUDGET_MAX` move into the API `Settings`/config so the
server and the frontend agree on the same bounds (the frontend currently owns these as
`BUDGET_MIN`/`BUDGET_MAX`/`DEFAULT_BUDGET`). `DEFAULT_SQUADS` / `MAX_SQUADS` already live in
`modules/planning/models.py` and are reused.

## Error handling

- Provider errors from the parser (rate limit, timeout, unavailable, invalid output) map to
  the existing stable `502/503` `ApiError`s — unchanged, raw provider bodies never leak.
- Invalid structured output is rejected by `PlanDraft.model_validate` (unchanged) before any
  plan runs.
- A resolved-but-unrunnable request (no `issueType`) is **not** an error: it returns
  `200` with `status: "needs_clarification"`.

## Frontend changes

- **`frontend/src/lib/citycrawlApi.ts`** — add
  `runPlanFromPrompt(prompt, types, regions, points, costs, signal?) -> PlanRun`.
  Keep `optimizePlan` for the manual dock "Generar plan" button. Remove `parseDraft` (its
  route is gone).
- **`frontend/src/pages/MapPage.tsx` — `onSubmitPrompt`** becomes one-shot:
  - set `generating`, call `runPlanFromPrompt` with all points + union regions + costs.
  - `status: "ran"` → set dock state to `resolved` params, push `PlanResult` into history,
    open the preview (same tail as `startPlan`).
  - `status: "needs_clarification"` → populate dock with partial `resolved`, surface
    `notes` (today's behavior).
  - return joined `notes` for the panel to display, as now.
- The dock + manual Generate button + quick-action chips are unchanged (override/refine path).
- **`frontend/src/lib/types.ts`** — add `PlanRun` / `ResolvedParams` types mirroring the
  Pydantic models.

## Testing (light, matching the existing fake-injection pattern)

Backend, with injected fake `DraftParser` + fake `PlanningEngine`:
- happy path: NL prompt resolves an `issueType` → `status: "ran"`, `plan` present, engine
  received the resolved/clamped params.
- unresolved `issueType` → `status: "needs_clarification"`, `plan: null`, `notes` populated,
  engine **not** called.
- budget/squad clamping: out-of-range parsed values are clamped before the engine call.
- parser provider error → propagates as the stable `ApiError` (e.g. `502`/`503`).

## Files touched

New:
- `services/api/src/citycrawl_api/modules/agent/__init__.py`
- `services/api/src/citycrawl_api/modules/agent/orchestrator.py`
- `services/api/src/citycrawl_api/modules/agent/models.py`
- `services/api/src/citycrawl_api/routers/agent.py`
- `services/api/tests/api/test_agent_plans_run.py`

Modified:
- `services/api/src/citycrawl_api/config.py` (budget bounds)
- API app router registration (mount `/v1/agent`)
- `services/api/src/citycrawl_api/routers/llm.py` (remove `drafts:parse` route)
- `frontend/src/lib/citycrawlApi.ts`
- `frontend/src/lib/types.ts`
- `frontend/src/pages/MapPage.tsx`
