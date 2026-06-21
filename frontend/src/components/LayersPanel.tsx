import type { TypeCount } from "../lib/types";
import { typeColor } from "../lib/types";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";

interface Props {
  types: TypeCount[];
  totalObs: number;
  roiCount: number;
  showPins: boolean;
  showRois: boolean;
  activeTypes: Record<string, boolean>;
  lastSweepLabel: string;
  bottom: number;
  onTogglePins: () => void;
  onToggleRois: () => void;
  onToggleType: (slug: string) => void;
  onSignOut: () => void;
}

const SECTION_LABEL = "text-[10px] font-bold uppercase tracking-[0.7px] text-muted-foreground";
const ROW = "flex h-auto w-full items-center justify-start gap-[9px] rounded-md px-0.5 py-1.5 text-left font-normal hover:bg-transparent";
const COUNT = "font-mono text-[9.5px] text-muted-foreground";

/** A square (layers) or round (types) colored toggle indicator. */
function Indicator({ on, color, round }: { on: boolean; color: string; round?: boolean }) {
  return (
    <span
      className={`flex shrink-0 items-center justify-center text-[11px] text-white ${
        round ? "size-[11px] rounded-full border-2" : "size-4 rounded-[5px] border-[1.5px]"
      }`}
      style={{
        borderColor: on ? color : "#cdd4de",
        background: on ? color : "#fff",
      }}
    >
      {on && !round ? "✓" : ""}
    </span>
  );
}

export function LayersPanel(props: Props) {
  return (
    <Panel
      className="absolute left-[18px] top-[18px] z-[500] flex w-[236px] flex-col"
      style={{ bottom: props.bottom, transition: "bottom 0.2s ease" }}
    >
      {/* header */}
      <div className="flex shrink-0 items-center gap-2.5 border-b border-[var(--line-2)] px-3.5 py-[13px]">
        <div className="flex size-[30px] shrink-0 items-center justify-center rounded-lg bg-[var(--ink)]">
          <div className="relative size-3 rounded-full border-[2.5px] border-white">
            <div className="absolute left-1/2 top-1/2 size-[3.5px] -translate-x-1/2 -translate-y-1/2 rounded-full bg-white" />
          </div>
        </div>
        <div className="min-w-0 leading-[1.12]">
          <div className="text-[13.5px] font-extrabold tracking-[-0.2px]">CityCrawl</div>
          <div className="text-[10px] font-medium text-muted-foreground">CDMX · Mapa de prioridades</div>
        </div>
        <div className="ml-auto text-right">
          <div className="flex items-center justify-end gap-[5px] font-mono text-[9px] font-semibold text-[var(--success)]">
            <span className="size-1.5 animate-[pppulse_1.8s_infinite] rounded-full bg-[var(--success)]" />
            EN VIVO
          </div>
          <div className="mt-0.5 font-mono text-[8.5px] text-[#b3bac5]">{props.lastSweepLabel}</div>
        </div>
      </div>

      {/* body */}
      <div className="pp-scroll min-h-0 flex-1 overflow-y-auto px-3.5 pb-3.5 pt-3">
        <div className={`${SECTION_LABEL} mb-2`}>Capas</div>

        <Button variant="ghost" onClick={props.onTogglePins} className={ROW}>
          <Indicator on={props.showPins} color="#2f64e6" />
          <span className="flex-1 text-left text-[12.5px] font-semibold">Instancias</span>
          <span className={COUNT}>{props.totalObs}</span>
        </Button>

        <Button variant="ghost" onClick={props.onToggleRois} className={ROW}>
          <Indicator on={props.showRois} color="#e5484d" />
          <span className="flex-1 text-left text-[12.5px] font-semibold">Zonas de riesgo</span>
          <span className={COUNT}>{props.roiCount}</span>
        </Button>
        <div className="-mt-0.5 mb-0.5 pl-[27px] text-[9.5px] text-[#aab2bd]">
          externas · crimen, choques, inundación
        </div>

        <Separator className="my-[10px] bg-[var(--line-2)]" />
        <div className={`${SECTION_LABEL} mb-[5px]`}>Tipos de observación</div>

        {props.types.map((t) => {
          const on = props.activeTypes[t.slug];
          return (
            <div key={t.slug}>
              <Button
                variant="ghost"
                onClick={() => props.onToggleType(t.slug)}
                className={`${ROW} ${on ? "opacity-100" : "opacity-55"}`}
              >
                <Indicator on={on} color={typeColor(t.slug)} round />
                <span
                  className="flex-1 text-left text-[12px] font-semibold"
                  style={{ color: on ? "#1b2430" : "#a9b1bd" }}
                >
                  {t.label}
                </span>
                <span className="font-mono text-[9.5px] text-[#aab2bd]">{t.count}</span>
              </Button>
              {t.slug === "pothole" && (
                <div className="-mt-0.5 flex items-center gap-1.5 pb-1 pl-[27px]">
                  <span className="text-[9px] text-[#aab2bd]">menor</span>
                  <span className="h-1.5 flex-1 rounded-full bg-[linear-gradient(90deg,#30a46c,#f5a623,#e5484d)]" />
                  <span className="text-[9px] text-[#aab2bd]">mayor área</span>
                </div>
              )}
            </div>
          );
        })}

        <Separator className="my-[10px] bg-[var(--line-2)]" />
        <div className="flex items-center gap-2 text-[10.5px] text-[#7a8493]">
          <span className="size-2.5 shrink-0 rounded-full border-[1.5px] border-dashed border-[#b3bac5] bg-white" />
          Sin volumen — pin neutral
        </div>

        <Button
          variant="outline"
          onClick={props.onSignOut}
          className="mt-3 h-[30px] w-full rounded-[9px] text-[11.5px] font-semibold text-[var(--ink-2)]"
        >
          Cerrar sesión
        </Button>
      </div>
    </Panel>
  );
}
