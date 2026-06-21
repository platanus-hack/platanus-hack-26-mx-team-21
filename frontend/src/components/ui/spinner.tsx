import { cn } from "@/lib/utils";

export function Spinner({
  className,
  size = 18,
}: {
  className?: string;
  size?: number;
}) {
  return (
    <span
      role="status"
      aria-label="Cargando"
      className={cn(
        "inline-block animate-spin rounded-full border-[2.5px] border-[var(--line)] border-t-[var(--brand)]",
        className,
      )}
      style={{ width: size, height: size }}
    />
  );
}
