import { useEffect, useRef } from "react";
import type { ObservationDetail } from "../lib/types";
import { typeColor } from "../lib/types";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Spinner } from "@/components/ui/spinner";

interface Props {
  detail: ObservationDetail | null;
  loading: boolean;
  onClose: () => void;
  /** Reports the card's rendered height so the layers panel can lift clear of it. */
  onHeight?: (h: number) => void;
}

const SHELL = "absolute left-[18px] bottom-[18px] z-[530] w-[300px]";

function agoLabel(iso: string): string {
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const mins = Math.max(0, Math.round((Date.now() - t) / 60000));
  if (mins < 60) return `hace ${mins} min`;
  const hrs = Math.round(mins / 60);
  if (hrs < 48) return `hace ${hrs} h`;
  return `hace ${Math.round(hrs / 24)} d`;
}

export function ObservationCard({ detail, loading, onClose, onHeight }: Props) {
  const ref = useRef<HTMLDivElement>(null);

  // Keep the layers panel informed of our height (varies between the loading
  // and loaded states, and with content) so it can stay lifted clear of us.
  useEffect(() => {
    const el = ref.current;
    if (!el || !onHeight) return;
    onHeight(el.offsetHeight);
    const ro = new ResizeObserver(() => onHeight(el.offsetHeight));
    ro.observe(el);
    return () => ro.disconnect();
  }, [onHeight, loading, detail]);

  if (loading || !detail) {
    return (
      <Panel ref={ref} className={SHELL}>
        <div className="h-[5px] bg-[var(--line-strong)]" />
        <div className="flex items-center gap-2.5 p-[18px] text-[12.5px] text-muted-foreground">
          <Spinner size={18} />
          Cargando observación…
        </div>
      </Panel>
    );
  }

  const d = detail;
  const color = typeColor(d.slug);
  const pending = d.state === "pending";
  const fact = d.qty != null ? `${d.qty} ${d.unit ?? ""}`.trim() : "1 pza";
  const bbox = d.imageBbox;

  return (
    <Panel ref={ref} className={SHELL}>
      <div className="h-[5px]" style={{ background: color }} />
      <div className="px-3.5 pt-[13px] pb-3.5">
        <div className="flex items-start justify-between gap-2.5">
          <div className="min-w-0">
            <div className="flex items-center gap-[7px]">
              <span className="text-sm font-bold tracking-[-0.2px]">{d.label}</span>
              <Badge variant={pending ? "statusPending" : "statusConfirmed"} className="rounded-[4px]">
                {pending ? "pendiente" : "evaluada"}
              </Badge>
            </div>
            <div className="mt-0.5 font-mono text-[10.5px] text-[var(--muted-ink-2)]">
              {`OBS · ${d.lat.toFixed(4)}, ${d.lng.toFixed(4)}`}
            </div>
          </div>
          <Button
            variant="secondary"
            size="icon-xs"
            onClick={onClose}
            className="size-[25px] shrink-0 rounded-[7px] bg-[#f1f4f8] text-base leading-none text-[var(--ink-2)]"
          >
            ×
          </Button>
        </div>

        <div className="mt-3 flex gap-2">
          <Stat label="Volumen" value={fact} valueColor={color} />
          <Stat label="Confianza" value={d.conf != null ? `${Math.round(d.conf * 100)}%` : "—"} />
        </div>

        <div className="mt-[11px] flex gap-2.5">
          <div className="relative h-[55px] w-[74px] shrink-0 overflow-hidden rounded-[9px] border border-[var(--line-2)] bg-[repeating-linear-gradient(45deg,#eef1f5,#eef1f5_6px,#e7ebf1_6px,#e7ebf1_12px)]">
            {bbox && (
              <div
                className="absolute rounded-[3px] shadow-[0_0_0_9999px_rgba(27,36,48,0.08)]"
                style={{
                  border: `1.5px solid ${color}`,
                  left: `${bbox.x * 100}%`,
                  top: `${bbox.y * 100}%`,
                  width: `${bbox.w * 100}%`,
                  height: `${bbox.h * 100}%`,
                }}
              />
            )}
            <div className="absolute inset-x-0 bottom-0 bg-white/70 py-px text-center font-mono text-[7px] text-muted-foreground">
              cuadro
            </div>
          </div>
          <div className="min-w-0 flex-1 font-mono text-[9.5px] leading-[1.55] text-[#7a8493]">
            <div>{d.recordingId ?? "rec —"}</div>
            <div>{d.frameRef ? `cuadro ${d.frameRef}` : "cuadro —"}</div>
            <div className="text-[#aab2bd]">{d.detector}</div>
          </div>
        </div>

        <div className="mt-2.5 flex flex-wrap gap-1">
          <Badge variant="tag">conf ×{d.confirmations}</Badge>
          <Badge variant="tag">fallas {d.misses}</Badge>
          <Badge variant="tag">{agoLabel(d.observedAt)}</Badge>
        </div>

        <div className="mt-[9px] flex items-center gap-1.5 border-t border-[var(--surface-2)] pt-2 text-[11px] text-[var(--ink-2)]">
          <svg width="13" height="13" viewBox="0 0 24 24" fill="none" className="shrink-0">
            <path d="M12 21s-7-5.4-7-11a7 7 0 1114 0c0 5.6-7 11-7 11z" stroke="#9aa3b1" strokeWidth="1.8" />
            <circle cx="12" cy="10" r="2.4" stroke="#9aa3b1" strokeWidth="1.8" />
          </svg>
          {[d.districtName, d.zone].filter(Boolean).join(" · ") || "Sin ubicación"}
        </div>

        <Button
          disabled
          variant="ghost"
          title="La vista de recorrido llegará pronto"
          className="mt-[11px] h-[38px] w-full gap-2 rounded-[10px] bg-[var(--bg)] text-[12px] font-bold text-[var(--muted-ink-2)] disabled:opacity-100"
        >
          <svg width="14" height="14" viewBox="0 0 24 24" fill="none">
            <path d="M8 5l11 7-11 7V5z" fill="#9aa3b1" />
          </svg>
          Ver recorrido {d.sweep} (próximamente)
        </Button>
      </div>
    </Panel>
  );
}

function Stat({ label, value, valueColor }: { label: string; value: string; valueColor?: string }) {
  return (
    <div className="flex-1 rounded-[9px] bg-[var(--surface-1)] px-2.5 py-2">
      <div className="text-[9.5px] font-semibold uppercase tracking-wide text-[var(--muted-ink-2)]">{label}</div>
      <div className="mt-[3px] font-mono text-[12.5px] font-semibold" style={valueColor ? { color: valueColor } : undefined}>
        {value}
      </div>
    </div>
  );
}
