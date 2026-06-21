/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_SUPABASE_URL: string;
  readonly VITE_SUPABASE_ANON_KEY: string;
  readonly VITE_CITYCRAWL_API_URL: string;
  // R2 access broker (Cloudflare Worker) — authorizes + streams observation thumbnails / sweep video.
  readonly VITE_BROKER_URL: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
