// Per-risk-dimension presentation (app-owned) for the external-dataset ROI layers.
// Single source of truth for layer color + Spanish label. DIMENSION_ORDER defines
// the order rows appear in the Layers panel.

export interface DimensionPresentation {
  label: string;
  color: string;
  deferred?: boolean; // shown disabled until its data lands (needs geocoding)
}

export const DIMENSION_PRESENTATION: Record<string, DimensionPresentation> = {
  crash: { label: "Choques", color: "#e5484d" },
  flooding: { label: "Inundación", color: "#2f64e6" },
  road_surface: { label: "Bacheo", color: "#f5a623" },
  crime: { label: "Crimen", color: "#7c3aed" },
  violation: { label: "Infracciones", color: "#0f9b8e", deferred: true },
};

export const DIMENSION_ORDER = ["crash", "flooding", "road_surface", "crime", "violation"];
export const NEUTRAL_DIMENSION_COLOR = "#9aa3b1";

export function dimensionColor(dim: string): string {
  return DIMENSION_PRESENTATION[dim]?.color ?? NEUTRAL_DIMENSION_COLOR;
}
export function dimensionLabel(dim: string): string {
  return DIMENSION_PRESENTATION[dim]?.label ?? dim;
}
