import type { PlanResult } from "../lib/types";
import { typeUnit } from "../lib/types";
import { money } from "../lib/money";
import { volumeColor } from "../lib/geo";

interface Chip {
  label: string;
  run: () => void;
}

interface Props {
  previewing: boolean;
  plan: PlanResult | null;
  typeLabels: Record<string, string>;
  chips: Chip[];
  onClosePreview: () => void;
  onLocateObs: (id: string) => void;
  onLocateSquad: (lat: number, lng: number) => void;
}

const shell: React.CSSProperties = {
  position: "absolute",
  top: 18,
  right: 18,
  bottom: 18,
  width: 368,
  zIndex: 510,
  background: "rgba(255,255,255,.93)",
  backdropFilter: "blur(16px)",
  WebkitBackdropFilter: "blur(16px)",
  border: "1px solid rgba(230,233,238,.9)",
  borderRadius: 18,
  boxShadow: "0 26px 64px -32px rgba(20,30,50,.5)",
  display: "flex",
  flexDirection: "column",
  overflow: "hidden",
};

export function AgentPanel(props: Props) {
  if (props.previewing && props.plan) {
    return (
      <aside style={shell}>
        <PlanPreview
          plan={props.plan}
          typeLabels={props.typeLabels}
          onClose={props.onClosePreview}
          onLocateObs={props.onLocateObs}
          onLocateSquad={props.onLocateSquad}
        />
      </aside>
    );
  }
  return (
    <aside style={shell}>
      <AgentDefault chips={props.chips} />
    </aside>
  );
}

// ---- plan preview -----------------------------------------------------------

function PlanPreview({
  plan,
  typeLabels,
  onClose,
  onLocateObs,
  onLocateSquad,
}: {
  plan: PlanResult;
  typeLabels: Record<string, string>;
  onClose: () => void;
  onLocateObs: (id: string) => void;
  onLocateSquad: (lat: number, lng: number) => void;
}) {
  const s = plan.stats;
  const unit = typeUnit(plan.issueType);
  const typeLabel = typeLabels[plan.issueType] ?? plan.issueType;
  const maxVol = plan.topCritical.length ? Math.max(...plan.topCritical.map((t) => t.volume)) : 1;

  const stats: { value: string; label: string; bg: string; border: string; color: string }[] = [
    { value: String(s.count), label: "Baches atendidos", bg: "#eaf0ff", border: "#d9e4ff", color: "var(--acc,#2f64e6)" },
    { value: `${Math.round(s.volume)} ${unit}`, label: "Volumen total", bg: "#fdeceb", border: "#f8d8d6", color: "#e5484d" },
    { value: String(s.squads), label: "Cuadrillas", bg: "#f7f9fc", border: "#eef0f4", color: "#1b2430" },
    { value: String(s.regions), label: "Alcaldías", bg: "#f7f9fc", border: "#eef0f4", color: "#1b2430" },
  ];

  return (
    <>
      {/* header */}
      <div
        style={{
          padding: "13px 14px",
          borderBottom: "1px solid #eef0f4",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <button onClick={onClose} title="Volver al agente" style={backBtn}>
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path
              d="M15 6l-6 6 6 6"
              stroke="#5b6675"
              strokeWidth="2"
              strokeLinecap="round"
              strokeLinejoin="round"
            />
          </svg>
        </button>
        <div style={{ lineHeight: 1.15, minWidth: 0, flex: 1 }}>
          <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: "-.2px" }}>Plan de acción</div>
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
            {typeLabel} · {money(plan.budget)}
          </div>
        </div>
        <span
          style={{
            fontFamily: "IBM Plex Mono, monospace",
            fontSize: 9,
            fontWeight: 600,
            letterSpacing: ".4px",
            textTransform: "uppercase",
            color: "#1d7a4d",
            background: "#e7f6ec",
            border: "1px solid #cdecd8",
            borderRadius: 5,
            padding: "2px 7px",
            flex: "none",
          }}
        >
          Listo
        </span>
      </div>

      <div className="pp-scroll" style={{ flex: 1, overflowY: "auto", padding: "13px 14px 16px" }}>
        {/* stats grid */}
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}>
          {stats.map((st, i) => (
            <div key={i} style={{ background: st.bg, border: `1px solid ${st.border}`, borderRadius: 11, padding: "10px 12px" }}>
              <div
                style={{
                  fontFamily: "IBM Plex Mono, monospace",
                  fontSize: 17,
                  fontWeight: 600,
                  color: st.color,
                  letterSpacing: "-.5px",
                  lineHeight: 1,
                  whiteSpace: "nowrap",
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                }}
              >
                {st.value}
              </div>
              <div style={{ fontSize: 10, color: "#8a94a3", fontWeight: 500, marginTop: 6 }}>{st.label}</div>
            </div>
          ))}
        </div>

        {/* budget bar */}
        <div style={{ marginTop: 10, background: "#f7f9fc", border: "1px solid #eef0f4", borderRadius: 11, padding: "10px 12px" }}>
          <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between" }}>
            <span style={{ fontSize: 10, color: "#8a94a3", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".4px" }}>
              Presupuesto usado
            </span>
            <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 12.5, fontWeight: 600 }}>
              {money(s.spent)} · {s.budgetPct}%
            </span>
          </div>
          <div style={{ marginTop: 7, height: 6, borderRadius: 4, background: "#e7ebf1", overflow: "hidden" }}>
            <div style={{ width: `${s.budgetPct}%`, height: "100%", background: "var(--acc,#2f64e6)" }} />
          </div>
          <div style={{ fontSize: 9.5, color: "#aab2bd", marginTop: 6, fontFamily: "IBM Plex Mono, monospace" }}>
            costo estimado · placeholder del módulo
          </div>
        </div>

        {/* top critical */}
        <SectionTitle title="Más críticos" hint="clic para ubicar" />
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {plan.topCritical.map((tc) => (
            <button key={tc.id} onClick={() => onLocateObs(tc.id)} style={rowItem}>
              <span style={{ ...badge, background: "#eef1f5", color: "#41506a" }}>{tc.rank}</span>
              <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                <span style={rowLabel}>
                  {(typeLabels[tc.slug] ?? tc.slug) + (tc.zone ? " · " + tc.zone : "")}
                </span>
                <span style={rowMeta}>{`${Math.round(tc.volume)} ${typeUnit(tc.slug)} · ${money(tc.cost)}`}</span>
              </span>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: volumeColor(tc.volume, maxVol), flex: "none" }} />
            </button>
          ))}
          {plan.topCritical.length === 0 && <Empty>Sin baches dentro del presupuesto.</Empty>}
        </div>

        {/* squads */}
        <SectionTitle title="Cuadrillas (clústeres)" hint="clic para ubicar" />
        <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
          {plan.squads.map((sq) => (
            <button
              key={sq.idx}
              onClick={() => onLocateSquad(sq.centroid.lat, sq.centroid.lng)}
              style={rowItem}
            >
              <span style={{ ...badge, background: sq.color, color: "#fff" }}>C{sq.idx}</span>
              <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                <span style={rowLabel}>Cuadrilla {sq.idx}</span>
                <span style={rowMeta}>{`${sq.count} baches · ${money(sq.cost)}`}</span>
              </span>
              <span style={{ width: 9, height: 9, borderRadius: "50%", background: sq.color, flex: "none" }} />
            </button>
          ))}
          {plan.squads.length === 0 && <Empty>Sin cuadrillas asignadas.</Empty>}
        </div>
      </div>
    </>
  );
}

function SectionTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <div style={{ display: "flex", alignItems: "baseline", gap: 8, margin: "16px 0 8px" }}>
      <span style={{ fontSize: 10, letterSpacing: ".5px", fontWeight: 700, color: "#8a94a3", textTransform: "uppercase" }}>
        {title}
      </span>
      <span style={{ fontSize: 10, color: "#b3bac5" }}>{hint}</span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div style={{ fontSize: 11.5, color: "#aab2bd", padding: "6px 2px" }}>{children}</div>;
}

// ---- agent default ----------------------------------------------------------

function AgentDefault({ chips }: { chips: Chip[] }) {
  return (
    <>
      <div
        style={{
          padding: "14px 16px",
          borderBottom: "1px solid #eef0f4",
          display: "flex",
          alignItems: "center",
          gap: 10,
        }}
      >
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 9,
            background: "linear-gradient(135deg,var(--acc,#2f64e6),#6a4cf0)",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flex: "none",
          }}
        >
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
            <path d="M12 3l1.6 4.8L18 9.4l-4.4 1.6L12 16l-1.6-5L6 9.4l4.4-1.6L12 3z" fill="#fff" />
            <circle cx="18.5" cy="5.5" r="1.4" fill="#fff" />
          </svg>
        </div>
        <div style={{ lineHeight: 1.15 }}>
          <div style={{ fontSize: 14, fontWeight: 800, letterSpacing: "-.2px" }}>Agente</div>
          <div style={{ fontSize: 10.5, color: "#9aa3b1", fontWeight: 500 }}>
            Genera planes de reparación con un clic
          </div>
        </div>
      </div>

      <div className="pp-scroll" style={{ flex: 1, overflowY: "auto", padding: "16px 16px 10px" }}>
        <div style={{ display: "flex", gap: 9, marginBottom: 13 }}>
          <div
            style={{
              width: 22,
              height: 22,
              borderRadius: 7,
              background: "linear-gradient(135deg,var(--acc,#2f64e6),#6a4cf0)",
              flex: "none",
              marginTop: 1,
            }}
          />
          <div style={{ flex: 1, fontSize: 12.5, lineHeight: 1.5, color: "#3a4655" }}>
            Soy tu agente del mapa de prioridades. Elige un <strong>tipo de problema</strong>, fija
            el <strong>presupuesto</strong>, acota la <strong>región</strong> y genera un{" "}
            <strong>plan de acción</strong>: los baches más críticos dentro del presupuesto y las{" "}
            <strong>cuadrillas</strong> por clúster. Cambia presupuesto, región o cuadrillas y el
            plan se recalcula al instante.
          </div>
        </div>
        <div style={{ display: "flex", gap: 9, marginBottom: 13, opacity: 0.85 }}>
          <div style={{ width: 22, height: 22, borderRadius: 7, background: "#e7eaf0", flex: "none", marginTop: 1 }} />
          <div style={{ flex: 1, fontSize: 12, lineHeight: 1.5, color: "#8a94a3" }}>
            El comando en lenguaje natural llegará pronto. Por ahora, usa las acciones rápidas o el
            panel de configuración.
          </div>
        </div>
      </div>

      <div style={{ borderTop: "1px solid #eef0f4", padding: "10px 12px 12px", background: "rgba(255,255,255,.6)" }}>
        <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 9 }}>
          {chips.map((c) => (
            <button
              key={c.label}
              onClick={c.run}
              style={{
                background: "#f4f6f9",
                border: "1px solid #e6e9ee",
                borderRadius: 16,
                padding: "5px 10px",
                fontSize: 10.5,
                fontWeight: 500,
                color: "#41506a",
                cursor: "pointer",
                whiteSpace: "nowrap",
              }}
            >
              {c.label}
            </button>
          ))}
        </div>
        <div
          style={{
            display: "flex",
            alignItems: "center",
            gap: 8,
            background: "#f4f6f9",
            border: "1px solid #e3e7ee",
            borderRadius: 12,
            padding: "5px 5px 5px 13px",
            opacity: 0.7,
          }}
        >
          <input
            disabled
            placeholder="Describe un plan… (próximamente)"
            style={{
              flex: 1,
              border: "none",
              outline: "none",
              fontFamily: "Public Sans, sans-serif",
              fontSize: 13,
              background: "none",
              minWidth: 0,
              color: "#9aa3b1",
              cursor: "not-allowed",
            }}
          />
          <button
            disabled
            style={{
              flex: "none",
              background: "#cdd4de",
              color: "#fff",
              border: "none",
              borderRadius: 9,
              width: 34,
              height: 34,
              cursor: "not-allowed",
              display: "flex",
              alignItems: "center",
              justifyContent: "center",
            }}
          >
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
              <path d="M5 12h13M13 6l6 6-6 6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
          </button>
        </div>
      </div>
    </>
  );
}

const backBtn: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  background: "#f1f4f8",
  border: "none",
  borderRadius: 8,
  width: 30,
  height: 30,
  cursor: "pointer",
  flex: "none",
};
const rowItem: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 9,
  width: "100%",
  padding: "8px 10px",
  border: "1px solid #eef0f4",
  borderRadius: 10,
  background: "#fbfcfe",
  cursor: "pointer",
};
const badge: React.CSSProperties = {
  width: 24,
  height: 24,
  borderRadius: 7,
  fontFamily: "IBM Plex Mono, monospace",
  fontSize: 10.5,
  fontWeight: 600,
  display: "flex",
  alignItems: "center",
  justifyContent: "center",
  flex: "none",
};
const rowLabel: React.CSSProperties = {
  display: "block",
  fontSize: 12,
  fontWeight: 600,
  letterSpacing: "-.1px",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};
const rowMeta: React.CSSProperties = {
  display: "block",
  fontSize: 9.5,
  color: "#9aa3b1",
  fontFamily: "IBM Plex Mono, monospace",
  whiteSpace: "nowrap",
  overflow: "hidden",
  textOverflow: "ellipsis",
};
