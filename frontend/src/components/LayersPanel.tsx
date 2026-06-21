import type { TypeCount } from "../lib/types";
import { typeColor } from "../lib/types";

interface Props {
  types: TypeCount[];
  totalObs: number;
  roiCount: number;
  showPins: boolean;
  showZones: boolean;
  showRois: boolean;
  activeTypes: Record<string, boolean>;
  lastSweepLabel: string;
  onTogglePins: () => void;
  onToggleZones: () => void;
  onToggleRois: () => void;
  onToggleType: (slug: string) => void;
  onSignOut: () => void;
}

function checkbox(on: boolean, color: string) {
  return {
    box: {
      width: 16,
      height: 16,
      borderRadius: 5,
      flex: "none" as const,
      display: "flex",
      alignItems: "center",
      justifyContent: "center",
      fontSize: 11,
      color: "#fff",
      border: `1.5px solid ${on ? color : "#cdd4de"}`,
      background: on ? color : "#fff",
    } as React.CSSProperties,
    check: on ? "✓" : "",
  };
}

const rowBtn: React.CSSProperties = {
  display: "flex",
  alignItems: "center",
  gap: 9,
  width: "100%",
  border: "none",
  background: "none",
  cursor: "pointer",
  padding: "6px 2px",
  textAlign: "left",
};
const sectionLabel: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: ".7px",
  fontWeight: 700,
  color: "#8a94a3",
  textTransform: "uppercase",
};

export function LayersPanel(props: Props) {
  const pinCb = checkbox(props.showPins, "#2f64e6");
  const zonesCb = checkbox(props.showZones, "#2f64e6");
  const roisCb = checkbox(props.showRois, "#e5484d");

  return (
    <aside
      style={{
        position: "absolute",
        top: 18,
        left: 18,
        zIndex: 500,
        width: 236,
        background: "rgba(255,255,255,.9)",
        backdropFilter: "blur(16px)",
        WebkitBackdropFilter: "blur(16px)",
        border: "1px solid rgba(230,233,238,.9)",
        borderRadius: 16,
        boxShadow: "0 18px 44px -26px rgba(20,30,50,.42),0 2px 6px -3px rgba(20,30,50,.12)",
        overflow: "hidden",
      }}
    >
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
        <div
          style={{
            width: 30,
            height: 30,
            borderRadius: 8,
            background: "#1b2430",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flex: "none",
          }}
        >
          <div style={{ width: 12, height: 12, border: "2.5px solid #fff", borderRadius: "50%", position: "relative" }}>
            <div
              style={{
                position: "absolute",
                width: 3.5,
                height: 3.5,
                background: "#fff",
                borderRadius: "50%",
                top: "50%",
                left: "50%",
                transform: "translate(-50%,-50%)",
              }}
            />
          </div>
        </div>
        <div style={{ lineHeight: 1.12, minWidth: 0 }}>
          <div style={{ fontSize: 13.5, fontWeight: 800, letterSpacing: "-.2px" }}>CityCrawl</div>
          <div style={{ fontSize: 10, color: "#9aa3b1", fontWeight: 500 }}>CDMX · Mapa de prioridades</div>
        </div>
        <div style={{ marginLeft: "auto", textAlign: "right" }}>
          <div
            style={{
              display: "flex",
              alignItems: "center",
              justifyContent: "flex-end",
              gap: 5,
              fontFamily: "IBM Plex Mono, monospace",
              fontSize: 9,
              color: "#30a46c",
              fontWeight: 600,
            }}
          >
            <span style={{ width: 6, height: 6, borderRadius: "50%", background: "#30a46c", animation: "pppulse 1.8s infinite" }} />
            EN VIVO
          </div>
          <div style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 8.5, color: "#b3bac5", marginTop: 2 }}>
            {props.lastSweepLabel}
          </div>
        </div>
      </div>

      {/* body */}
      <div style={{ padding: "12px 14px 14px" }}>
        <div style={{ ...sectionLabel, marginBottom: 8 }}>Capas</div>

        <button onClick={props.onTogglePins} style={rowBtn}>
          <span style={pinCb.box}>{pinCb.check}</span>
          <span style={{ flex: 1, textAlign: "left", fontSize: 12.5, fontWeight: 600 }}>Instancias</span>
          <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 9.5, color: "#9aa3b1" }}>{props.totalObs}</span>
        </button>

        {/* volume legend */}
        <div style={{ display: "flex", alignItems: "center", gap: 8, padding: "3px 2px 5px 27px" }}>
          <span style={{ fontSize: 9.5, color: "#aab2bd" }}>menor</span>
          <span
            style={{
              flex: 1,
              height: 8,
              borderRadius: 5,
              background: "linear-gradient(90deg,#30a46c,#f5a623,#e5484d)",
            }}
          />
          <span style={{ fontSize: 9.5, color: "#aab2bd" }}>mayor volumen</span>
        </div>

        <button onClick={props.onToggleZones} style={rowBtn}>
          <span style={zonesCb.box}>{zonesCb.check}</span>
          <span style={{ flex: 1, textAlign: "left", fontSize: 12.5, fontWeight: 600 }}>Zonas (clústeres)</span>
          <span
            style={{
              width: 16,
              height: 12,
              borderRadius: 3,
              border: "1.5px dashed #2f64e6",
              background: "rgba(47,100,230,.08)",
            }}
          />
        </button>

        <button onClick={props.onToggleRois} style={rowBtn}>
          <span style={roisCb.box}>{roisCb.check}</span>
          <span style={{ flex: 1, textAlign: "left", fontSize: 12.5, fontWeight: 600 }}>Zonas de riesgo</span>
          <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 9.5, color: "#9aa3b1" }}>{props.roiCount}</span>
        </button>
        <div style={{ paddingLeft: 27, fontSize: 9.5, color: "#aab2bd", marginTop: -2, marginBottom: 2 }}>
          externas · crimen, choques, inundación
        </div>

        <div style={{ height: 1, background: "#eef0f4", margin: "11px 0 9px" }} />
        <div style={{ ...sectionLabel, marginBottom: 5 }}>Tipos de observación</div>

        {props.types.map((t) => {
          const on = props.activeTypes[t.slug];
          return (
            <button
              key={t.slug}
              onClick={() => props.onToggleType(t.slug)}
              style={{ ...rowBtn, opacity: on ? 1 : 0.55 }}
            >
              <span
                style={{
                  width: 11,
                  height: 11,
                  borderRadius: "50%",
                  flex: "none",
                  border: `2px solid ${on ? typeColor(t.slug) : "#cdd4de"}`,
                  background: on ? typeColor(t.slug) : "#fff",
                }}
              />
              <span
                style={{
                  flex: 1,
                  textAlign: "left",
                  fontSize: 12,
                  fontWeight: 600,
                  color: on ? "#1b2430" : "#a9b1bd",
                }}
              >
                {t.label}
              </span>
              <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 9.5, color: "#aab2bd" }}>{t.count}</span>
            </button>
          );
        })}

        <div style={{ height: 1, background: "#eef0f4", margin: "11px 0 9px" }} />
        <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 10.5, color: "#7a8493" }}>
          <span
            style={{
              width: 10,
              height: 10,
              borderRadius: "50%",
              background: "#fff",
              border: "1.5px dashed #b3bac5",
              flex: "none",
            }}
          />
          Sin volumen — pin neutral
        </div>

        <button
          onClick={props.onSignOut}
          style={{
            marginTop: 12,
            width: "100%",
            height: 30,
            border: "1px solid #e6e9ee",
            background: "#fff",
            borderRadius: 9,
            fontFamily: "Public Sans, sans-serif",
            fontSize: 11.5,
            fontWeight: 600,
            color: "#5b6675",
            cursor: "pointer",
          }}
        >
          Cerrar sesión
        </button>
      </div>
    </aside>
  );
}
