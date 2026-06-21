import { useEffect } from "react";
import { Panel } from "@/components/ui/panel";
import { Button } from "@/components/ui/button";
import type { Toast } from "../lib/observationStream";

const DISMISS_MS = 8000;

// Bottom-right live-notification stack. Sits above the Leaflet zoom control (which is
// bottom-right) via the bottom offset, clear of the bottom-left dock and top-center
// sweep banner. Each toast auto-dismisses; "Ver" pans/fits the map to the new pin(s).
export function ToastStack({
  toasts,
  onAction,
  onDismiss,
}: {
  toasts: Toast[];
  onAction: (t: Toast) => void;
  onDismiss: (id: string) => void;
}) {
  if (toasts.length === 0) return null;
  return (
    <div className="pointer-events-none absolute bottom-[92px] right-[18px] z-[560] flex w-[280px] flex-col items-end gap-2">
      {toasts.map((t) => (
        <ToastRow key={t.id} toast={t} onAction={onAction} onDismiss={onDismiss} />
      ))}
    </div>
  );
}

function ToastRow({
  toast,
  onAction,
  onDismiss,
}: {
  toast: Toast;
  onAction: (t: Toast) => void;
  onDismiss: (id: string) => void;
}) {
  useEffect(() => {
    const id = setTimeout(() => onDismiss(toast.id), DISMISS_MS);
    return () => clearTimeout(id);
  }, [toast.id, onDismiss]);

  return (
    <Panel
      className="pointer-events-auto flex w-full items-center gap-2 py-2 pl-3 pr-2"
      style={{ animation: "ppup 180ms ease-out" }}
    >
      <span
        className="size-2 shrink-0 rounded-full"
        style={{ background: toast.kind === "batch" ? "#2f64e6" : "#0f9b8e" }}
      />
      <span className="flex-1 text-[12px] leading-[1.35] text-foreground">{toast.message}</span>
      <Button
        variant="secondary"
        size="sm"
        onClick={() => onAction(toast)}
        className="h-[26px] shrink-0 rounded-[7px] px-2.5 text-[11px] font-semibold"
      >
        Ver
      </Button>
      <Button
        variant="secondary"
        size="icon-xs"
        onClick={() => onDismiss(toast.id)}
        title="Descartar"
        className="size-[22px] shrink-0 rounded-[6px] bg-[#f1f4f8] text-base leading-none text-[var(--ink-2)]"
      >
        ×
      </Button>
    </Panel>
  );
}
