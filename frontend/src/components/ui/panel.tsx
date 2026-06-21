import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Panel — the shared floating-surface primitive for the map overlays
 * (layers panel, agent panel, analysis dock, observation card, popovers).
 * Encodes the one consistent surface look; callers pass position/size via className.
 */
const Panel = React.forwardRef<HTMLDivElement, React.ComponentProps<"div">>(
  function Panel({ className, ...props }, ref) {
    return (
      <div
        ref={ref}
        data-slot="panel"
        className={cn(
          "overflow-hidden rounded-[16px] border border-[var(--line)]/90 bg-card text-foreground",
          "shadow-[0_24px_60px_-30px_rgba(20,30,50,0.5),0_2px_6px_-3px_rgba(20,30,50,0.12)]",
          className,
        )}
        {...props}
      />
    );
  },
);

/** Consistent panel header row: padded, with a hairline bottom border. */
function PanelHeader({ className, ...props }: React.ComponentProps<"div">) {
  return (
    <div
      data-slot="panel-header"
      className={cn(
        "flex items-center gap-2.5 border-b border-[var(--line-2)] px-3.5 py-3",
        className,
      )}
      {...props}
    />
  );
}

export { Panel, PanelHeader };
