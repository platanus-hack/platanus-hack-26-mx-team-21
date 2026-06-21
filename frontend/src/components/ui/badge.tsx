import * as React from "react"
import { cva, type VariantProps } from "class-variance-authority"
import { Slot } from "radix-ui"

import { cn } from "@/lib/utils"

const badgeVariants = cva(
  "inline-flex w-fit shrink-0 items-center justify-center gap-1 overflow-hidden rounded-full border border-transparent px-2 py-0.5 text-xs font-medium whitespace-nowrap transition-[color,box-shadow] focus-visible:border-ring focus-visible:ring-[3px] focus-visible:ring-ring/50 aria-invalid:border-destructive aria-invalid:ring-destructive/20 dark:aria-invalid:ring-destructive/40 [&>svg]:pointer-events-none [&>svg]:size-3",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground [a&]:hover:bg-primary/90",
        secondary:
          "bg-secondary text-secondary-foreground [a&]:hover:bg-secondary/90",
        destructive:
          "bg-destructive text-white focus-visible:ring-destructive/20 dark:bg-destructive/60 dark:focus-visible:ring-destructive/40 [a&]:hover:bg-destructive/90",
        outline:
          "border-border text-foreground [a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        ghost: "[a&]:hover:bg-accent [a&]:hover:text-accent-foreground",
        link: "text-primary underline-offset-4 [a&]:hover:underline",
        statusPending:
          "border border-dashed border-[var(--line-strong)] bg-[var(--surface-2)] text-[var(--muted-ink)] font-mono text-[8px] font-semibold uppercase tracking-wide",
        statusConfirmed:
          "border border-[var(--success-line)] bg-[var(--success-soft)] text-[var(--success-ink)] font-mono text-[8px] font-semibold uppercase tracking-wide",
        type: "border border-[var(--line)] bg-[var(--surface-1)] text-[var(--ink-2)] font-mono text-[8px] font-semibold uppercase tracking-wide",
        // plan / run lifecycle states — mono, square-ish, used by the dock & history
        statusReady:
          "rounded-[5px] border border-[var(--success-line)] bg-[var(--success-soft)] text-[var(--success-ink)] px-[7px] py-[2px] font-mono text-[9px] font-semibold uppercase tracking-wide",
        statusRunning:
          "rounded-[5px] border border-[var(--brand-line)] bg-[var(--brand-soft)] text-[var(--brand)] px-[7px] py-[2px] font-mono text-[9px] font-semibold uppercase tracking-wide",
        statusQueued:
          "rounded-[5px] border border-[#f5e3b0] bg-[var(--warning-soft)] text-[#8a6d00] px-[7px] py-[2px] font-mono text-[9px] font-semibold uppercase tracking-wide",
        statusFailed:
          "rounded-[5px] border border-[var(--danger-line)] bg-[var(--danger-soft)] text-[var(--danger)] px-[7px] py-[2px] font-mono text-[9px] font-semibold uppercase tracking-wide",
        statusNeutral:
          "rounded-[5px] border border-[#dde2e9] bg-[var(--bg)] text-[#7a8493] px-[7px] py-[2px] font-mono text-[9px] font-semibold uppercase tracking-wide",
        // mono "tag" chip (counters, conf ×N, ago labels, rank badges)
        tag: "rounded-[5px] bg-[var(--bg)] text-[#41506a] px-[7px] py-[3px] font-mono text-[9px] font-normal normal-case tracking-normal",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  }
)

function Badge({
  className,
  variant = "default",
  asChild = false,
  ...props
}: React.ComponentProps<"span"> &
  VariantProps<typeof badgeVariants> & { asChild?: boolean }) {
  const Comp = asChild ? Slot.Root : "span"

  return (
    <Comp
      data-slot="badge"
      data-variant={variant}
      className={cn(badgeVariants({ variant }), className)}
      {...props}
    />
  )
}

export { Badge, badgeVariants }
