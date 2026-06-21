/** Token names available as CSS variables (see design-system/tokens.css).
 *  Use as `var(${tokens.brand})` or in inline styles when a utility class
 *  is not appropriate. */
export const tokens = {
  brand: "--brand",
  violet: "--violet",
  ink: "--ink",
  ink2: "--ink-2",
  mutedInk: "--muted-ink",
  bg: "--bg",
  card: "--card",
  line: "--line",
  success: "--success",
  danger: "--danger",
  warning: "--warning",
  fontDisplay: "--font-display",
  fontMono: "--font-mono",
  radius: "--radius",
} as const;
