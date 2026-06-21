import { money } from "../lib/money";
import type { VariantProps } from "class-variance-authority";
import { Panel } from "@/components/ui/panel";
import { Badge, badgeVariants } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";

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

type BadgeVariant = NonNullable<VariantProps<typeof badgeVariants>["variant"]>;

function statusInfo(status: string): { label: string; variant: BadgeVariant } {
  switch (status) {
    case "succeeded":
      return { label: "Listo", variant: "statusReady" };
    case "running":
      return { label: "En curso", variant: "statusRunning" };
    case "queued":
      return { label: "En cola", variant: "statusQueued" };
    case "failed":
      return { label: "Falló", variant: "statusFailed" };
    case "cancelled":
      return { label: "Cancelado", variant: "statusNeutral" };
    default:
      return { label: status, variant: "statusNeutral" };
  }
}

export function HistoryPopover(props: Props) {
  return (
    <div
      className="pointer-events-none absolute left-[18px] right-[404px] z-[540] flex justify-center"
      style={{ bottom: props.dockOpen ? 230 : 70 }}
    >
      <Panel className="pointer-events-auto w-[312px] animate-[ppup_0.16s_ease] rounded-[14px]">
        <div className="border-b border-[var(--surface-2)] px-3.5 py-[11px]">
          <div className="text-[12px] font-extrabold">Planes anteriores</div>
          <div className="mt-px text-[10px] text-muted-foreground">
            selecciona uno para abrir su vista previa
          </div>
        </div>
        <div className="pp-scroll max-h-[248px] overflow-y-auto p-1.5">
          {props.items.map((r) => {
            const si = statusInfo(r.status);
            const active = r.id === props.activeId;
            return (
              <Button
                key={r.id}
                variant="ghost"
                onClick={() => props.onOpen(r.id)}
                className={`flex h-auto w-full items-center justify-start gap-2.5 rounded-[9px] px-[9px] py-2 ${
                  active ? "bg-[#f4f7ff]" : ""
                }`}
              >
                <span className="size-2 shrink-0 rounded-full bg-primary" />
                <span className="min-w-0 flex-1 text-left">
                  <span className="block text-[12px] font-semibold tracking-[-0.1px]">
                    Plan de acción
                  </span>
                  <span className="block font-mono text-[10px] font-normal text-muted-foreground">
                    {money(r.budget)}
                    {r.count != null ? ` · ${r.count} baches` : ""}
                  </span>
                </span>
                <Badge variant={si.variant} className="shrink-0">
                  {si.label}
                </Badge>
              </Button>
            );
          })}
          {props.items.length === 0 && (
            <div className="px-[9px] py-2.5 text-[11.5px] text-[#aab2bd]">
              Aún no hay planes.
            </div>
          )}
        </div>
      </Panel>
    </div>
  );
}
