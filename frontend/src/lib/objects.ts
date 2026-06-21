// Authorized reads of R2-served objects (observation thumbnails, sweep video) via the
// broker Worker. The browser can't put an `Authorization` header on an <img>/<video> src,
// so we fetch the bytes with the caller's Supabase JWT and hand back a blob: object URL.
// The broker authorizes every read through public.app_authorize_object before streaming.
import { supabase } from "./supabase";

export const THUMBNAIL_BUCKET = "observation-thumbnails";

const BROKER = import.meta.env.VITE_BROKER_URL as string | undefined;

// Fetch an object the current user is authorized to view and return a blob: URL for it
// (or null if unconfigured / unauthenticated / denied / missing). Callers own the URL and
// should URL.revokeObjectURL it when done. Never throws — image loading is best-effort.
export async function fetchObjectUrl(bucket: string, path: string): Promise<string | null> {
  if (!BROKER || !path) return null;
  try {
    const { data } = await supabase.auth.getSession();
    const token = data.session?.access_token;
    if (!token) return null;
    const url =
      `${BROKER.replace(/\/$/, "")}/api/r2/object` +
      `?bucket=${encodeURIComponent(bucket)}&path=${encodeURIComponent(path)}`;
    const res = await fetch(url, { headers: { Authorization: `Bearer ${token}` } });
    if (!res.ok) return null;
    const objectUrl = URL.createObjectURL(await res.blob());
    // Only hand back the URL if the bytes actually decode as an image — corrupt/empty/stub
    // thumbnails resolve to null so the caller can fall back (e.g. a plain map dot).
    return await new Promise<string | null>((resolve) => {
      const img = new Image();
      img.onload = () => resolve(objectUrl);
      img.onerror = () => {
        URL.revokeObjectURL(objectUrl);
        resolve(null);
      };
      img.src = objectUrl;
    });
  } catch {
    return null;
  }
}
