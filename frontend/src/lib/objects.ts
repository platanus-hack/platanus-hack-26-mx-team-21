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
    return URL.createObjectURL(await res.blob());
  } catch {
    return null;
  }
}
