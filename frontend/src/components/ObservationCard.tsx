import type { ObservationDetail } from "../lib/types";
import { typeColor } from "../lib/types";

interface Props {
  detail: ObservationDetail | null;
  loading: boolean;
  onClose: () => void;
}

function agoLabel(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 60) return `hace ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `hace ${hrs} h`;
  return `hace ${Math.round(hrs / 24)} d`;
}

export function ObservationCard({ detail, loading, onClose }: Props) {
  if (loading || !detail) {
    return (
      <div style={shell}>
        <div style={{ height: 5, background: "#cdd4de" }} />
        <div style={{ padding: 18, color: "#8a94a3", fontSize: 12.5, display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ width: 18, height: 18, border: "2.5px solid #e3e7ee", borderTopColor: "#2f64e6", borderRadius: "50%", animation: "ppspin .7s linear infinite", display: "inline-block" }} />
          Cargando observación…
        </div>
      </div>
    );
  }

  const d = detail;
  const color = typeColor(d.slug);
  const pending = d.state === "pending";
  const fact = d.qty != null ? `${d.qty} ${d.unit ?? ""}`.trim() : "1 pza";
  const bbox = d.imageBbox;

  return (
    <div style={shell}>
      <div style={{ height: 5, background: color }} />
      <div style={{ padding: "13px 14px 14px" }}>
        <div style={{ display: "flex", alignItems: "flex-start", justifyContent: "space-between", gap: 10 }}>
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
              <span style={{ fontSize: 14, fontWeight: 700, letterSpacing: "-.2px" }}>{d.label}</span>
              <span
                style={{
                  fontFamily: "IBM Plex Mono, monospace",
                  fontSize: 8,
                  fontWeight: 600,
                  letterSpacing: ".3px",
                  textTransform: "uppercase",
                  borderRadius: 4,
                  padding: "1px 5px",
                  color: pending ? "#7a8493" : "#1d7a4d",
                  background: pending ? "#eef1f5" : "#e7f6ec",
                  border: pending ? "1px dashed #cdd4de" : "1px solid #cdecd8",
                }}
              >
                {pending ? "pendiente" : "evaluada"}
              </span>
            </div>
            <div style={{ fontSize: 10.5, color: "#9aa3b1", fontFamily: "IBM Plex Mono, monospace", marginTop: 2 }}>
              {`OBS · ${d.lat.toFixed(4)}, ${d.lng.toFixed(4)}`}
            </div>
          </div>
          <button
            onClick={onClose}
            style={{ border: "none", background: "#f1f4f8", width: 25, height: 25, borderRadius: 7, cursor: "pointer", color: "#5b6675", fontSize: 14, lineHeight: 1, flex: "none" }}
          >
            ×
          </button>
        </div>

        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <div style={statBox}>
            <div style={statLabel}>Volumen</div>
            <div style={{ ...statVal, color }}>{fact}</div>
          </div>
          <div style={statBox}>
            <div style={statLabel}>Confianza</div>
            <div style={statVal}>{d.conf != null ? `${Math.round(d.conf * 100)}%` : "—"}</div>
          </div>
        </div>

        <div style={{ display: "flex", gap: 10, marginTop: 11 }}>
          <div
            style={{
              width: 74,
              height: 55,
              borderRadius: 9,
              flex: "none",
              overflow: "hidden",
              background:
                "repeating-linear-gradient(45deg,#eef1f5,#eef1f5 6px,#e7ebf1 6px,#e7ebf1 12px)",
              border: "1px solid #e6e9ee",
              position: "relative",
            }}
          >
            {bbox && (
              <div
                style={{
                  position: "absolute",
                  border: `1.5px solid ${color}`,
                  borderRadius: 3,
                  boxShadow: "0 0 0 9999px rgba(27,36,48,.08)",
                  left: `${bbox.x * 100}%`,
                  top: `${bbox.y * 100}%`,
                  width: `${bbox.w * 100}%`,
                  height: `${bbox.h * 100}%`,
                }}
              />
            )}
            <div style={{ position: "absolute", bottom: 0, left: 0, right: 0, fontFamily: "IBM Plex Mono, monospace", fontSize: 7, color: "#8a94a3", textAlign: "center", padding: "1px 0", background: "rgba(255,255,255,.7)" }}>
              cuadro
            </div>
          </div>
          <div style={{ flex: 1, minWidth: 0, fontFamily: "IBM Plex Mono, monospace", fontSize: 9.5, color: "#7a8493", lineHeight: 1.55 }}>
            <div>{d.recordingId ?? "rec —"}</div>
            <div>{d.frameRef ? `cuadro ${d.frameRef}` : "cuadro —"}</div>
            <div style={{ color: "#aab2bd" }}>{d.detector}</div>
          </div>
        </div>

        <div style={{ display: "flex", flexWrap: "wrap", gap: 4, marginTop: 10 }}>
          <Chip>conf ×{d.confirmations}</Chip>
          <Chip>fallas {d.misses}</Chip>
          <Chip>{agoLabel(d.observedAt)}</Chip>
        </div>

        <div style={{ marginTop: 9, borderTop: "1px solid #f3f5f8", paddingTop: 8, display: "flex", alignItems: "center", gap: 6, fontSize: 11, color: "#5b6675" }}>
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" style={{ flex: "none" }}>
            <path d="M12 21s-7-5.4-7-11a7 7 0 1114 0c0 5.6-7 11-7 11z" stroke="#9aa3b1" strokeWidth="1.8" />
            <circle cx="12" cy="10" r="2.4" stroke="#9aa3b1" strokeWidth="1.8" />
          </svg>
          {[d.districtName, d.zone].filter(Boolean).join(" · ") || "Sin ubicación"}
        </div>

        <button
          disabled
          title="La vista de recorrido llegará pronto"
          style={{
            marginTop: 11,
            width: "100%",
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            gap: 8,
            background: "#eef1f5",
            color: "#9aa3b1",
            border: "none",
            borderRadius: 10,
            height: 38,
            fontFamily: "Public Sans, sans-serif",
            fontSize: 12,
            fontWeight: 700,
            cursor: "not-allowed",
          }}
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M8 5l11 7-11 7V5z" fill="#9aa3b1" />
          </svg>
          Ver recorrido {d.sweep} (próximamente)
        </button>
      </div>
    </div>
  );
}

function Chip({ children }: { children: React.ReactNode }) {
  return (
    <span style={{ fontFamily: "IBM Plex Mono, monospace", fontSize: 9, color: "#41506a", background: "#eef1f5", borderRadius: 5, padding: "3px 7px" }}>
      {children}
    </span>
  );
}

const shell: React.CSSProperties = {
  position: "absolute",
  left: 18,
  bottom: 18,
  zIndex: 530,
  width: 300,
  background: "#fff",
  border: "1px solid #e6e9ee",
  borderRadius: 14,
  boxShadow: "0 24px 60px -30px rgba(20,30,50,.5)",
  overflow: "hidden",
};
const statBox: React.CSSProperties = { flex: 1, background: "#f7f9fc", borderRadius: 9, padding: "8px 10px" };
const statLabel: React.CSSProperties = { fontSize: 9.5, color: "#9aa3b1", fontWeight: 600, textTransform: "uppercase", letterSpacing: ".4px" };
const statVal: React.CSSProperties = { fontFamily: "IBM Plex Mono, monospace", fontSize: 12.5, fontWeight: 600, marginTop: 3 };
