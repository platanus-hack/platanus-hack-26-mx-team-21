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

export function AnalysisDock(props: Props) {
  const [pop, setPop] = useState<"region" | "cost" | null>(null);
  const togglePop = (p: "region" | "cost") => setPop((cur) => (cur === p ? null : p));

  // Cross-fade between launcher and full dock. Both stay mounted for the duration of
  // the transition so there's never an empty frame (no flash). `anim` drives which
  // keyframe the dock plays; once it clears, only one of the two is rendered.
  const [anim, setAnim] = useState<"in" | "out" | null>(null);
  const prevOpen = useRef(props.open);
  useEffect(() => {
    if (prevOpen.current === props.open) return;
    prevOpen.current = props.open;
    setPop(null);
    setAnim(props.open ? "in" : "out");
    const t = setTimeout(() => setAnim(null), 200);
    return () => clearTimeout(t);
  }, [props.open]);

  const showDock = props.open || anim === "out";
  const showLauncher = !props.open || anim === "in";

  // Report the dock's rendered height so sibling panels can sit a consistent gap above it.
  const dockRef = useRef<HTMLDivElement>(null);
  const onHeight = props.onHeight;
  useEffect(() => {
    const el = dockRef.current;
    if (!el || !onHeight) return;
    onHeight(el.offsetHeight);
    const ro = new ResizeObserver(() => onHeight(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [onHeight, showDock]);

  const regionLabel =
    props.regionFilter.length === 0
      ? "Todas las alcaldías"
      : `${props.regionFilter.length} alcaldía${props.regionFilter.length > 1 ? "s" : ""}`;
  const squadValue = props.squadOverride ?? DEFAULT_SQUADS;
  const auto = props.squadOverride == null;

  return (
    <>
      {/* collapsed → header-only bar; sits behind the dock so it's revealed/covered cleanly */}
      {showLauncher && (
        <button onClick={props.onToggleOpen} style={launcher} title="Abrir análisis">
          <span style={{ ...launcherDot, background: "var(--acc,#2f64e6)" }}>
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none">
              <path d="M4 19V9M10 19V5M16 19v-7M22 19H2" stroke="#fff" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
          <span style={{ fontWeight: 800, letterSpacing: "-.2px" }}>Análisis</span>
          <span style={launcherMeta}>{props.pointCount} pts · {money(props.budget)}</span>
          <span style={{ marginLeft: "auto", display: "flex" }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M6 15l6-6 6 6" stroke="#8a94a3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </span>
        </button>
      )}

      {showDock && (
    <div
      ref={dockRef}
      style={{
        position: "absolute",
        left: 18,
        right: 404,
        bottom: 18,
        zIndex: 521,
        background: "rgba(255,255,255,.96)",
        // backdrop-filter is dropped mid-animation: re-blurring every frame is what made
        // the open/close janky, and the bg is ~opaque so the difference is imperceptible.
        backdropFilter: anim ? "none" : "blur(16px)",
        WebkitBackdropFilter: anim ? "none" : "blur(16px)",
        border: "1px solid rgba(230,233,238,.95)",
        borderRadius: 16,
        boxShadow: "0 28px 70px -34px rgba(20,30,50,.55)",
        display: "flex",
        flexDirection: "column",
        overflow: "visible",
        willChange: anim ? "transform, opacity" : undefined,
        animation: anim === "out" ? "ppdown .2s ease forwards" : anim === "in" ? "ppup .2s ease" : undefined,
        pointerEvents: anim === "out" ? "none" : "auto",
      }}
    >
      {/* header */}
      <div
        style={{
          padding: "11px 14px",
          display: "flex",
          alignItems: "center",
          gap: 11,
          borderBottom: "1px solid #eef0f4",
        }}
      >
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 9,
            background: "var(--acc,#2f64e6)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flex: "none",
          }}
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path
              d="M4 19V9M10 19V5M16 19v-7M22 19H2"
              stroke="#fff"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </div>
        <div style={{ minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 13.5, fontWeight: 800, letterSpacing: "-.2px" }}>
            Análisis
          </div>
          <div
            style={{
              fontSize: 10.5,
              color: "#9aa3b1",
              fontFamily: "IBM Plex Mono, monospace",
              whiteSpace: "nowrap",
              overflow: "hidden",
              textOverflow: "ellipsis",
            }}
          >
            {props.pointCount} en la región · {money(props.budget)} · {regionLabel}
          </div>
        </div>
        {props.hasHistory && (
          <button onClick={props.onToggleHistory} title="Planes anteriores" style={iconBtn}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path
                d="M12 8v4l3 2"
                stroke="#8a94a3"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
              <path
                d="M3.5 12a8.5 8.5 0 1 0 2.4-5.9M3.5 4v3h3"
                stroke="#8a94a3"
                strokeWidth="1.8"
                strokeLinecap="round"
                strokeLinejoin="round"
              />
            </svg>
          </button>
        )}
        <button onClick={props.onToggleOpen} title="Ocultar panel" style={iconBtn}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M6 9l6 6 6-6" stroke="#8a94a3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </button>
      </div>

      {/* issue-type selector */}
      <div
        style={{
          padding: "9px 14px",
          display: "flex",
          alignItems: "center",
          gap: 9,
          borderBottom: "1px solid #f3f5f8",
        }}
      >
        <span style={miniLabel}>Tipo</span>
        <div style={{ position: "relative", flex: "1 1 220px", maxWidth: 280 }}>
          <span
            style={{
              position: "absolute",
              left: 11,
              top: "50%",
              transform: "translateY(-50%)",
              width: 9,
              height: 9,
              borderRadius: "50%",
              background: typeColor(props.issueType),
              pointerEvents: "none",
            }}
          />
          <select
            value={props.issueType}
            onChange={(e) => props.onSetIssueType(e.target.value)}
            style={{
              width: "100%",
              appearance: "none",
              WebkitAppearance: "none",
              border: "1px solid #e3e7ee",
              background: "#fff",
              borderRadius: 9,
              height: 32,
              padding: "0 30px 0 27px",
              fontFamily: "Public Sans, sans-serif",
              fontSize: 12.5,
              fontWeight: 600,
              color: "#1b2430",
              cursor: "pointer",
            }}
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
            style={{ position: "absolute", right: 9, top: "50%", transform: "translateY(-50%)", pointerEvents: "none" }}
          >
            <path d="M6 9l6 6 6-6" stroke="#8a94a3" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </div>
      </div>

      {/* controls */}
      <div
        style={{
          padding: "11px 14px 13px",
          display: "flex",
          alignItems: "center",
          gap: 13,
          flexWrap: "wrap",
          position: "relative",
        }}
      >
        {/* budget */}
        <div style={{ flex: "1 1 200px", minWidth: 170, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={miniLabel}>Presupuesto</span>
          <input
            type="range"
            min={BUDGET_MIN}
            max={BUDGET_MAX}
            step={BUDGET_STEP}
            value={props.budget}
            onChange={(e) => props.onBudget(+e.target.value)}
            style={{ flex: 1, minWidth: 60 }}
          />
          <span
            style={{
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: 13,
              fontWeight: 600,
              flex: "none",
              minWidth: 78,
              textAlign: "right",
            }}
          >
            {money(props.budget)}
          </span>
        </div>

        {/* region filter */}
        <button
          onClick={() => togglePop("region")}
          style={pillBtn(pop === "region" || props.regionFilter.length > 0)}
        >
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ flex: "none" }}>
            <path
              d="M12 21s-7-5.4-7-11a7 7 0 1114 0c0 5.6-7 11-7 11z"
              stroke="currentColor"
              strokeWidth="1.8"
            />
            <circle cx="12" cy="10" r="2.4" stroke="currentColor" strokeWidth="1.8" />
          </svg>
          {regionLabel}
        </button>

        {/* squad override */}
        <div style={{ display: "flex", alignItems: "center", gap: 7, flex: "none" }}>
          <span style={miniLabel}>Cuadrillas</span>
          <button
            onClick={() => props.onSetSquadOverride(auto ? squadValue : null)}
            style={pillBtn(!auto)}
          >
            {auto ? "Auto" : "Manual"}
          </button>
          {!auto && (
            <div
              style={{
                display: "flex",
                alignItems: "center",
                background: "#fff",
                border: "1px solid #e6e9ee",
                borderRadius: 8,
              }}
            >
              <button
                onClick={() => props.onSetSquadOverride(Math.max(1, squadValue - 1))}
                style={stepBtn}
              >
                −
              </button>
              <div
                style={{
                  minWidth: 22,
                  textAlign: "center",
                  fontFamily: "IBM Plex Mono, monospace",
                  fontSize: 12,
                  fontWeight: 600,
                }}
              >
                {squadValue}
              </div>
              <button
                onClick={() => props.onSetSquadOverride(Math.min(MAX_SQUADS, squadValue + 1))}
                style={stepBtn}
              >
                +
              </button>
            </div>
          )}
        </div>

        {/* cost basis */}
        <button onClick={() => togglePop("cost")} style={pillBtn(pop === "cost")}>
          Base de costos
        </button>

        {/* generate */}
        <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 9, minWidth: 0 }}>
          {props.planError && (
            <span
              title={props.planError}
              style={{
                fontFamily: "IBM Plex Mono, monospace",
                fontSize: 10.5,
                color: "#c2333a",
                maxWidth: 220,
                whiteSpace: "nowrap",
                overflow: "hidden",
                textOverflow: "ellipsis",
              }}
            >
              ⚠ {props.planError}
            </span>
          )}
          <button
            onClick={props.onGenerate}
            disabled={props.pointCount === 0 || props.generating}
            style={{
              flex: "none",
              display: "flex",
              alignItems: "center",
              gap: 7,
              background: props.pointCount === 0 || props.generating ? "#cdd4de" : "var(--acc,#2f64e6)",
              color: "#fff",
              border: "none",
              borderRadius: 9,
              height: 34,
              padding: "0 16px",
              fontFamily: "Public Sans, sans-serif",
              fontSize: 12.5,
              fontWeight: 700,
              cursor: props.pointCount === 0 || props.generating ? "not-allowed" : "pointer",
            }}
          >
            {props.generating ? (
              <span
                style={{
                  width: 14,
                  height: 14,
                  border: "2px solid rgba(255,255,255,.5)",
                  borderTopColor: "#fff",
                  borderRadius: "50%",
                  display: "inline-block",
                  animation: "ppspin .7s linear infinite",
                }}
              />
            ) : (
              <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
                <path
                  d="M12 3l1.6 4.8L18 9.4l-4.4 1.6L12 16l-1.6-5L6 9.4l4.4-1.6L12 3z"
                  fill="#fff"
                />
              </svg>
            )}
            {props.generating ? "Generando…" : props.previewing ? "Actualizar plan" : "Generar plan"}
          </button>
        </div>

        {/* region popover */}
        {pop === "region" && (
          <Popover>
            <div style={popHeader}>
              <span style={popTitle}>Alcaldías (INEGI)</span>
              <button onClick={props.onClearRegions} style={popClear}>
                Todas
              </button>
            </div>
            <div style={{ padding: "3px 6px 8px", maxHeight: 200, overflowY: "auto" }} className="pp-scroll">
              {props.regions.map((rg) => {
                const on = props.regionFilter.includes(rg.cve);
                return (
                  <button
                    key={rg.cve}
                    onClick={() => props.onToggleRegion(rg.cve)}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 9,
                      width: "100%",
                      border: "none",
                      background: "none",
                      cursor: "pointer",
                      padding: "6px 8px",
                      borderRadius: 8,
                    }}
                  >
                    <span
                      style={{
                        width: 15,
                        height: 15,
                        borderRadius: 4,
                        flex: "none",
                        display: "flex",
                        alignItems: "center",
                        justifyContent: "center",
                        fontSize: 10,
                        color: "#fff",
                        border: `1.5px solid ${on ? "var(--acc,#2f64e6)" : "#cdd4de"}`,
                        background: on ? "var(--acc,#2f64e6)" : "#fff",
                      }}
                    >
                      {on ? "✓" : ""}
                    </span>
                    <span style={{ flex: 1, textAlign: "left", fontSize: 12, fontWeight: 600, color: "#3a4655" }}>
                      {rg.name}
                    </span>
                    <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 9.5, color: "#aab2bd" }}>
                      {rg.count}
                    </span>
                  </button>
                );
              })}
            </div>
          </Popover>
        )}

        {/* cost-basis popover */}
        {pop === "cost" && (
          <Popover>
            <div style={popHeader}>
              <span style={popTitle}>Costo unitario</span>
              <span style={{ fontSize: 9.5, color: "#aab2bd" }}>se pasa al módulo</span>
            </div>
            <div style={{ padding: "3px 13px 8px" }}>
              {props.types
                .filter((t) => ACTIVE_ISSUE_TYPES.has(t.slug))
                .map((t) => (
                  <div
                    key={t.slug}
                    style={{
                      display: "flex",
                      alignItems: "center",
                      gap: 9,
                      padding: "7px 0",
                    }}
                  >
                    <span
                      style={{
                        width: 8,
                        height: 8,
                        borderRadius: "50%",
                        background: typeColor(t.slug),
                        flex: "none",
                      }}
                    />
                    <span style={{ flex: 1, fontSize: 12, fontWeight: 600, color: "#3a4655" }}>
                      {props.typeLabels[t.slug] ?? t.label}
                    </span>
                    <div
                      style={{
                        display: "flex",
                        alignItems: "center",
                        background: "#fff",
                        border: "1px solid #e6e9ee",
                        borderRadius: 7,
                      }}
                    >
                      <button onClick={() => props.onAdjCost(t.slug, -typeStep(t.slug))} style={stepBtn}>
                        −
                      </button>
                      <div
                        style={{
                          minWidth: 64,
                          textAlign: "center",
                          fontFamily: "IBM Plex Mono, monospace",
                          fontSize: 11,
                          fontWeight: 600,
                        }}
                      >
                        {money(props.costs[t.slug] ?? 0)}
                      </div>
                      <button onClick={() => props.onAdjCost(t.slug, typeStep(t.slug))} style={stepBtn}>
                        +
                      </button>
                    </div>
                    <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 9, color: "#b3bac5", minWidth: 30 }}>
                      /{typeUnit(t.slug)}
                    </span>
                  </div>
                ))}
            </div>
          </Popover>
        )}
      </div>
    </div>
      )}
    </>
  );
}

function Popover({ children }: { children: React.ReactNode }) {
  return (
    <div
      style={{
        position: "absolute",
        right: 14,
        bottom: 58,
        width: 288,
        background: "#fff",
        border: "1px solid #e6e9ee",
        borderRadius: 12,
        boxShadow: "0 22px 54px -26px rgba(20,30,50,.55)",
        zIndex: 6,
        overflow: "hidden",
      }}
    >
      {children}
    </div>
  );
}

const miniLabel: React.CSSProperties = {
  fontSize: 10,
  fontWeight: 700,
  color: "#8a94a3",
  textTransform: "uppercase",
  letterSpacing: ".4px",
  flex: "none",
};
const iconBtn: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#f1f4f8",
  border: "none",
  borderRadius: 8,
  width: 30,
  height: 30,
  color: "#5b6675",
  cursor: "pointer",
  flex: "none",
};
const stepBtn: React.CSSProperties = {
  width: 24,
  height: 26,
  border: "none",
  background: "none",
  color: "#5b6675",
  fontSize: 15,
  cursor: "pointer",
  lineHeight: 1,
};
const popHeader: React.CSSProperties = {
  padding: "9px 13px",
  borderBottom: "1px solid #f3f5f8",
  display: "flex",
  alignItems: "center",
  justifyContent: "space-between",
};
const popTitle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: ".5px",
  fontWeight: 700,
  color: "#7a8493",
  textTransform: "uppercase",
};
const popClear: React.CSSProperties = {
  border: "none",
  background: "none",
  color: "var(--acc,#2f64e6)",
  fontSize: 11,
  fontWeight: 700,
  cursor: "pointer",
};

const launcher: React.CSSProperties = {
  position: "absolute",
  left: 18,
  right: 404,
  bottom: 18,
  zIndex: 520,
  display: "flex",
  alignItems: "center",
  gap: 11,
  background: "rgba(255,255,255,.96)",
  backdropFilter: "blur(16px)",
  WebkitBackdropFilter: "blur(16px)",
  border: "1px solid rgba(230,233,238,.95)",
  borderRadius: 16,
  boxShadow: "0 28px 70px -34px rgba(20,30,50,.55)",
  height: 52,
  padding: "0 14px 0 11px",
  fontFamily: "Public Sans, sans-serif",
  fontSize: 13.5,
  fontWeight: 700,
  color: "#1b2430",
  cursor: "pointer",
  textAlign: "left",
};
const launcherDot: React.CSSProperties = {
  width: 30,
  height: 30,
  borderRadius: 9,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  flex: "none",
};
const launcherMeta: React.CSSProperties = {
  fontFamily: "IBM Plex Mono, monospace",
  fontSize: 10,
  fontWeight: 500,
  color: "#9aa3b1",
};

function pillBtn(active: boolean): React.CSSProperties {
  return {
    flex: "none",
    display: "flex",
    alignItems: "center",
    gap: 6,
    border: `1px solid ${active ? "var(--acc,#2f64e6)" : "#e3e7ee"}`,
    background: active ? "#eef3ff" : "#fff",
    color: active ? "var(--acc,#2f64e6)" : "#41506a",
    borderRadius: 9,
    height: 30,
    padding: "0 12px",
    fontFamily: "Public Sans, sans-serif",
    fontSize: 11.5,
    fontWeight: 600,
    cursor: "pointer",
  };
}
