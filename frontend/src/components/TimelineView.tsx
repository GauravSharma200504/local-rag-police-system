import { AlertTriangle, CalendarClock } from "lucide-react";
import { Badge, Card, CardHeader, EmptyState, Notice, type Tone } from "@/components/ui/primitives";
import type { Timeline } from "@/types";
import { cn } from "@/utils/format";

const NATURE_TONE: Record<string, Tone> = {
  allegation: "navy", "witness statement": "violet", "investigative observation": "blue", "documentary evidence": "amber",
};

export function TimelineView({ timeline, onOpen }: { timeline: Timeline; onOpen: (documentId: string, page: number, passage: string) => void }) {
  if (!timeline.events.length) return <EmptyState icon={<CalendarClock className="h-5 w-5" />} title="No dated events found" description="Timelines are built from dates and times extracted from indexed case documents." />;
  return (
    <div className="space-y-4">
      {timeline.conflicts.length > 0 && (
        <Card className="border-amber-300">
          <CardHeader title={<span className="flex items-center gap-2 text-amber-800"><AlertTriangle className="h-4 w-4" /> Unresolved discrepancies ({timeline.conflicts.length})</span>}
            description="Shown with every source. The system does not decide which version is correct." />
          <div className="divide-y divide-slate-100">
            {timeline.conflicts.map((c, i) => (
              <div key={i} className="px-5 py-3">
                <p className="text-sm font-medium text-slate-800">{c.message}</p>
                <div className="mt-2 grid gap-2 md:grid-cols-2">
                  {c.versions.map((v, j) => (
                    <button key={j} onClick={() => onOpen(v.document_id, v.page, v.passage)} className="rounded border border-slate-200 p-2 text-left text-xs hover:border-navy-600">
                      <div className="mb-1 flex items-center gap-1.5"><Badge tone="amber">{v.value}</Badge><span className="font-medium">{v.document_title}</span><span className="text-slate-400">p.{v.page}</span><Badge tone={NATURE_TONE[v.nature] ?? "slate"}>{v.nature}</Badge></div>
                      <p className="italic text-slate-600">“{v.passage}”</p>
                    </button>
                  ))}
                </div>
              </div>
            ))}
          </div>
        </Card>
      )}
      {timeline.flags.length > 0 && <Notice>{timeline.flags.map((f, i) => <div key={i}>{f}</div>)}</Notice>}
      <ol className="relative ml-3 border-l border-slate-200">
        {timeline.events.map((e, i) => (
          <li key={i} className="mb-3 ml-5">
            <span className={cn("absolute -left-[5px] mt-1.5 h-2.5 w-2.5 rounded-full border-2 border-white", e.flags.length ? "bg-amber-500" : "bg-navy-700")} />
            <button onClick={() => onOpen(e.document_id, e.page, e.description)} className="w-full rounded-md border border-slate-200 bg-white p-3 text-left hover:border-navy-600">
              <div className="flex flex-wrap items-center gap-2 text-xs">
                <span className="font-mono font-semibold text-slate-900">{e.date ?? "date unknown"}{e.time ? ` ${e.time}` : ""}</span>
                <Badge tone={NATURE_TONE[e.nature] ?? "slate"}>{e.nature}</Badge>
                {e.category && <Badge>{e.category.replace(/_/g, " ")}</Badge>}
                {e.flags.map((f) => <Badge key={f} tone="amber">{f.replace(/_/g, " ")}</Badge>)}
                <span className="ml-auto text-slate-500">{e.document_title} · p.{e.page}</span>
              </div>
              <p className="mt-1 text-sm text-slate-700">{e.description}</p>
              {(e.people.length > 0 || e.locations.length > 0) && (
                <p className="mt-1 text-[11px] text-slate-500">{[...e.people, ...e.locations].join(" · ")}</p>
              )}
            </button>
          </li>
        ))}
      </ol>
    </div>
  );
}
