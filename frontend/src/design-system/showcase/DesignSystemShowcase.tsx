import type { ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Separator } from "@/components/ui/separator";
import { Skeleton } from "@/components/ui/skeleton";
import { Slider } from "@/components/ui/slider";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import { Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui/tabs";
import {
  Tooltip,
  TooltipProvider,
  TooltipTrigger,
  TooltipContent,
} from "@/components/ui/tooltip";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
} from "@/components/ui/popover";
import { ScrollArea } from "@/components/ui/scroll-area";
import { Spinner } from "@/components/ui/spinner";

function Section({ title, children }: { title: string; children: ReactNode }) {
  return (
    <section style={{ marginBottom: 28 }}>
      <h2
        style={{
          font: "600 11px var(--font-mono)",
          textTransform: "uppercase",
          letterSpacing: ".6px",
          color: "var(--muted-ink)",
          margin: "0 0 10px",
        }}
      >
        {title}
      </h2>
      <div
        style={{
          display: "flex",
          flexWrap: "wrap",
          gap: 12,
          alignItems: "center",
        }}
      >
        {children}
      </div>
    </section>
  );
}

export function DesignSystemShowcase() {
  return (
    <TooltipProvider>
      <div data-showcase-ready style={{ maxWidth: 900, margin: "0 auto", padding: 32 }}>
        <h1 style={{ font: "800 22px var(--font-display)", color: "var(--ink)", margin: "0 0 4px" }}>
          CityCrawl — Design System
        </h1>
        <p style={{ color: "var(--muted-ink)", margin: "0 0 24px", fontFamily: "var(--font-display)" }}>
          shadcn/ui primitives themed from the reference tokens
        </p>

        <Section title="Buttons">
          <Button>Default</Button>
          <Button variant="secondary">Secondary</Button>
          <Button variant="outline">Outline</Button>
          <Button variant="ghost">Ghost</Button>
          <Button variant="destructive">Destructive</Button>
          <Button disabled>Disabled</Button>
        </Section>

        <Section title="Badges">
          <Badge>Default</Badge>
          <Badge variant="secondary">Secondary</Badge>
          <Badge variant="outline">Outline</Badge>
          <Badge variant="statusPending">PENDIENTE</Badge>
          <Badge variant="statusConfirmed">CONFIRMADO</Badge>
          <Badge variant="type">SEMÁFORO</Badge>
        </Section>

        <Section title="Card">
          <Card style={{ width: 280, padding: 14 }}>
            <div style={{ fontWeight: 700, fontFamily: "var(--font-display)" }}>Observación</div>
            <Separator style={{ margin: "10px 0" }} />
            <div style={{ color: "var(--ink-2)", fontSize: 13 }}>Contenido de ejemplo.</div>
          </Card>
        </Section>

        <Section title="Form">
          <div style={{ display: "grid", gap: 6, width: 240 }}>
            <Label htmlFor="email">Correo</Label>
            <Input id="email" placeholder="tu@correo.mx" />
          </div>
        </Section>

        <Section title="Slider">
          <div style={{ width: 240 }}>
            <Slider defaultValue={[60]} max={100} step={1} />
          </div>
        </Section>

        <Section title="Toggles">
          <Switch defaultChecked />
          <Checkbox defaultChecked />
        </Section>

        <Section title="Tabs">
          <Tabs defaultValue="ruta" style={{ width: 320 }}>
            <TabsList>
              <TabsTrigger value="ruta">Ruta</TabsTrigger>
              <TabsTrigger value="grupo">Grupo</TabsTrigger>
            </TabsList>
            <TabsContent value="ruta">Análisis de ruta</TabsContent>
            <TabsContent value="grupo">Análisis de grupo</TabsContent>
          </Tabs>
        </Section>

        <Section title="Overlays">
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline">Popover</Button>
            </PopoverTrigger>
            <PopoverContent>Planes anteriores…</PopoverContent>
          </Popover>
          <Tooltip>
            <TooltipTrigger asChild>
              <Button variant="ghost">Tooltip</Button>
            </TooltipTrigger>
            <TooltipContent>Detalle</TooltipContent>
          </Tooltip>
        </Section>

        <Section title="Loading">
          <Spinner />
          <Skeleton style={{ width: 160, height: 14 }} />
        </Section>

        <Section title="ScrollArea">
          <ScrollArea
            className="pp-scroll"
            style={{
              height: 80,
              width: 200,
              border: "1px solid var(--line)",
              borderRadius: 9,
              padding: 8,
            }}
          >
            {Array.from({ length: 20 }).map((_, i) => (
              <div key={i} style={{ fontSize: 13, fontFamily: "var(--font-display)" }}>
                Fila {i + 1}
              </div>
            ))}
          </ScrollArea>
        </Section>
      </div>
    </TooltipProvider>
  );
}
