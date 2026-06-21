# Design: Repo Flatten + Isolated In-App Design System (shadcn + Tailwind v4)

**Date:** 2026-06-20
**Status:** Approved (design) — pending implementation plan
**Author:** brainstorming session
**Branch:** `feat/city-priority-map-app`

## Problem

The `frontend` (Vialia / City Priority Map) was built during a "fast build" that
**deliberately deviated** from the agreed plan
(`docs/superpowers/plans/2026-06-20-city-priority-map-application.md`, lines 8/21/158),
which specified **shadcn/ui + Tailwind**. Instead the app shipped as ~2,300 lines of
inline `style={{}}` objects across 8 component/page files, with hardcoded hex colors
(`#2f64e6`, `#1b2430`, `#eef1f5`, …) repeated everywhere and no shared design vocabulary.
There is no Tailwind, no shadcn, no `components.json`. The single global stylesheet
(`src/index.css`, 104 lines) only holds CSS vars, scrollbar styling, the range-input
appearance, and keyframes.

Two structural problems compound this:

1. **No isolated design system.** Styling is baked into feature components, so there is
   no reusable, consistent set of primitives. Changing the look means editing inline
   styles in many files.
2. **Inconsistent repo nesting.** The frontend lives under `apps/web/` while the
   Cloudflare/Python services live at `services/{broker,external-data,worker}` (i.e.
   "outside apps"). For effectively one app + a few services, the `apps/web` nesting adds
   depth without benefit.

## Goals

1. **Flatten the repo** so the frontend is a top-level `frontend/` folder, a sibling of
   `services/`, `packages/`, `supabase/`, `design/`, `docs/`. Remove the empty `apps/`.
2. **Extract an isolated, in-app design system** built on **Tailwind v4 + shadcn/ui**,
   themed to match the reference design exactly. Tokens become the single source of truth;
   shadcn primitives inherit them.
3. **Prove fidelity** with a showcase page + screenshot comparison against the reference,
   without touching any feature component.

## Non-Goals (explicitly out of scope for this plan)

- **No rewriting of feature components.** `MapPage`, `MapCanvas`, `AnalysisDock`,
  `AgentPanel`, `ObservationCard`, `LayersPanel`, `HistoryPopover`, `LoginPage` keep their
  current inline styles. Migrating them onto the new primitives is a **separate follow-up**.
- No new features, no data/schema changes, no router/state changes.
- No CI changes beyond what the build/typecheck already does.

## Decisions (confirmed)

| Decision | Choice | Rationale |
|---|---|---|
| Isolation level | **In-app** (`frontend/src/components/ui` + `frontend/src/design-system`) | Standard shadcn layout; isolated by folder + token boundary; fastest for a single app. Rejected: separate `packages/ui` workspace package (heavier, only one consumer). |
| Repo layout | **Flatten** `apps/web` → `frontend/` | Removes pointless nesting; sibling of `services/`. |
| Tailwind version | **v4 (CSS-first)** | shadcn's current default; tokens in CSS via `@theme`, no `tailwind.config.ts` to drift. Rejected: v3 JS config. |
| Migration of features | **Deferred** | User instruction: extract the system, don't yet modify the application. |

## Part 1 — Repo flatten

```
BEFORE                          AFTER
apps/web/         →             frontend/          ← Vite + React SPA
services/{broker,…}             services/{broker,…}   (unchanged)
packages/db-types               packages/db-types     (unchanged)
supabase/ design/ docs/         supabase/ design/ docs/
```

Moves:
- `apps/web/*` → `frontend/` (move all contents, including `src/`, `package.json`,
  `vite.config.ts`, `index.html`, `tsconfig.json`, `bun.lock`).
- Delete the now-empty `apps/` directory.

Path references to fix (full list found during exploration):
- `frontend/vite.config.ts`:
  - `@db-types` alias `../../packages/db-types/database.ts` → `../packages/db-types/database.ts`
  - `fs.allow: [".", "../..", "../../packages"]` → `[".", "..", "../packages"]`
- `supabase/STORAGE.md:172` — doc reference to `apps/web` ("blocked on `apps/web` existing").
- Re-verify `.gitignore` and `frontend/tsconfig.json` path globs after the move.

Risk: **low.** `apps/web` is entirely untracked (added on this branch, not yet committed
per `git status`), so this is a plain move with no git history to preserve.

## Part 2 — Design tokens (extracted from the reference)

Source of truth: `design/city-priority-map/CityPriorityMap.dc.html` and the already-ported
inline styles (which match it). Token values below were extracted by frequency analysis of
the live hex usage. They live in a single file `frontend/src/design-system/tokens.css` as
CSS custom properties; shadcn's theme variables map onto them.

| Role | Token | Value(s) |
|---|---|---|
| Accent / primary | `--accent` | `#2f64e6` |
| Accent tints | `--accent-soft`, `--accent-line` | `#eaf0ff`, `#d9e4ff` |
| Agent / analysis (violet) | `--violet` (+ soft/line) | `#7c3aed`, `#f6f1ff`, `#e7daff` |
| Ink ramp (text) | `--ink`, `--ink-2`, `--muted`, `--muted-2` | `#1b2430`, `#5b6675`, `#8a94a3`, `#9aa3b1` |
| Surfaces | `--bg`, `--card`, tint ramp | `#eef1f5`, `#fff`, (`#f3f5f8`…`#fbfcfe`) |
| Borders | `--border`, `--border-2`, `--border-strong` | `#e3e7ee`, `#e6e9ee`, `#cdd4de` |
| Success | green | `#30a46c`, `#1d7a4d`, `#e7f6ec`, `#cdecd8` |
| Danger | red | `#e5484d`, `#fdeceb`, `#f8d8d6` |
| Warning | amber | `#f5a623`, `#fff6e0` |
| Fonts | `--font-display`, `--font-mono` | **Public Sans**, **IBM Plex Mono** |
| Radii | sm / md / lg / xl | `4 / 7 / 9 / 11` px (base `--radius: 9px`) |

Several values are Radix Colors (`#30a46c` green, `#e5484d` red), already aligned with
shadcn conventions.

## Part 3 — Tailwind v4 + shadcn setup (in-app)

Target layout:

```
frontend/
  components.json                 # shadcn config; aliases → @/components/ui, @/lib/utils
  src/
    design-system/
      tokens.css                  # the token table above, as CSS vars  ← source of truth
      index.ts                    # JS re-exports of tokens for non-Tailwind use
    components/
      ui/                         # shadcn primitives (generated, then themed)
    lib/
      utils.ts                    # cn() helper (shadcn standard)
    index.css                     # @import "tailwindcss"; @import design-system/tokens.css; @theme mapping
```

- Add deps: `tailwindcss` (v4), `@tailwindcss/vite`, `class-variance-authority`, `clsx`,
  `tailwind-merge`, `lucide-react`, plus the Radix primitives shadcn pulls per component.
- `vite.config.ts` gains the `@tailwindcss/vite` plugin.
- `index.css` imports Tailwind + `tokens.css`, then uses `@theme` to bind shadcn's
  semantic variables (`--background`, `--foreground`, `--primary`, `--border`, `--radius`,
  `--font-sans`, …) to our extracted tokens, so every generated primitive inherits the
  reference look with no per-component overrides.
- shadcn `components.json` configured for the in-app aliases; no `tailwind.config.ts`
  (v4 CSS-first).

Coexistence: feature components keep their inline styles; Tailwind utility classes and the
new primitives live alongside them. Nothing in the existing app breaks because we add, not
replace.

## Part 4 — Primitives to generate (mapped from real inline patterns)

| Current inline pattern | shadcn primitive |
|---|---|
| white rounded shadowed `shell` boxes | `Card` |
| mono uppercase status pills (pending/confirmed, type tags) | `Badge` (+ status/outline variants) |
| accent / ghost buttons, login button | `Button` |
| custom `input[type=range]` (weight, layers) | `Slider` |
| `HistoryPopover` | `Popover` |
| `.pp-scroll` custom scrollbars | `ScrollArea` |
| LoginPage fields | `Input`, `Label` |
| layer on/off toggles | `Switch` / `Checkbox` |
| `ppspin` keyframe loader | `Spinner` (small custom) + `Skeleton` |
| dividers, AnalysisDock tab views | `Separator`, `Tabs`, `Tooltip` |

Themed variants worth adding beyond shadcn defaults:
- `Badge`: `status-pending` (dashed gray), `status-confirmed` (green), `type` (mono
  uppercase tag), to match the existing pills.
- `Button`: `accent` (the `#2f64e6` primary), `ghost`, `outline`.

Feature composites (`ObservationCard`, `AgentPanel`, `AnalysisDock`, `MapCanvas`,
`LayersPanel`) are **not** primitives — they are future consumers, untouched here.

## Part 5 — Verification

- **Showcase page** `DesignSystemShowcase` rendering every primitive × every variant on the
  app background, mounted at a dev-only route/entry (not wired into the main app flow).
- **Screenshot** the showcase with **puppeteer-core** (already a dependency) and compare
  side-by-side against the reference (`design/city-priority-map/`, rendered from
  `CityPriorityMap.dc.html`).
- **Build gate:** `tsc --noEmit && vite build` passes from the new `frontend/` location.
- **No-regression gate:** zero changes to feature component files (verifiable via `git diff
  --stat` showing only design-system / config / moved files).

Definition of done: primitives are visually indistinguishable from the reference's
hand-styled equivalents; app builds from `frontend/`; no feature file modified.

## Files touched (summary)

- **Moved:** all of `apps/web/*` → `frontend/*`; `apps/` removed.
- **Added:** `frontend/components.json`, `frontend/src/design-system/{tokens.css,index.ts}`,
  `frontend/src/components/ui/*`, `frontend/src/lib/utils.ts`, showcase page, deps in
  `package.json`.
- **Edited:** `frontend/vite.config.ts` (paths + Tailwind plugin), `frontend/src/index.css`
  (Tailwind + theme mapping), `frontend/package.json` (deps), `supabase/STORAGE.md` (doc path).
- **Untouched:** every feature component/page, all `services/`, `packages/`, `supabase/`
  migrations, data layer (`src/lib/api.ts`, `supabase.ts`, `types.ts`, etc.).

## Open questions

None blocking. (Storybook intentionally omitted — the puppeteer showcase screenshot is the
lightweight verification for a hackathon.)
