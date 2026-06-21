import { money } from "../lib/money";

export interface PlanHistoryItem {
  id: string;
  budget: number;
  status: string; // succeeded | running | queued | failed | cancelled
  createdAt: string;
  count: number | null; // baches in the plan (local plans), null for live runs
}

interface Props {
  items: PlanHistoryItem[];
  activeId: string | null;
  dockOpen: boolean;
  onOpen: (id: string) => void;
}

function statusInfo(status: string): { label: string; color: string; bg: string; border: string } {
  switch (status) {
    case "succeeded":
      return { label: "Listo", color: "#1d7a4d", bg: "#e7f6ec", border: "#cdecd8" };
    case "running":
      return { label: "En curso", color: "#2f64e6", bg: "#eaf0ff", border: "#d9e4ff" };
    case "queued":
      return { label: "En cola", color: "#8a6d00", bg: "#fff6e0", border: "#f5e3b0" };
    case "failed":
      return { label: "Falló", color: "#e5484d", bg: "#fdeceb", border: "#f8d8d6" };
    case "cancelled":
      return { label: "Cancelado", color: "#7a8493", bg: "#eef1f5", border: "#dde2e9" };
    default:
      return { label: status, color: "#7a8493", bg: "#eef1f5", border: "#dde2e9" };
  }
}

export function HistoryPopover(props: Props) {
  return (
    <div
      style={{
        position: "absolute",
        left: 18,
        right: 404,
        bottom: props.dockOpen ? 230 : 70,
        zIndex: 540,
        display: "flex",
        justifyContent: "center",
        pointerEvents: "none",
      }}
    >
      <div
        style={{
          pointerEvents: "auto",
          width: 312,
          background: "#fff",
          border: "1px solid #e6e9ee",
          borderRadius: 14,
          boxShadow: "0 26px 60px -28px rgba(20,30,50,.55)",
          overflow: "hidden",
          animation: "ppup .16s ease",
        }}
      >
        <div style={{ padding: "11px 14px", borderBottom: "1px solid #f3f5f8" }}>
          <div style={{ fontSize: 12, fontWeight: 800 }}>Planes anteriores</div>
          <div style={{ fontSize: 10, color: "#9aa3b1", marginTop: 1 }}>
            selecciona uno para abrir su vista previa
          </div>
        </div>
        <div className="pp-scroll" style={{ maxHeight: 248, overflowY: "auto", padding: 6 }}>
          {props.items.map((r) => {
            const si = statusInfo(r.status);
            const active = r.id === props.activeId;
            return (
              <button
                key={r.id}
                onClick={() => props.onOpen(r.id)}
                style={{
                  width: "100%",
                  display: "flex",
                  alignItems: "center",
                  gap: 10,
                  padding: "8px 9px",
                  border: "none",
                  borderRadius: 9,
                  cursor: "pointer",
                  background: active ? "#f4f7ff" : "none",
                }}
              >
                <span
                  style={{
                    width: 8,
                    height: 8,
                    borderRadius: "50%",
                    background: "var(--acc,#2f64e6)",
                    flex: "none",
                  }}
                />
                <span style={{ flex: 1, minWidth: 0, textAlign: "left" }}>
                  <span style={{ display: "block", fontSize: 12, fontWeight: 600, letterSpacing: "-.1px" }}>
                    Plan de acción
                  </span>
                  <span style={{ display: "block", fontSize: 10, color: "#9aa3b1", fontFamily: "IBM Plex Mono, monospace" }}>
                    {money(r.budget)}
                    {r.count != null ? ` · ${r.count} baches` : ""}
                  </span>
                </span>
                <span
                  style={{
                    fontFamily: "IBM Plex Mono, monospace",
                    fontSize: 9,
                    fontWeight: 600,
                    letterSpacing: ".4px",
                    textTransform: "uppercase",
                    color: si.color,
                    background: si.bg,
                    border: `1px solid ${si.border}`,
                    borderRadius: 5,
                    padding: "2px 7px",
                    flex: "none",
                  }}
                >
                  {si.label}
                </span>
              </button>
            );
          })}
          {props.items.length === 0 && (
            <div style={{ fontSize: 11.5, color: "#aab2bd", padding: "10px 9px" }}>
              Aún no hay planes.
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
