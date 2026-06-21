// Typed client for the Fly modular API (citycrawl-api). Planning + draft parsing moved off
// the browser; reads still go directly to Supabase RPCs (see api.ts). Every call attaches
// the current Supabase access token. There is no client-side computation fallback.
import { supabase } from "./supabase";
import type {
  AnalysisPoint,
  AnalysisRequest,
  ChatMessage,
  ClusteredPriority,
  DraftChatResponse,
  PlanDraft,
  PlanResult,
  RegionOption,
  TypeCount,
} from "./types";

const BASE = import.meta.env.VITE_CITYCRAWL_API_URL as string | undefined;

async function authHeaders(): Promise<HeadersInit> {
  const { data } = await supabase.auth.getSession();
  const token = data.session?.access_token;
  if (!token) throw new Error("Sesión expirada. Vuelve a iniciar sesión.");
  return { "Content-Type": "application/json", Authorization: `Bearer ${token}` };
}

async function post<T>(path: string, body: unknown, signal?: AbortSignal): Promise<T> {
  if (!BASE) throw new Error("Falta VITE_CITYCRAWL_API_URL. Copia frontend/.env.example a frontend/.env.");
  const res = await fetch(`${BASE.replace(/\/$/, "")}${path}`, {
    method: "POST",
    headers: await authHeaders(),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok) {
    let message = `Error ${res.status}`;
    try {
      const j = await res.json();
      message = j?.error?.message ?? message;
    } catch {
      /* non-JSON error body */
    }
    throw new Error(message);
  }
  return (await res.json()) as T;
}

// Action plan — the former runAnalysis, now server-side.
export function optimizePlan(req: AnalysisRequest, signal?: AbortSignal): Promise<PlanResult> {
  return post<PlanResult>("/v1/planning/optimize", req, signal);
}

// Standalone priority clusters — the former mockClusteredPriorities, now server-side.
export function clusterPriorities(
  points: AnalysisPoint[],
  squadCount?: number,
  signal?: AbortSignal,
): Promise<ClusteredPriority[]> {
  return post<ClusteredPriority[]>("/v1/planning/priorities:cluster", { points, squadCount }, signal);
}

// Conversational agent turn — sends the full message history plus the draft accumulated so
// far, and gets back a Spanish reply and the merged draft. Populates the dock; never auto-runs.
export function chatDraft(
  messages: ChatMessage[],
  draft: PlanDraft | null,
  issueTypes: TypeCount[],
  regions: RegionOption[],
  signal?: AbortSignal,
): Promise<DraftChatResponse> {
  return post<DraftChatResponse>(
    "/v1/llm/chat",
    {
      messages,
      draft,
      issueTypes: issueTypes.map((t) => ({ slug: t.slug, label: t.label })),
      regions: regions.map((r) => ({ cve: r.cve, name: r.name })),
    },
    signal,
  );
}
