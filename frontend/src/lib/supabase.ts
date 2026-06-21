import { createClient } from "@supabase/supabase-js";
import type { Database } from "@db-types";

const url = import.meta.env.VITE_SUPABASE_URL;
const anonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

if (!url || !anonKey) {
  // Fail loud in dev rather than silently returning empty data.
  throw new Error(
    "Faltan VITE_SUPABASE_URL / VITE_SUPABASE_ANON_KEY. Copia apps/web/.env.example a apps/web/.env.",
  );
}

// Typed against the `public` schema only — the browser never touches the
// custom schemas; all reads go through the public.app_* security-definer RPCs.
export const supabase = createClient<Database>(url, anonKey, {
  auth: { persistSession: true, autoRefreshToken: true, detectSessionInUrl: true },
});
