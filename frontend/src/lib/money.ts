// MXN currency formatter — mirrors the reference `$()` (strip the `MX$` prefix).
const fmt = new Intl.NumberFormat("es-MX", {
  style: "currency",
  currency: "MXN",
  maximumFractionDigits: 0,
});

export function money(value: number): string {
  return fmt.format(value).replace("MX$", "$");
}

// Compact money for tight chips, e.g. $3.0M
export function moneyShort(value: number): string {
  if (value >= 1_000_000) return "$" + (value / 1_000_000).toFixed(1).replace(/\.0$/, "") + "M";
  if (value >= 1_000) return "$" + Math.round(value / 1_000) + "k";
  return money(value);
}
