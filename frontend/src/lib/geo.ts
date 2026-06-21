// Geometry helpers — distance, clustering (k-means-style stand-in for the module's
// DBSCAN), convex hull (monotone chain), and the volume color/size ramp.

export function haversine(la1: number, lo1: number, la2: number, lo2: number): number {
  const R = 6371000;
  const dLa = ((la2 - la1) * Math.PI) / 180;
  const dLo = ((lo2 - lo1) * Math.PI) / 180;
  const a =
    Math.sin(dLa / 2) ** 2 +
    Math.cos((la1 * Math.PI) / 180) * Math.cos((la2 * Math.PI) / 180) * Math.sin(dLo / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

// ---- Green→amber→red ramp ---------------------------------------------------
// Shared 3-stop ramp. `volumeColor` colors a pin by its volume metadata relative
// to the in-view max (§4.1). `priorityColor` colors a cluster region by the model-
// provided weight (0..1) — the app never derives this, it only paints it.
const RAMP_STOPS: [number, number, number][] = [
  [48, 164, 108],
  [245, 166, 35],
  [229, 72, 77],
];

function rampColor(t: number): string {
  const x = Math.min(0.999, Math.max(0, t)) * (RAMP_STOPS.length - 1);
  const i = Math.floor(x);
  const f = x - i;
  const a = RAMP_STOPS[i];
  const b = RAMP_STOPS[i + 1] || a;
  return `rgb(${Math.round(a[0] + (b[0] - a[0]) * f)},${Math.round(
    a[1] + (b[1] - a[1]) * f,
  )},${Math.round(a[2] + (b[2] - a[2]) * f)})`;
}

export function volumeColor(v: number, max: number): string {
  return rampColor(max > 0 ? v / max : 0);
}

// Cluster-region color from the model's normalized weight (0..1). Higher = hotter.
export function priorityColor(weight: number): string {
  return rampColor(weight);
}

// ---- Clustering + hulls (§2.3.4, §4.2) --------------------------------------

export interface LatLng {
  lat: number;
  lng: number;
}

export function centroidOf(pts: LatLng[]): LatLng {
  if (!pts.length) return { lat: 0, lng: 0 };
  let lat = 0;
  let lng = 0;
  for (const p of pts) {
    lat += p.lat;
    lng += p.lng;
  }
  return { lat: lat / pts.length, lng: lng / pts.length };
}

// Bounded radius (meters) for drawing a cluster as a soft region. Uses the 75th-
// percentile member→centroid distance so a couple of far-flung members don't blow
// the blob up, then clamps to a sane on-map range. Keeps regions clean, never slivers.
export function clusterRadiusMeters(members: LatLng[], centroid: LatLng): number {
  if (members.length < 2) return 380;
  const ds = members
    .map((m) => haversine(m.lat, m.lng, centroid.lat, centroid.lng))
    .sort((a, b) => a - b);
  const p75 = ds[Math.min(ds.length - 1, Math.floor(ds.length * 0.75))];
  return Math.max(360, Math.min(2200, p75 * 1.25));
}

// Deterministic k-means-style clustering on lat/lng. Returns, for each non-empty
// cluster, the indices of its member points. Deterministic seeding (evenly spaced
// over the lng/lat sort order) keeps rendering stable across recomputes.
export function clusterIndices(pts: LatLng[], k: number): number[][] {
  const n = pts.length;
  if (n === 0) return [];
  const K = Math.max(1, Math.min(k, n));
  if (K === 1) return [pts.map((_, i) => i)];

  const order = pts
    .map((_, i) => i)
    .sort((a, b) => pts[a].lng - pts[b].lng || pts[a].lat - pts[b].lat);
  let centroids: LatLng[] = Array.from({ length: K }, (_, j) => {
    const idx = order[Math.min(n - 1, Math.floor((j + 0.5) * (n / K)))];
    return { lat: pts[idx].lat, lng: pts[idx].lng };
  });

  const assign = new Array<number>(n).fill(0);
  for (let iter = 0; iter < 14; iter++) {
    let changed = false;
    for (let i = 0; i < n; i++) {
      let best = 0;
      let bd = Infinity;
      for (let j = 0; j < K; j++) {
        const d = haversine(pts[i].lat, pts[i].lng, centroids[j].lat, centroids[j].lng);
        if (d < bd) {
          bd = d;
          best = j;
        }
      }
      if (assign[i] !== best) {
        assign[i] = best;
        changed = true;
      }
    }
    const sums = Array.from({ length: K }, () => ({ lat: 0, lng: 0, c: 0 }));
    for (let i = 0; i < n; i++) {
      const a = assign[i];
      sums[a].lat += pts[i].lat;
      sums[a].lng += pts[i].lng;
      sums[a].c++;
    }
    centroids = sums.map((s, j) => (s.c ? { lat: s.lat / s.c, lng: s.lng / s.c } : centroids[j]));
    if (!changed && iter > 0) break;
  }

  const groups: number[][] = Array.from({ length: K }, () => []);
  assign.forEach((a, i) => groups[a].push(i));
  // Reseed empty clusters by stealing one member from the largest group.
  for (let j = 0; j < K; j++) {
    if (groups[j].length === 0) {
      let big = 0;
      for (let g = 0; g < K; g++) if (groups[g].length > groups[big].length) big = g;
      if (groups[big].length > 1) groups[j].push(groups[big].pop() as number);
    }
  }
  return groups.filter((g) => g.length > 0);
}

// Convex hull via Andrew's monotone chain. Input/output as [lat,lng] pairs.
// For <3 points the hull is just the points (Leaflet renders them degenerately;
// MapCanvas falls back to a circle for tiny clusters).
export function convexHull(pts: LatLng[]): [number, number][] {
  if (pts.length < 3) return pts.map((p) => [p.lat, p.lng] as [number, number]);
  const ps = pts.map((p) => [p.lng, p.lat] as [number, number]); // x=lng, y=lat
  ps.sort((a, b) => a[0] - b[0] || a[1] - b[1]);
  const cross = (o: [number, number], a: [number, number], b: [number, number]) =>
    (a[0] - o[0]) * (b[1] - o[1]) - (a[1] - o[1]) * (b[0] - o[0]);
  const lower: [number, number][] = [];
  for (const p of ps) {
    while (lower.length >= 2 && cross(lower[lower.length - 2], lower[lower.length - 1], p) <= 0)
      lower.pop();
    lower.push(p);
  }
  const upper: [number, number][] = [];
  for (let i = ps.length - 1; i >= 0; i--) {
    const p = ps[i];
    while (upper.length >= 2 && cross(upper[upper.length - 2], upper[upper.length - 1], p) <= 0)
      upper.pop();
    upper.push(p);
  }
  lower.pop();
  upper.pop();
  return lower.concat(upper).map(([x, y]) => [y, x] as [number, number]); // -> [lat,lng]
}
