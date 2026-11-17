import { useState } from "react";
import { Copy, FileSearch, ShieldCheck } from "lucide-react";
import { Badge } from "@/components/ui/primitives";
import { DocTypeBadge } from "@/components/StatusBadge";
import type { Citation, Message } from "@/types";
import { useToast } from "@/components/Toast";

const NATURE: Record<string, string> = {
  FIR: "Allegation (FIR)", "Witness Statement": "Witness statement", "Investigation Report": "Investigative observation",
  "Evidence Report": "Documentary evidence", "Charge Sheet": "Allegation (charge sheet)", "Legal Document": "Legal reference", Other: "Document",
};

export function EvidencePanel({ message, onOpen }: { message: Message | null; onOpen: (c: Citation) => void }) {
  const [tab, setTab] = useState<"cited" | "retrieved">("cited");
  const toast = useToast();
  if (!message) {
    return <div className="p-5 text-xs text-slate-500">Evidence for the selected answer appears here: validated citations, their pages and the retrieved passages.</div>;
  }
  const sources = message.retrieval.sources ?? [];
  const copy = () => {
    const txt = message.citations.map((c) => `[${c.label}] ${c.document_title}, page ${c.page}: "${c.passage}"`).join("\n");
    navigator.clipboard?.writeText(txt).then(() => toast("Citations copied"), () => toast("Clipboard unavailable", "error"));
  };
  const timings = message.retrieval.timings_ms ?? {};
  const stages = message.retrieval.retrieval?.stage_counts ?? {};
  return (
    <div className="flex h-full flex-col">
      <div className="flex items-center justify-between border-b border-slate-200 px-4 py-3">
        <div className="flex gap-1">
          {(["cited", "retrieved"] as const).map((t) => (
            <button key={t} onClick={() => setTab(t)} className={`rounded px-2 py-1 text-xs font-medium ${tab === t ? "bg-navy-800 text-white" : "text-slate-600 hover:bg-slate-100"}`}>
              {t === "cited" ? `Citations (${message.citations.length})` : `Retrieved (${sources.length})`}
            </button>
          ))}
        </div>
        {message.citations.length > 0 && (
          <button onClick={copy} className="flex items-center gap-1 text-xs text-slate-500 hover:text-slate-900"><Copy className="h-3.5 w-3.5" /> Copy</button>
        )}
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-4">
        {tab === "cited" && message.citations.length === 0 && (
          <p className="text-xs text-slate-500">{message.abstained ? "No answer was given, so there are no citations." : "No validated citations."}</p>
        )}
        {tab === "cited" && message.citations.map((c) => (
          <button key={c.label} onClick={() => onOpen(c)} className="block w-full rounded-md border border-slate-200 p-3 text-left hover:border-navy-600 hover:bg-navy-50">
            <div className="mb-1 flex flex-wrap items-center gap-1.5">
              <Badge tone="navy">{c.label}</Badge>
              <span className="text-xs font-medium text-slate-900">{c.document_title}</span>
              <span className="text-xs text-slate-500">· page {c.page}</span>
            </div>
            <p className="text-xs italic text-slate-700">“{c.passage}”</p>
            <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-500">
              {c.doc_type && <span>{NATURE[c.doc_type] ?? c.doc_type}</span>}
              {c.support !== null && c.support !== undefined && (
                <span className="flex items-center gap-1 text-emerald-700"><ShieldCheck className="h-3 w-3" /> support {(c.support * 100).toFixed(0)}%</span>
              )}
              <span className="ml-auto flex items-center gap-1 text-navy-700"><FileSearch className="h-3 w-3" /> open page</span>
            </div>
          </button>
        ))}
        {tab === "retrieved" && sources.map((s) => (
          <button key={s.chunk_id} onClick={() => onOpen({ label: s.label, chunk_id: s.chunk_id, document_id: s.document_id, document_title: s.document_title, page: s.page_start, passage: s.text.slice(0, 300), support: null })}
            className="block w-full rounded-md border border-slate-200 p-3 text-left hover:border-navy-600">
            <div className="mb-1 flex flex-wrap items-center gap-1.5">
              <Badge>{s.label}</Badge>
              <span className="text-xs font-medium text-slate-900">{s.document_title}</span>
              <span className="text-xs text-slate-500">p.{s.page_start}{s.page_end !== s.page_start ? `–${s.page_end}` : ""}</span>
              <DocTypeBadge type={s.doc_type} />
            </div>
            <p className="line-clamp-4 text-xs text-slate-600">{s.text}</p>
            <div className="mt-2 flex flex-wrap gap-2 font-mono text-[10px] text-slate-500">
              {s.scores.dense_rank !== undefined && <span>dense #{s.scores.dense_rank} ({s.scores.dense_similarity?.toFixed(3)})</span>}
              {s.scores.sparse_rank !== undefined && <span>sparse #{s.scores.sparse_rank}</span>}
              {s.scores.rrf !== undefined && <span>RRF {s.scores.rrf.toFixed(4)}</span>}
              {s.scores.rerank !== undefined && <span>rerank {s.scores.rerank.toFixed(2)}</span>}
            </div>
          </button>
        ))}
      </div>
      <div className="border-t border-slate-200 px-4 py-2 font-mono text-[10px] text-slate-500">
        config: {message.retrieval.config ?? "—"} · {Object.entries(stages).map(([k, v]) => `${k}:${v}`).join(" ")}
        {timings.total_ms !== undefined && ` · ${(timings.total_ms / 1000).toFixed(1)} s`}
      </div>
    </div>
  );
}
