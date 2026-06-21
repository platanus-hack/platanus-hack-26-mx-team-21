import { useEffect, useRef, useState } from "react";
import { money } from "../lib/money";
import {
  ACTIVE_ISSUE_TYPES,
  BUDGET_MAX,
  BUDGET_MIN,
  BUDGET_STEP,
  DEFAULT_SQUADS,
  MAX_SQUADS,
  typeColor,
  typeStep,
  typeUnit,
} from "../lib/types";
import type { RegionOption, TypeCount } from "../lib/types";
import { cn } from "@/lib/utils";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

interface Props {
  issueType: string;
  budget: number;
  regions: RegionOption[];
  regionFilter: string[];
  squadOverride: number | null;
  costs: Record<string, number>;
  types: TypeCount[];
  typeLabels: Record<string, string>;
  pointCount: number;
  previewing: boolean;
  generating?: boolean;
  planError?: string | null;
  hasHistory: boolean;
  open: boolean;
  onToggleOpen: () => void;
  onSetIssueType: (slug: string) => void;
  onBudget: (v: number) => void;
  onToggleRegion: (cve: string) => void;
  onClearRegions: () => void;
  onSetSquadOverride: (n: number | null) => void;
  onAdjCost: (slug: string, delta: number) => void;
  onGenerate: () => void;
  onToggleHistory: () => void;
  onHeight?: (h: number) => void;
}

const MINI_LABEL = "shrink-0 text-[10px] font-bold uppercase tracking-[0.4px] text-muted-foreground";
const STEP_BTN = "h-[26px] w-6 rounded-none text-[15px] leading-none text-[var(--ink-2)] hover:bg-transparent";

function pillClass(active: boolean) {
  return cn(
    "h-[30px] shrink-0 gap-1.5 rounded-[9px] px-3 text-[11.5px] font-semibold",
    active ? "border-primary bg-[#eef3ff] text-primary" : "border-[var(--line)] bg-card text-[#41506a]",
  );
}

export function AnalysisDock(props: Props) {
  const [pop, setPop] = useState<"region" | "cost" | null>(null);
  const togglePop = (p: "region" | "cost") => setPop((cur) => (cur === p ? null : p));

  useEffect(() => {
    if (!props.open) setPop(null);
  }, [props.open]);

  // Dismiss the open popover on any click outside the controls area.
  const controlsRef = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!pop) return;
    const onDown = (e: MouseEvent) => {
      if (!controlsRef.current?.contains(e.target as Node)) setPop(null);
    };
    // Capture phase: Leaflet stops propagation of mousedown over the map,
    // so a bubble-phase listener would never fire for clicks on the map.
    document.addEventListener("mousedown", onDown, true);
    return () => document.removeEventListener("mousedown", onDown, true);
  }, [pop]);

  // Collapse/expand by animating the BODY's height; the header stays as the bar.
  // height:auto can't be transitioned, so we go auto → fixed px → 0 (and back).
  const bodyRef = useRef<HTMLDivElement>(null);
  const [bodyH, setBodyH] = useState<number | "auto">(props.open ? "auto" : 0);
  const first = useRef(true);
  useEffect(() => {
    const el = bodyRef.current;
    if (!el) return;
    if (first.current) {
      first.current = false;
      return;
    }
    if (props.open) {
      setBodyH(el.scrollHeight);
      const t = setTimeout(() => setBodyH("auto"), 210); // settle to auto so content can reflow
      return () => clearTimeout(t);
    }
    setBodyH(el.scrollHeight); // pin current px height, then collapse to 0 next frame
    const r = requestAnimationFrame(() => requestAnimationFrame(() => setBodyH(0)));
    return () => cancelAnimationFrame(r);
  }, [props.open]);

  // Report the expanded card height (once settled) so the layers panel keeps a steady gap.
  const cardRef = useRef<HTMLDivElement>(null);
  const onHeight = props.onHeight;
  useEffect(() => {
    const el = cardRef.current;
    if (el && onHeight && props.open && bodyH === "auto") onHeight(el.offsetHeight);
  }, [onHeight, props.open, bodyH, props.pointCount, props.budget, props.squadOverride, props.regionFilter]);

  const regionLabel =
    props.regionFilter.length === 0
      ? "Todas las alcaldías"
      : `${props.regionFilter.length} alcaldía${props.regionFilter.length > 1 ? "s" : ""}`;
  const squadValue = props.squadOverride ?? DEFAULT_SQUADS;
  const auto = props.squadOverride == null;
  const genDisabled = props.pointCount === 0 || !!props.generating;

  return (
    <Panel
      ref={cardRef}
      className="absolute left-[18px] right-[404px] bottom-[18px] z-[521] flex flex-col overflow-visible"
    >
      {/* header — always visible; doubles as the collapsed bar and the toggle */}
      <div
        onClick={props.onToggleOpen}
        className={cn(
          "flex cursor-pointer items-center gap-[11px] px-3.5 py-[11px]",
          props.open ? "border-b border-[var(--line-2)]" : "border-b border-transparent",
        )}
      >
        <div className="flex size-[30px] shrink-0 items-center justify-center rounded-[9px] bg-primary">
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
        <div className="min-w-0 flex-1">
          <div className="text-[13.5px] font-extrabold tracking-[-0.2px]">Análisis</div>
          <div className="truncate font-mono text-[10.5px] text-muted-foreground">
            {props.pointCount} en la región · {money(props.budget)} · {regionLabel}
          </div>
        </div>
        {props.hasHistory && (
          <Button
            variant="secondary"
            size="icon"
            onClick={(e) => {
              e.stopPropagation();
              props.onToggleHistory();
            }}
            title="Planes anteriores"
            className="size-[30px] shrink-0 rounded-lg bg-[#f1f4f8] text-[var(--ink-2)]"
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M12 8v4l3 2" stroke="#8a94a3" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
              <path d="M3.5 12a8.5 8.5 0 1 0 2.4-5.9M3.5 4v3h3" stroke="#8a94a3" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </Button>
        )}
        <span
          title={props.open ? "Ocultar panel" : "Abrir panel"}
          className={cn(
            "flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-[#f1f4f8] transition-transform duration-200",
            props.open ? "rotate-0" : "rotate-180",
          )}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M6 9l6 6 6-6" stroke="#8a94a3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </span>
      </div>

      {/* collapsible body — height animates between 0 and content height */}
      <div
        ref={bodyRef}
        style={{
          height: bodyH === "auto" ? "auto" : bodyH,
          overflow: bodyH === "auto" ? "visible" : "hidden",
          transition: "height .2s ease",
        }}
      >
        {/* row 1 — issue type + budget, paired on one line */}
        <div className="flex flex-wrap items-center gap-x-[18px] gap-y-[10px] border-b border-[var(--surface-2)] px-3.5 py-[10px]">
          {/* tipo */}
          <div className="flex shrink-0 items-center gap-[9px]">
            <span className={MINI_LABEL}>Tipo</span>
            <div className="relative w-[190px]">
              <span
                className="pointer-events-none absolute left-[11px] top-1/2 size-[9px] -translate-y-1/2 rounded-full"
                style={{ background: typeColor(props.issueType) }}
              />
              <select
                value={props.issueType}
                onChange={(e) => props.onSetIssueType(e.target.value)}
                className="h-8 w-full cursor-pointer appearance-none rounded-[9px] border border-[var(--line)] bg-card pl-[27px] pr-[30px] text-[12.5px] font-semibold text-foreground"
              >
                {props.types.map((t) => {
                  const active = ACTIVE_ISSUE_TYPES.has(t.slug);
                  const label = props.typeLabels[t.slug] ?? t.label;
                  return (
                    <option key={t.slug} value={t.slug} disabled={!active}>
                      {active ? label : `${label} · próximamente`}
                    </option>
                  );
                })}
              </select>
              <svg
                width="14"
                height="14"
                viewBox="0 0 24 24"
                fill="none"
                className="pointer-events-none absolute right-[9px] top-1/2 -translate-y-1/2"
              >
                <path d="M6 9l6 6 6-6" stroke="#8a94a3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            </div>
          </div>

          {/* presupuesto */}
          <div className="flex min-w-[230px] flex-1 items-center gap-2.5">
            <span className={MINI_LABEL}>Presupuesto</span>
            <input
              type="range"
              min={BUDGET_MIN}
              max={BUDGET_MAX}
              step={BUDGET_STEP}
              value={props.budget}
              onChange={(e) => props.onBudget(+e.target.value)}
              className="min-w-[60px] flex-1"
            />
            <span className="min-w-[78px] shrink-0 text-right font-mono text-[13px] font-semibold">
              {money(props.budget)}
            </span>
          </div>
        </div>

        {/* row 2 — region, cuadrillas, cost basis, and the generate button inline */}
        <div ref={controlsRef} className="relative flex flex-wrap items-center gap-[13px] px-3.5 pb-[13px] pt-[12px]">
          {/* region filter */}
          <Button
            variant="outline"
            onClick={() => togglePop("region")}
            className={pillClass(pop === "region" || props.regionFilter.length > 0)}
          >
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="shrink-0">
              <path d="M12 21s-7-5.4-7-11a7 7 0 1114 0c0 5.6-7 11-7 11z" stroke="currentColor" strokeWidth="1.8" />
              <circle cx="12" cy="10" r="2.4" stroke="currentColor" strokeWidth="1.8" />
            </svg>
            {regionLabel}
          </Button>

          {/* squad override */}
          <div className="flex shrink-0 items-center gap-[7px]">
            <span className={MINI_LABEL}>Cuadrillas</span>
            <Button
              variant="outline"
              onClick={() => props.onSetSquadOverride(auto ? squadValue : null)}
              className={cn(pillClass(!auto), "w-[74px]")}
            >
              {auto ? "Auto" : "Manual"}
            </Button>
            {/* always mounted so toggling Auto↔Manual doesn't reflow the row; hidden (space reserved) when auto */}
            <div
              aria-hidden={auto}
              className={cn(
                "flex items-center rounded-lg border border-[var(--line-2)] bg-card",
                auto && "invisible",
              )}
            >
              <Button variant="ghost" size="icon" onClick={() => props.onSetSquadOverride(Math.max(1, squadValue - 1))} className={STEP_BTN}>
                −
              </Button>
              <div className="min-w-[22px] text-center font-mono text-[12px] font-semibold">{squadValue}</div>
              <Button variant="ghost" size="icon" onClick={() => props.onSetSquadOverride(Math.min(MAX_SQUADS, squadValue + 1))} className={STEP_BTN}>
                +
              </Button>
            </div>
          </div>

          {/* cost basis */}
          <Button variant="outline" onClick={() => togglePop("cost")} className={pillClass(pop === "cost")}>
            Base de costos
          </Button>

          {/* generate */}
          <div className="ml-auto flex min-w-0 items-center gap-[9px]">
            {props.planError && (
              <span title={props.planError} className="max-w-[220px] truncate font-mono text-[10.5px] text-[#c2333a]">
                ⚠ {props.planError}
              </span>
            )}
            <Button
              onClick={props.onGenerate}
              disabled={genDisabled}
              className="h-[34px] shrink-0 gap-[7px] rounded-[9px] px-4 text-[12.5px] font-bold"
            >
              {props.generating ? (
                <Spinner size={14} className="border-white/50 border-t-white" />
              ) : (
                <svg width="15" height="15" viewBox="0 -2.5 24 24" fill="none">
                  <path d="M12 3l1.6 4.8L18 9.4l-4.4 1.6L12 16l-1.6-5L6 9.4l4.4-1.6L12 3z" fill="#fff" />
                </svg>
              )}
              {props.generating ? "Generando…" : props.previewing ? "Actualizar plan" : "Generar plan"}
            </Button>
          </div>

          {/* region popover */}
          {pop === "region" && (
            <Popover>
              <div className={POP_HEADER}>
                <span className={POP_TITLE}>Alcaldías (INEGI)</span>
                <Button variant="link" onClick={props.onClearRegions} className="h-auto p-0 text-[11px] font-bold text-primary">
                  Todas
                </Button>
              </div>
              <div className="pp-scroll max-h-[200px] overflow-y-auto px-1.5 pb-2 pt-[3px]">
                {props.regions.map((rg) => {
                  const on = props.regionFilter.includes(rg.cve);
                  return (
                    <Button
                      key={rg.cve}
                      variant="ghost"
                      onClick={() => props.onToggleRegion(rg.cve)}
                      className="flex h-auto w-full items-center justify-start gap-[9px] rounded-lg px-2 py-1.5 font-normal"
                    >
                      <span
                        className="flex size-[15px] shrink-0 items-center justify-center rounded-[4px] border-[1.5px] text-[10px] text-white"
                        style={{ borderColor: on ? "var(--acc,#2f64e6)" : "#cdd4de", background: on ? "var(--acc,#2f64e6)" : "#fff" }}
                      >
                        {on ? "✓" : ""}
                      </span>
                      <span className="flex-1 text-left text-[12px] font-semibold text-[#3a4655]">{rg.name}</span>
                      <span className="font-mono text-[9.5px] text-[#aab2bd]">{rg.count}</span>
                    </Button>
                  );
                })}
              </div>
            </Popover>
          )}

          {/* cost-basis popover */}
          {pop === "cost" && (
            <Popover>
              <div className={POP_HEADER}>
                <span className={POP_TITLE}>Costo unitario</span>
                <span className="text-[9.5px] text-[#aab2bd]">se pasa al módulo</span>
              </div>
              <div className="px-[13px] pb-2 pt-[3px]">
                {props.types
                  .filter((t) => ACTIVE_ISSUE_TYPES.has(t.slug))
                  .map((t) => (
                    <div key={t.slug} className="flex items-center gap-[9px] py-[7px]">
                      <span className="size-2 shrink-0 rounded-full" style={{ background: typeColor(t.slug) }} />
                      <span className="flex-1 text-[12px] font-semibold text-[#3a4655]">
                        {props.typeLabels[t.slug] ?? t.label}
                      </span>
                      <div className="flex items-center rounded-[7px] border border-[var(--line-2)] bg-card">
                        <Button variant="ghost" size="icon" onClick={() => props.onAdjCost(t.slug, -typeStep(t.slug))} className={STEP_BTN}>
                          −
                        </Button>
                        <div className="min-w-[64px] text-center font-mono text-[11px] font-semibold">
                          {money(props.costs[t.slug] ?? 0)}
                        </div>
                        <Button variant="ghost" size="icon" onClick={() => props.onAdjCost(t.slug, typeStep(t.slug))} className={STEP_BTN}>
                          +
                        </Button>
                      </div>
                      <span className="min-w-[30px] font-mono text-[9px] text-[#b3bac5]">/{typeUnit(t.slug)}</span>
                    </div>
                  ))}
              </div>
            </Popover>
          )}
        </div>
      </div>
    </Panel>
  );
}

const POP_HEADER = "flex items-center justify-between border-b border-[var(--surface-2)] px-[13px] py-[9px]";
const POP_TITLE = "text-[10px] font-bold uppercase tracking-[0.5px] text-[#7a8493]";

function Popover({ children }: { children: React.ReactNode }) {
  return (
    <Panel className="absolute bottom-[58px] right-3.5 z-[6] w-[288px] rounded-xl">
      {children}
    </Panel>
  );
}
