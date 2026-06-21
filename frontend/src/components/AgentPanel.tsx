import { useEffect, useRef, useState } from "react";
import ReactMarkdown from "react-markdown";
import remarkGfm from "remark-gfm";
import type { ChatMessage, PlanResult } from "../lib/types";
import { typeUnit } from "../lib/types";
import { money } from "../lib/money";
import { volumeColor } from "../lib/geo";
import { Panel } from "@/components/ui/panel";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Spinner } from "@/components/ui/spinner";

interface Chip {
  label: string;
  run: () => void;
}

interface Props {
  previewing: boolean;
  plan: PlanResult | null;
  typeLabels: Record<string, string>;
  chips: Chip[];
  // Send the full conversation to the agent. The handler populates the dock with the merged
  // draft (independent of the dock's "Generar plan" button) and resolves with the assistant's
  // Spanish reply for this turn.
  onChat?: (messages: ChatMessage[]) => Promise<string>;
  onClosePreview: () => void;
  onLocateObs: (id: string) => void;
  onLocateSquad: (lat: number, lng: number) => void;
}

const SHELL = "absolute right-[18px] top-[18px] bottom-[18px] z-[510] flex w-[368px] flex-col";

export function AgentPanel(props: Props) {
  if (props.previewing && props.plan) {
    return (
      <Panel className={SHELL}>
        <PlanPreview
          plan={props.plan}
          typeLabels={props.typeLabels}
          onClose={props.onClosePreview}
          onLocateObs={props.onLocateObs}
          onLocateSquad={props.onLocateSquad}
        />
      </Panel>
    );
  }
  return (
    <Panel className={SHELL}>
      <AgentDefault chips={props.chips} onChat={props.onChat} />
    </Panel>
  );
}

// ---- plan preview -----------------------------------------------------------

const ROW_ITEM =
  "flex h-auto w-full items-center justify-start gap-[9px] rounded-[10px] border border-[var(--line-2)] bg-[#fbfcfe] px-2.5 py-2 font-normal";
const ROW_LABEL = "block truncate text-[12px] font-semibold tracking-[-0.1px]";
const ROW_META = "block truncate font-mono text-[9.5px] text-muted-foreground";

function PlanPreview({
  plan,
  typeLabels,
  onClose,
  onLocateObs,
  onLocateSquad,
}: {
  plan: PlanResult;
  typeLabels: Record<string, string>;
  onClose: () => void;
  onLocateObs: (id: string) => void;
  onLocateSquad: (lat: number, lng: number) => void;
}) {
  const s = plan.stats;
  const unit = typeUnit(plan.issueType);
  const typeLabel = typeLabels[plan.issueType] ?? plan.issueType;
  const maxVol = plan.topCritical.length ? Math.max(...plan.topCritical.map((t) => t.volume)) : 1;

  const stats: { value: string; label: string; bg: string; border: string; color: string }[] = [
    { value: String(s.count), label: "Baches atendidos", bg: "#eaf0ff", border: "#d9e4ff", color: "var(--acc,#2f64e6)" },
    { value: `${Math.round(s.volume)} ${unit}`, label: "Volumen total", bg: "#fdeceb", border: "#f8d8d6", color: "#e5484d" },
    { value: String(s.squads), label: "Cuadrillas", bg: "#f7f9fc", border: "#eef0f4", color: "#1b2430" },
    { value: String(s.regions), label: "Alcaldías", bg: "#f7f9fc", border: "#eef0f4", color: "#1b2430" },
  ];

  return (
    <>
      {/* header */}
      <div className="flex items-center gap-2.5 border-b border-[var(--line-2)] px-3.5 py-[13px]">
        <Button
          variant="secondary"
          size="icon"
          onClick={onClose}
          title="Volver al agente"
          className="size-[30px] shrink-0 rounded-lg bg-[#f1f4f8]"
        >
          <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
            <path d="M15 6l-6 6 6 6" stroke="#5b6675" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
          </svg>
        </Button>
        <div className="min-w-0 flex-1 leading-[1.15]">
          <div className="text-sm font-extrabold tracking-[-0.2px]">Plan de acción</div>
          <div className="truncate font-mono text-[10.5px] text-muted-foreground">
            {typeLabel} · {money(plan.budget)}
          </div>
        </div>
        <Badge variant="statusReady" className="shrink-0">Listo</Badge>
      </div>

      <div className="pp-scroll flex-1 overflow-y-auto px-3.5 pb-4 pt-[13px]">
        {/* stats grid */}
        <div className="grid grid-cols-2 gap-2">
          {stats.map((st, i) => (
            <div
              key={i}
              className="rounded-[11px] border px-3 py-2.5"
              style={{ background: st.bg, borderColor: st.border }}
            >
              <div
                className="truncate font-mono text-[17px] font-semibold leading-none tracking-[-0.5px]"
                style={{ color: st.color }}
              >
                {st.value}
              </div>
              <div className="mt-1.5 text-[10px] font-medium text-muted-foreground">{st.label}</div>
            </div>
          ))}
        </div>

        {/* budget bar */}
        <div className="mt-2.5 rounded-[11px] border border-[var(--line-2)] bg-[var(--surface-1)] px-3 py-2.5">
          <div className="flex items-baseline justify-between">
            <span className="text-[10px] font-semibold uppercase tracking-wide text-muted-foreground">
              Presupuesto usado
            </span>
            <span className="font-mono text-[12.5px] font-semibold">
              {money(s.spent)} · {s.budgetPct}%
            </span>
          </div>
          <div className="mt-[7px] h-1.5 overflow-hidden rounded bg-[#e7ebf1]">
            <div className="h-full bg-primary" style={{ width: `${s.budgetPct}%` }} />
          </div>
          <div className="mt-1.5 font-mono text-[9.5px] text-[#aab2bd]">
            costo estimado · placeholder del módulo
          </div>
        </div>

        {/* top critical */}
        <SectionTitle title="Más críticos" hint="clic para ubicar" />
        <div className="flex flex-col gap-1.5">
          {plan.topCritical.map((tc) => (
            <Button key={tc.id} variant="ghost" onClick={() => onLocateObs(tc.id)} className={ROW_ITEM}>
              <RankBadge className="bg-[var(--bg)] text-[#41506a]">{tc.rank}</RankBadge>
              <span className="min-w-0 flex-1 text-left">
                <span className={ROW_LABEL}>
                  {(typeLabels[tc.slug] ?? tc.slug) + (tc.zone ? " · " + tc.zone : "")}
                </span>
                <span className={ROW_META}>{`${Math.round(tc.volume)} ${typeUnit(tc.slug)} · ${money(tc.cost)}`}</span>
              </span>
              <span
                className="size-[9px] shrink-0 rounded-full"
                style={{ background: volumeColor(tc.volume, maxVol) }}
              />
            </Button>
          ))}
          {plan.topCritical.length === 0 && <Empty>Sin baches dentro del presupuesto.</Empty>}
        </div>

        {/* crews (clusters) — categorical color per crew */}
        <SectionTitle title="Cuadrillas (clústeres)" hint="clic para ubicar" />
        <div className="flex flex-col gap-1.5">
          {plan.squads.map((sq) => (
            <Button
              key={sq.idx}
              variant="ghost"
              onClick={() => onLocateSquad(sq.centroid.lat, sq.centroid.lng)}
              className={ROW_ITEM}
            >
              <RankBadge className="text-white" style={{ background: sq.color }}>C{sq.idx}</RankBadge>
              <span className="min-w-0 flex-1 text-left">
                <span className={ROW_LABEL}>Cuadrilla {sq.idx}</span>
                <span className={ROW_META}>{`${sq.count} baches · ${money(sq.cost)}`}</span>
              </span>
              <span className="size-[9px] shrink-0 rounded-full" style={{ background: sq.color }} />
            </Button>
          ))}
          {plan.squads.length === 0 && <Empty>Sin cuadrillas asignadas.</Empty>}
        </div>
      </div>
    </>
  );
}

function RankBadge({
  children,
  className,
  style,
}: {
  children: React.ReactNode;
  className?: string;
  style?: React.CSSProperties;
}) {
  return (
    <span
      className={`flex size-6 shrink-0 items-center justify-center rounded-[7px] font-mono text-[10.5px] font-semibold ${className ?? ""}`}
      style={style}
    >
      {children}
    </span>
  );
}

function SectionTitle({ title, hint }: { title: string; hint: string }) {
  return (
    <div className="mb-2 mt-4 flex items-baseline gap-2">
      <span className="text-[10px] font-bold uppercase tracking-[0.5px] text-muted-foreground">{title}</span>
      <span className="text-[10px] text-[#b3bac5]">{hint}</span>
    </div>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return <div className="px-0.5 py-1.5 text-[11.5px] text-[#aab2bd]">{children}</div>;
}

// ---- agent default ----------------------------------------------------------

// Greeting shown before the first user turn — static, not sent to the model.
const INTRO =
  "¡Hola! Soy tu agente del mapa de prioridades. Dime qué quieres atender y armo un plan: " +
  "tipo de problema, presupuesto, región (alcaldía) y cuántas cuadrillas. " +
  'Por ejemplo: "baches en Cuauhtémoc, 2 millones, 3 cuadrillas". Relleno el panel para que ' +
  "lo revises antes de generar — pídeme ajustes cuando quieras.";

function AgentDefault({
  chips,
  onChat,
}: {
  chips: Chip[];
  onChat?: (messages: ChatMessage[]) => Promise<string>;
}) {
  const [prompt, setPrompt] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const scrollRef = useRef<HTMLDivElement>(null);

  // Keep the conversation pinned to the latest turn.
  useEffect(() => {
    scrollRef.current?.scrollTo({ top: scrollRef.current.scrollHeight, behavior: "smooth" });
  }, [messages, busy]);

  const submit = () => {
    const text = prompt.trim();
    if (!text || busy || !onChat) return;
    const next: ChatMessage[] = [...messages, { role: "user", content: text }];
    setMessages(next);
    setPrompt("");
    setBusy(true);
    setErr(null);
    onChat(next)
      .then((reply) => setMessages((m) => [...m, { role: "assistant", content: reply }]))
      .catch((e) => setErr(e instanceof Error ? e.message : String(e)))
      .finally(() => setBusy(false));
  };

  return (
    <>
      <div className="flex items-center gap-2.5 border-b border-[var(--line-2)] px-4 py-3.5">
        <div className="flex size-[30px] shrink-0 items-center justify-center rounded-[9px] bg-[linear-gradient(135deg,var(--acc,#2f64e6),#6a4cf0)]">
          <svg width="15" height="15" viewBox="0 0 24 24" fill="none">
            <path d="M12 3l1.6 4.8L18 9.4l-4.4 1.6L12 16l-1.6-5L6 9.4l4.4-1.6L12 3z" fill="#fff" />
            <circle cx="18.5" cy="5.5" r="1.4" fill="#fff" />
          </svg>
        </div>
        <div className="leading-[1.15]">
          <div className="text-sm font-extrabold tracking-[-0.2px]">Agente</div>
          <div className="text-[10.5px] font-medium text-muted-foreground">
            Conversa para armar tu plan de reparación
          </div>
        </div>
      </div>

      <div ref={scrollRef} className="pp-scroll flex flex-1 flex-col gap-3 overflow-y-auto px-4 pb-2.5 pt-4">
        <Bubble role="assistant">{INTRO}</Bubble>
        {messages.map((m, i) => (
          <Bubble key={i} role={m.role}>
            {m.content}
          </Bubble>
        ))}
        {busy && <Typing />}
      </div>

      <div className="border-t border-[var(--line-2)] bg-white/60 px-3 pb-3 pt-2.5">
        {err && (
          <div className="mb-[9px] rounded-lg border border-[#f6d4d2] bg-[#fdeceb] px-[9px] py-1.5 font-mono text-[10.5px] leading-[1.4] text-[#c2333a]">
            No pude responder: {err}
          </div>
        )}
        <div className="mb-[9px] flex flex-wrap gap-1.5">
          {chips.map((c) => (
            <Button
              key={c.label}
              variant="outline"
              onClick={c.run}
              className="h-auto whitespace-nowrap rounded-2xl bg-[#f4f6f9] px-2.5 py-[5px] text-[10.5px] font-medium text-[#41506a]"
            >
              {c.label}
            </Button>
          ))}
        </div>
        <div className="flex items-center gap-2 rounded-xl border border-[var(--line)] bg-card py-[5px] pl-[13px] pr-[5px]">
          <Input
            value={prompt}
            onChange={(e) => setPrompt(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === "Enter" && !e.shiftKey) {
                e.preventDefault();
                submit();
              }
            }}
            disabled={busy || !onChat}
            placeholder="Escribe un mensaje…"
            className="h-auto min-w-0 flex-1 border-0 bg-transparent px-0 py-0 text-[13px] shadow-none focus-visible:ring-0 md:text-[13px]"
          />
          <Button
            onClick={submit}
            disabled={busy || !prompt.trim() || !onChat}
            size="icon"
            title="Enviar"
            className="size-[34px] shrink-0 rounded-[9px]"
          >
            {busy ? (
              <Spinner size={15} className="border-white/50 border-t-white" />
            ) : (
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none">
                <path d="M5 12h13M13 6l6 6-6 6" stroke="#fff" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />
              </svg>
            )}
          </Button>
        </div>
      </div>
    </>
  );
}

// A single conversation turn. Assistant bubbles sit left with the gradient avatar; the user's
// own messages sit right in the accent color.
function Bubble({ role, children }: { role: "user" | "assistant"; children: React.ReactNode }) {
  if (role === "user") {
    return (
      <div className="flex justify-end">
        <div className="max-w-[82%] whitespace-pre-wrap rounded-[12px] rounded-br-[4px] bg-[var(--acc,#2f64e6)] px-3 py-2 text-[12.5px] leading-[1.45] text-white">
          {children}
        </div>
      </div>
    );
  }
  return (
    <div className="flex gap-[9px]">
      <div className="mt-px size-[22px] shrink-0 rounded-[7px] bg-[linear-gradient(135deg,var(--acc,#2f64e6),#6a4cf0)]" />
      <div className="max-w-[82%] rounded-[12px] rounded-tl-[4px] border border-[var(--line-2)] bg-[#fbfcfe] px-3 py-2 text-[12.5px] leading-[1.5] text-[#3a4655]">
        {typeof children === "string" ? <ChatMarkdown text={children} /> : children}
      </div>
    </div>
  );
}

// Compact markdown renderer for assistant replies. Element styles are tuned to the bubble's
// 12.5px / 1.5 type scale so lists, emphasis, and code stay legible without a typography plugin.
function ChatMarkdown({ text }: { text: string }) {
  return (
    <div className="space-y-1.5 break-words [&_a]:text-[var(--acc,#2f64e6)] [&_a]:underline [&_code]:rounded [&_code]:bg-[#eef1f6] [&_code]:px-1 [&_code]:py-px [&_code]:font-mono [&_code]:text-[11px] [&_li]:my-0.5 [&_ol]:list-decimal [&_ol]:pl-4 [&_p]:whitespace-pre-wrap [&_strong]:font-semibold [&_strong]:text-[#1b2430] [&_ul]:list-disc [&_ul]:pl-4">
      <ReactMarkdown
        remarkPlugins={[remarkGfm]}
        components={{
          a: ({ node, ...props }) => <a target="_blank" rel="noreferrer" {...props} />,
        }}
      >
        {text}
      </ReactMarkdown>
    </div>
  );
}

// Three-dot "thinking" indicator shown while the agent's turn is in flight.
function Typing() {
  return (
    <div className="flex gap-[9px]">
      <div className="mt-px size-[22px] shrink-0 rounded-[7px] bg-[linear-gradient(135deg,var(--acc,#2f64e6),#6a4cf0)]" />
      <div className="flex items-center gap-1 rounded-[12px] rounded-tl-[4px] border border-[var(--line-2)] bg-[#fbfcfe] px-3 py-2.5">
        {[0, 1, 2].map((i) => (
          <span
            key={i}
            className="size-1.5 animate-bounce rounded-full bg-[#aab2bd]"
            style={{ animationDelay: `${i * 0.15}s` }}
          />
        ))}
      </div>
    </div>
  );
}
