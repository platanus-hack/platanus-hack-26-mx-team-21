# Repo Flatten + Isolated In-App Design System Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the frontend from `apps/web/` to a top-level `frontend/` folder and stand up an isolated, in-app shadcn/ui + Tailwind v4 design system themed from the reference tokens — without rewiring any feature component.

**Architecture:** Flatten the repo first so all paths are clean, then add Tailwind v4 (CSS-first, no `tailwind.config.ts`) and a single token layer (`src/design-system/tokens.css`) that shadcn's semantic theme variables map onto. Generate shadcn primitives into `src/components/ui/`, customize only the `Badge` to reproduce the reference's status pills, and prove fidelity with an isolated showcase HTML entry screenshotted via the existing puppeteer pattern. Feature components keep their inline styles and are never edited.

**Tech Stack:** Vite 5, React 18, TypeScript, **bun**, Tailwind CSS v4 (`@tailwindcss/vite`), shadcn/ui (Radix + cva + clsx + tailwind-merge), lucide-react, tw-animate-css, puppeteer-core. Fonts: Public Sans + IBM Plex Mono (already loaded via `index.html`).

## Global Constraints

- **No feature-component edits.** These files must show zero diff at the end: `src/App.tsx`, `src/pages/*`, `src/components/{MapCanvas,AnalysisDock,AgentPanel,ObservationCard,LayersPanel,HistoryPopover}.tsx`, and everything under `src/lib/`. Verify with `git diff --stat`.
- **Tailwind v4 only** — CSS-first config, **no `tailwind.config.ts`**.
- **In-app design system** — primitives under `frontend/src/components/ui/`, tokens under `frontend/src/design-system/`. No separate workspace package.
- **Package manager is `bun`** — use `bun install`, `bunx`, never npm/pnpm/yarn.
- **Preserve existing `src/index.css` globals verbatim:** the `--acc` variable (the range-input CSS depends on `var(--acc, #2f64e6)`), `.leaflet-*` rules, `.pp-scroll` scrollbar rules, `input[type="range"]` styling, and the `@keyframes` `ppspin`/`pppulse`/`ppin`/`ppup`. Feature components depend on all of these.
- **Naming note (deviation from spec):** the spec labelled the brand blue `--accent`. The implementation names it **`--brand`** in `tokens.css`, because shadcn reserves `--color-accent` for the subtle hover-background role. Brand blue `#2f64e6` maps to shadcn's **`--color-primary`**.
- **Fonts are already loaded** via the Google Fonts `<link>` in `index.html` (and the new `showcase.html`). Do not add font tooling.
- **Screenshots** use `puppeteer-core` with Chrome at `/Applications/Google Chrome.app/Contents/MacOS/Google Chrome`, dev server on `http://localhost:5173` — matching `scripts/shot.mjs`.
- **All paths below are relative to the repo root** `/Volumes/T7/projs/Platanus_Hackathon_2026` unless prefixed with `frontend/`.

---

### Task 1: Flatten `apps/web/` → `frontend/`

Moves the entire (untracked) app to a top-level folder and fixes the four path references that point at the old `../../` depth.

**Files:**
- Move: `apps/web/` (all contents) → `frontend/`; remove empty `apps/`
- Modify: `frontend/vite.config.ts` (db-types alias + `fs.allow`)
- Modify: `frontend/tsconfig.json` (db-types path + `include`)
- Modify: `supabase/STORAGE.md:172` (doc path reference)

**Interfaces:**
- Produces: the app now lives at `frontend/`; `bun run build` and `bun run typecheck` run from `frontend/`. All later tasks operate inside `frontend/`.

- [ ] **Step 1: Move the directory**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026
mv apps/web frontend
rmdir apps
ls -d frontend apps 2>&1   # expect: frontend listed, apps -> "No such file or directory"
```

- [ ] **Step 2: Fix `frontend/vite.config.ts`**

Replace the whole file with (db-types path drops one `../`, `fs.allow` updated):

```ts
import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
      "@db-types": fileURLToPath(
        new URL("../packages/db-types/database.ts", import.meta.url),
      ),
    },
  },
  server: {
    port: 5173,
    // allow importing the shared db-types package from outside the app root
    fs: { allow: [".", "..", "../packages"] },
  },
});
```

(The `@tailwindcss/vite` plugin is added in Task 2.)

- [ ] **Step 3: Fix `frontend/tsconfig.json` paths**

Change the two `../../packages/...` references to `../packages/...`:

```jsonc
    "paths": {
      "@/*": ["src/*"],
      "@db-types": ["../packages/db-types/database.ts"]
    }
  },
  "include": ["src", "../packages/db-types/database.ts"]
```

- [ ] **Step 4: Fix the doc reference**

In `supabase/STORAGE.md` line ~172, replace `apps/web` with `frontend`:

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026
grep -n "apps/web" supabase/STORAGE.md   # confirm the one hit, then edit it to "frontend"
```

Edit that line so it reads `…blocked on \`frontend\` existing` (or current phrasing with `frontend`).

- [ ] **Step 5: Reinstall to rebuild `node_modules/.bin` after the move**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun install
```

Expected: completes without error.

- [ ] **Step 6: Verify typecheck + build pass from the new location**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run typecheck && bun run build
```

Expected: `tsc --noEmit` clean, `vite build` succeeds, no `Cannot find module '@db-types'`.

- [ ] **Step 7: Commit**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026
git add -A
git commit -m "refactor(repo): flatten apps/web -> frontend/, fix db-types paths"
```

---

### Task 2: Add Tailwind v4 + token layer + theme mapping (preserve globals)

Introduces Tailwind v4, the `cn()` helper, the extracted token file, and the shadcn theme mapping — while keeping every existing global rule. Ends with a before/after login screenshot to confirm Tailwind's preflight did not visually regress the untouched app.

**Files:**
- Modify: `frontend/package.json` (deps)
- Modify: `frontend/vite.config.ts` (add `@tailwindcss/vite`)
- Create: `frontend/src/lib/utils.ts`
- Create: `frontend/src/design-system/tokens.css`
- Create: `frontend/src/design-system/index.ts`
- Modify: `frontend/src/index.css` (Tailwind import + theme + preserved globals)

**Interfaces:**
- Produces: `cn(...inputs: ClassValue[]) => string` from `@/lib/utils`; CSS variables `--brand`, `--violet`, ink/surface/border/status ramps, `--font-display`, `--font-mono`, `--radius` from `tokens.css`; Tailwind utilities + shadcn color/radius theme keys (`bg-background`, `text-foreground`, `bg-primary`, `border-border`, `rounded-lg`, …) available app-wide.

- [ ] **Step 1: Capture the BASELINE login screenshot (before Tailwind)**

Start the dev server in the background, screenshot the login page, stop it:

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run dev &   # note the PID
sleep 3
node -e '
import("puppeteer-core").then(async ({default:p})=>{
  const b=await p.launch({executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",headless:"new",args:["--no-sandbox","--disable-gpu"],defaultViewport:{width:1440,height:900,deviceScaleFactor:2}});
  const pg=await b.newPage(); await pg.goto("http://localhost:5173/",{waitUntil:"networkidle2"});
  await pg.waitForSelector("input[type=password]"); await pg.screenshot({path:"/tmp/login-before.png"});
  await b.close(); console.log("baseline ok");
});'
kill %1   # stop dev server
```

Expected: `/tmp/login-before.png` written, "baseline ok".

- [ ] **Step 2: Add dependencies**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun add tailwindcss @tailwindcss/vite
bun add class-variance-authority clsx tailwind-merge lucide-react
bun add -d tw-animate-css
```

Expected: `package.json` gains these; install succeeds.

- [ ] **Step 3: Wire the Tailwind Vite plugin**

In `frontend/vite.config.ts` add the import and plugin:

```ts
import tailwindcss from "@tailwindcss/vite";
// ...
  plugins: [react(), tailwindcss()],
```

- [ ] **Step 4: Create the `cn()` helper**

`frontend/src/lib/utils.ts`:

```ts
import { clsx, type ClassValue } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

- [ ] **Step 5: Create the token file**

`frontend/src/design-system/tokens.css` (extracted reference values; single source of truth):

```css
/* CityCrawl design tokens — extracted from the reference design.
   Single source of truth. shadcn theme variables (index.css) map onto these. */
:root {
  /* Brand (shadcn --color-primary) */
  --brand: #2f64e6;
  --brand-soft: #eaf0ff;
  --brand-line: #d9e4ff;

  /* Violet — agent / analysis accent */
  --violet: #7c3aed;
  --violet-soft: #f6f1ff;
  --violet-line: #e7daff;

  /* Ink ramp (text) */
  --ink: #1b2430;
  --ink-2: #5b6675;
  --muted-ink: #8a94a3;
  --muted-ink-2: #9aa3b1;

  /* Surfaces */
  --bg: #eef1f5;
  --card: #ffffff;
  --surface-1: #f7f9fc;
  --surface-2: #f3f5f8;

  /* Borders */
  --line: #e3e7ee;
  --line-2: #e6e9ee;
  --line-strong: #cdd4de;

  /* Status — success */
  --success: #30a46c;
  --success-ink: #1d7a4d;
  --success-soft: #e7f6ec;
  --success-line: #cdecd8;
  /* Status — danger */
  --danger: #e5484d;
  --danger-soft: #fdeceb;
  --danger-line: #f8d8d6;
  /* Status — warning */
  --warning: #f5a623;
  --warning-soft: #fff6e0;

  /* Type */
  --font-display: "Public Sans", system-ui, sans-serif;
  --font-mono: "IBM Plex Mono", monospace;

  /* Radius base (scale derived in index.css @theme) */
  --radius: 9px;
}
```

- [ ] **Step 6: Create the token JS re-export**

`frontend/src/design-system/index.ts` (lets non-Tailwind code read tokens by name):

```ts
/** Token names available as CSS variables (see design-system/tokens.css).
 *  Use as `var(${tokens.brand})` or in inline styles when a utility class
 *  is not appropriate. */
export const tokens = {
  brand: "--brand",
  violet: "--violet",
  ink: "--ink",
  ink2: "--ink-2",
  mutedInk: "--muted-ink",
  bg: "--bg",
  card: "--card",
  line: "--line",
  success: "--success",
  danger: "--danger",
  warning: "--warning",
  fontDisplay: "--font-display",
  fontMono: "--font-mono",
  radius: "--radius",
} as const;
```

- [ ] **Step 7: Rewrite `frontend/src/index.css` (Tailwind + theme + preserved globals)**

Replace the whole file with the following. The block from `/* ===== preserved globals` downward is the **existing** content kept verbatim (only `--acc` is re-pointed at `--brand`):

```css
@import "tailwindcss";
@import "tw-animate-css";
@import "./design-system/tokens.css";

/* Map shadcn semantic theme keys onto our tokens (Tailwind v4 CSS-first). */
@theme inline {
  --color-background: var(--bg);
  --color-foreground: var(--ink);
  --color-card: var(--card);
  --color-card-foreground: var(--ink);
  --color-popover: var(--card);
  --color-popover-foreground: var(--ink);
  --color-primary: var(--brand);
  --color-primary-foreground: #ffffff;
  --color-secondary: var(--surface-2);
  --color-secondary-foreground: var(--ink);
  --color-muted: var(--surface-2);
  --color-muted-foreground: var(--muted-ink);
  --color-accent: var(--surface-2);
  --color-accent-foreground: var(--ink);
  --color-destructive: var(--danger);
  --color-destructive-foreground: #ffffff;
  --color-border: var(--line);
  --color-input: var(--line);
  --color-ring: var(--brand);

  --radius-sm: calc(var(--radius) - 4px);
  --radius-md: calc(var(--radius) - 2px);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) + 2px);

  --font-sans: var(--font-display);
  --font-mono: var(--font-mono);
}

/* ===== preserved globals — feature components depend on these, do not remove ===== */
:root {
  --acc: var(--brand);
}
* {
  box-sizing: border-box;
}
html,
body,
#root {
  margin: 0;
  padding: 0;
  height: 100%;
}
body {
  font-family: "Public Sans", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
  color: #1b2430;
  background: #eef1f5;
}

.leaflet-container {
  background: #eef1f5;
  font-family: "Public Sans", sans-serif;
}
.leaflet-bar a,
.leaflet-control-attribution {
  font-family: "Public Sans", sans-serif;
}

.pp-scroll::-webkit-scrollbar {
  width: 8px;
  height: 8px;
}
.pp-scroll::-webkit-scrollbar-thumb {
  background: #d4d9e0;
  border-radius: 8px;
}
.pp-scroll::-webkit-scrollbar-track {
  background: transparent;
}

input[type="range"] {
  -webkit-appearance: none;
  appearance: none;
  height: 4px;
  border-radius: 4px;
  background: #e3e7ee;
  outline: none;
}
input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  border: 3px solid var(--acc, #2f64e6);
  cursor: pointer;
  box-shadow: 0 1px 3px rgba(20, 30, 50, 0.25);
}
input[type="range"]::-moz-range-thumb {
  width: 16px;
  height: 16px;
  border-radius: 50%;
  background: #fff;
  border: 3px solid var(--acc, #2f64e6);
  cursor: pointer;
}

@keyframes ppspin {
  to {
    transform: rotate(360deg);
  }
}
@keyframes pppulse {
  0%,
  100% {
    opacity: 0.55;
  }
  50% {
    opacity: 1;
  }
}
@keyframes ppin {
  from {
    opacity: 0;
    transform: translateY(6px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
@keyframes ppup {
  from {
    opacity: 0;
    transform: translateY(14px);
  }
  to {
    opacity: 1;
    transform: translateY(0);
  }
}
```

- [ ] **Step 8: Typecheck + build**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run typecheck && bun run build
```

Expected: both pass. (Tailwind now compiles via the Vite plugin.)

- [ ] **Step 9: Capture the AFTER login screenshot and compare (preflight no-regression)**

Repeat Step 1's screenshot to `/tmp/login-after.png`, then open both:

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run dev &
sleep 3
node -e '
import("puppeteer-core").then(async ({default:p})=>{
  const b=await p.launch({executablePath:"/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",headless:"new",args:["--no-sandbox","--disable-gpu"],defaultViewport:{width:1440,height:900,deviceScaleFactor:2}});
  const pg=await b.newPage(); await pg.goto("http://localhost:5173/",{waitUntil:"networkidle2"});
  await pg.waitForSelector("input[type=password]"); await pg.screenshot({path:"/tmp/login-after.png"});
  await b.close(); console.log("after ok");
});'
kill %1
open /tmp/login-before.png /tmp/login-after.png
```

Expected: login page looks identical. **If preflight introduced a regression** (e.g. changed default heading/button rendering on the login page), note it in the commit and add a scoped fix in `index.css` `@layer base` — do not edit `LoginPage.tsx`.

- [ ] **Step 10: Commit**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026
git add -A
git commit -m "feat(ds): add Tailwind v4 + token layer + shadcn theme mapping"
```

---

### Task 3: shadcn config + static primitives + reference Badge variants + Spinner

Adds `components.json` and the non-interactive (static) primitives, customizes only `Badge` to reproduce the reference status pills, and authors the small `Spinner`.

**Files:**
- Create: `frontend/components.json`
- Create (via CLI): `frontend/src/components/ui/{button,card,badge,input,label,separator,skeleton}.tsx`
- Modify: `frontend/src/components/ui/badge.tsx` (add reference variants)
- Create: `frontend/src/components/ui/spinner.tsx`

**Interfaces:**
- Produces: `Button`, `Card`, `Badge` (with `variant` incl. `statusPending | statusConfirmed | type`), `Input`, `Label`, `Separator`, `Skeleton`, `Spinner` — all importable from `@/components/ui/<name>`.

- [ ] **Step 1: Create `frontend/components.json`**

```json
{
  "$schema": "https://ui.shadcn.com/schema.json",
  "style": "new-york",
  "rsc": false,
  "tsx": true,
  "tailwind": {
    "config": "",
    "css": "src/index.css",
    "baseColor": "neutral",
    "cssVariables": true,
    "prefix": ""
  },
  "iconLibrary": "lucide",
  "aliases": {
    "components": "@/components",
    "utils": "@/lib/utils",
    "ui": "@/components/ui",
    "lib": "@/lib",
    "hooks": "@/hooks"
  }
}
```

- [ ] **Step 2: Add the static primitives via the shadcn CLI**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bunx --bun shadcn@latest add button card badge input label separator skeleton --yes
```

Expected: files appear under `src/components/ui/`. If the CLI offers to overwrite `src/index.css`, **decline / leave our theme intact** — we already configured it. Verify our `@theme inline` block is still present:

```bash
grep -c "var(--brand)" src/index.css   # expect >= 1
ls src/components/ui                    # expect the 7 files
```

- [ ] **Step 3: Add reference status variants to `Badge`**

In `frontend/src/components/ui/badge.tsx`, extend the `cva` `variant` map — **keep the generated `default/secondary/destructive/outline` entries** and append:

```ts
        statusPending:
          "border border-dashed border-[var(--line-strong)] bg-[var(--surface-2)] text-[var(--muted-ink)] font-mono text-[8px] font-semibold uppercase tracking-wide",
        statusConfirmed:
          "border border-[var(--success-line)] bg-[var(--success-soft)] text-[var(--success-ink)] font-mono text-[8px] font-semibold uppercase tracking-wide",
        type: "border border-[var(--line)] bg-[var(--surface-1)] text-[var(--ink-2)] font-mono text-[8px] font-semibold uppercase tracking-wide",
```

- [ ] **Step 4: Author the `Spinner` primitive**

`frontend/src/components/ui/spinner.tsx` (matches the reference's 18px brand-topped loader; uses Tailwind's built-in `animate-spin`):

```tsx
import { cn } from "@/lib/utils";

export function Spinner({
  className,
  size = 18,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <span
      role="status"
      aria-label="Cargando"
      className={cn(
        "inline-block animate-spin rounded-full border-[2.5px] border-[var(--line)] border-t-[var(--brand)]",
        className,
      )}
      style={{ width: size, height: size }}
    />
  );
}
```

- [ ] **Step 5: Typecheck + build**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run typecheck && bun run build
```

Expected: both pass.

- [ ] **Step 6: Commit**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026
git add -A
git commit -m "feat(ds): add static shadcn primitives + reference badge variants + spinner"
```

---

### Task 4: Interactive Radix primitives

Adds the primitives that wrap Radix (overlays, form controls, scroll). CLI-generated; no customization beyond what they inherit from the theme.

**Files:**
- Create (via CLI): `frontend/src/components/ui/{slider,popover,switch,checkbox,tabs,tooltip,scroll-area}.tsx`

**Interfaces:**
- Produces: `Slider`, `Popover`/`PopoverTrigger`/`PopoverContent`, `Switch`, `Checkbox`, `Tabs`/`TabsList`/`TabsTrigger`/`TabsContent`, `Tooltip`/`TooltipProvider`/`TooltipTrigger`/`TooltipContent`, `ScrollArea` — importable from `@/components/ui/<name>`.

- [ ] **Step 1: Add the interactive primitives**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bunx --bun shadcn@latest add slider popover switch checkbox tabs tooltip scroll-area --yes
```

Expected: 7 files under `src/components/ui/`; Radix deps installed into `package.json`. Again, **do not let it overwrite our `index.css` theme** — verify:

```bash
grep -c "var(--brand)" src/index.css   # expect >= 1
ls src/components/ui                    # expect the 14 primitive files + spinner
```

- [ ] **Step 2: Typecheck + build**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run typecheck && bun run build
```

Expected: both pass.

- [ ] **Step 3: Commit**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026
git add -A
git commit -m "feat(ds): add interactive Radix-based shadcn primitives"
```

---

### Task 5: Showcase entry + screenshot verification

Adds an isolated `showcase.html` Vite entry (separate from the auth-gated app — `App.tsx` untouched) that renders every primitive, then screenshots it and compares to the reference for fidelity.

**Files:**
- Create: `frontend/showcase.html`
- Create: `frontend/src/showcase.tsx`
- Create: `frontend/src/design-system/showcase/DesignSystemShowcase.tsx`
- Create: `scripts/shot-showcase.mjs`

**Interfaces:**
- Consumes: every primitive from Task 3 + Task 4.
- Produces: `/tmp/citycrawl-showcase.png`; a dev-only route `http://localhost:5173/showcase.html`.

- [ ] **Step 1: Create the showcase component**

`frontend/src/design-system/showcase/DesignSystemShowcase.tsx` (showcase chrome uses inline layout styles intentionally — only the primitives under test come from the design system):

```tsx
import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Spinner } from "@/components/ui/spinner";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginBottom: 28 }}>
      <h2
        style={{
          font: "600 11px var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: ".6px",
          color: "var(--muted-ink)",
          margin: "0 0 10px",
        }}
      >
        {title}
      </h2>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          alignItems: "center",
        }}
      >
        {children}
      </div>
    </section>
  );
}

export function DesignSystemShowcase() {
  return (
    <TooltipProvider>
      <div data-showcase-ready style={{ maxWidth: 900, margin: "0 auto", padding: 32 }}>
        <h1 style={{ font: "800 22px var(--font-display)", color: "var(--ink)", margin: "0 0 4px" }}>
          CityCrawl — Design System
        </h1>
        <p style={{ color: "var(--muted-ink)", margin: "0 0 24px", fontFamily: "var(--font-display)" }}>
          shadcn/ui primitives themed from the reference tokens
        </p>

        <Section title="Buttons">
          <Button>Default</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button disabled>Disabled</Button>
        </Section>

        <Section title="Badges">
          <Badge>Default</Badge>
          <Badge variant="secondary">Secondary</Badge>
          <Badge variant="outline">Outline</Badge>
          <Badge variant="statusPending">PENDIENTE</Badge>
          <Badge variant="statusConfirmed">CONFIRMADO</Badge>
          <Badge variant="type">SEMÁFORO</Badge>
        </Section>

        <Section title="Card">
          <Card style={{ width: 280, padding: 14 }}>
            <div style={{ fontWeight: 700, fontFamily: "var(--font-display)" }}>Observación</div>
            <Separator style={{ margin: "10px 0" }} />
            <div style={{ color: "var(--ink-2)", fontSize: 13 }}>Contenido de ejemplo.</div>
          </Card>
        </Section>

        <Section title="Form">
          <div style={{ display: "grid", gap: 6, width: 240 }}>
            <Label htmlFor="email">Correo</Label>
            <Input id="email" placeholder="tu@correo.mx" />
          </div>
        </Section>

        <Section title="Slider">
          <div style={{ width: 240 }}>
            <Slider defaultValue={[60]} max={100} step={1} />
          </div>
        </Section>

        <Section title="Toggles">
          <Switch defaultChecked />
          <Checkbox defaultChecked />
        </Section>

        <Section title="Tabs">
          <Tabs defaultValue="ruta" style={{ width: 320 }}>
            <TabsList>
              <TabsTrigger value="ruta">Ruta</TabsTrigger>
              <TabsTrigger value="grupo">Grupo</TabsTrigger>
            </TabsList>
            <TabsContent value="ruta">Análisis de ruta</TabsContent>
            <TabsContent value="grupo">Análisis de grupo</TabsContent>
          </Tabs>
        </Section>

        <Section title="Overlays">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline">Popover</Button>
            </PopoverTrigger>
            <PopoverContent>Planes anteriores…</PopoverContent>
          </Popover>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost">Tooltip</Button>
            </TooltipTrigger>
            <TooltipContent>Detalle</TooltipContent>
          </Tooltip>
        </Section>

        <Section title="Loading">
          <Spinner />
          <Skeleton style={{ width: 160, height: 14 }} />
        </Section>

        <Section title="ScrollArea">
          <ScrollArea
            className="pp-scroll"
            style={{
              height: 80,
              width: 200,
              border: "1px solid var(--line)",
              borderRadius: 9,
              padding: 8,
            }}
          >
            {Array.from({ length: 20 }).map((_, i) => (
              <div key={i} style={{ fontSize: 13, fontFamily: "var(--font-display)" }}>
                Fila {i + 1}
              </div>
            ))}
          </ScrollArea>
        </Section>
      </div>
    </TooltipProvider>
  );
}
```

- [ ] **Step 2: Create the showcase entry module**

`frontend/src/showcase.tsx`:

```tsx
import React from "react";
import ReactDOM from "react-dom/client";
import "./index.css";
import { DesignSystemShowcase } from "./design-system/showcase/DesignSystemShowcase";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <DesignSystemShowcase />
  </React.StrictMode>,
);
```

- [ ] **Step 3: Create the showcase HTML entry**

`frontend/showcase.html`:

```html
<!DOCTYPE html>
<html lang="es">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>CityCrawl · Design System</title>
    <link rel="preconnect" href="https://fonts.googleapis.com" />
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin />
    <link
      href="https://fonts.googleapis.com/css2?family=Public+Sans:ital,wght@0,400;0,500;0,600;0,700;0,800&family=IBM+Plex+Mono:wght@400;500;600&display=swap"
      rel="stylesheet"
    />
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/showcase.tsx"></script>
  </body>
</html>
```

- [ ] **Step 4: Create the screenshot script**

`scripts/shot-showcase.mjs` (modeled on `scripts/shot.mjs`):

```js
import puppeteer from "puppeteer-core";

const CHROME = "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const URL = "http://localhost:5173/showcase.html";

const browser = await puppeteer.launch({
  executablePath: CHROME,
  headless: "new",
  args: ["--no-sandbox", "--disable-gpu"],
  defaultViewport: { width: 1200, height: 1600, deviceScaleFactor: 2 },
});
const page = await browser.newPage();
page.on("pageerror", (e) => console.log("PAGEERROR", e.message));

await page.goto(URL, { waitUntil: "networkidle2" });
await page.waitForSelector("[data-showcase-ready]");
await page.screenshot({ path: "/tmp/citycrawl-showcase.png", fullPage: true });
console.log("showcase shot ok");

await browser.close();
```

- [ ] **Step 5: Run the showcase, screenshot it, compare to the reference**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run dev &
sleep 3
node /Volumes/T7/projs/Platanus_Hackathon_2026/scripts/shot-showcase.mjs
kill %1
open /tmp/citycrawl-showcase.png
open /Volumes/T7/projs/Platanus_Hackathon_2026/design/city-priority-map/CityPriorityMap.dc.html
```

Expected: `/tmp/citycrawl-showcase.png` written with **no `PAGEERROR` lines**. Visually compare: primitives (buttons, status pills, card, slider, scrollbar) should match the reference's hand-styled equivalents in color, radius, and typography. If a primitive is off (e.g. radius/weight), adjust the token in `tokens.css` or the variant class — never a feature file — and re-shoot.

- [ ] **Step 6: Confirm no feature files changed across the whole effort**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026
git diff --stat main -- frontend/src/App.tsx frontend/src/pages frontend/src/components/MapCanvas.tsx frontend/src/components/AnalysisDock.tsx frontend/src/components/AgentPanel.tsx frontend/src/components/ObservationCard.tsx frontend/src/components/LayersPanel.tsx frontend/src/components/HistoryPopover.tsx frontend/src/lib
```

Expected: **empty output** (these were only moved, not modified). Note: the move means these paths differ from `main`; the check compares content of the moved files — they should be byte-identical to their `apps/web` originals aside from path.

- [ ] **Step 7: Final build + commit**

```bash
cd /Volumes/T7/projs/Platanus_Hackathon_2026/frontend
bun run typecheck && bun run build
cd /Volumes/T7/projs/Platanus_Hackathon_2026
git add -A
git commit -m "feat(ds): design-system showcase + screenshot verification"
```

---

## Self-Review

**Spec coverage:**
- Repo flatten (spec Part 1) → Task 1. ✓ (move, path fixes for vite/tsconfig/STORAGE.md)
- Design tokens (spec Part 2) → Task 2 Step 5 `tokens.css`, all values from the spec table. ✓ (`--accent` renamed `--brand` per the documented Global Constraint)
- Tailwind v4 + shadcn setup (spec Part 3) → Task 2 (Tailwind+theme) + Task 3 Step 1 (`components.json`). ✓
- Primitives mapping (spec Part 4) → Task 3 (Card, Button, Badge, Input, Label, Separator, Skeleton, Spinner) + Task 4 (Slider, Popover, Switch, Checkbox, Tabs, Tooltip, ScrollArea). ✓ Badge status/type variants → Task 3 Step 3. ✓
- Verification (spec Part 5) → Task 5 (showcase + puppeteer screenshot) + build gates each task + no-regression login screenshot (Task 2) + no-feature-diff check (Task 5 Step 6). ✓
- Non-goals (no feature rewiring) → enforced by Global Constraints + Task 5 Step 6 gate. ✓

**Placeholder scan:** No TBD/TODO; every code step contains full file content or the exact lines to add. ✓

**Type consistency:** `cn()` signature consistent (defined Task 2, used by `Spinner` Task 3). `Badge` variant names `statusPending`/`statusConfirmed`/`type` defined in Task 3 Step 3 and consumed in Task 5 showcase. `Spinner` props (`className`, `size`) consistent between definition (Task 3) and use (Task 5). Primitive import paths `@/components/ui/<name>` consistent throughout. ✓

**Known risk:** Tailwind v4 preflight could alter the untouched app's default element rendering. Mitigated by the before/after login screenshot gate (Task 2 Step 9); fix, if any, stays in `index.css`, never a feature file.
