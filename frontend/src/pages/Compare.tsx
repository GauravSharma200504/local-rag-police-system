import { useState } from "react";
import { Link } from "react-router-dom";
import { AlertTriangle, GitCompare } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorBox, Label, Notice, PageHeader, Select } from "@/components/ui/primitives";
import { CitationText } from "@/components/CitationText";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import type { Citation, DocumentItem } from "@/types";

interface Ref { document_id: string; document_title: string; page: number; passage: string; value: string }
interface Structured {
  common: { type: string; label: string; value: string; a: Ref; b: Ref }[];
  different: { type: string; label: string; only_in: "a" | "b"; value: string; a?: Ref; b?: Ref }[];
  conflicts: { type: string; category: string; message: string; a: Ref[]; b: Ref[] }[];
  missing: { label: string; missing_in: string; message: string }[];
}
interface Result {
  content: { a: { id: string; title: string }; b: { id: string; title: string }; structured: Structured; disclaimer: string;
    narrative?: { available: boolean; error?: string; text?: string; citations?: Citation[]; warnings?: string[]; unsupported_sentences?: string[] } };
  report?: { id: string };
}

export default function ComparePage() {
  const docs = useApi<{ items: DocumentItem[] }>("/documents", { status: "indexed", page_size: 200 });
  const [a, setA] = useState("");
  const [b, setB] = useState("");
  const [narrative, setNarrative] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [res, setRes] = useState<Result | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const items = (docs.data?.items ?? []).filter((d) => d.doc_type !== "Legal Document");

  const run = async () => {
    setBusy(true);
    setError(null);
    try { setRes((await api.post<Result>("/intelligence/compare", { document_a: a, document_b: b, narrative })).data); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };
  const open = (r?: Ref) => r && setViewer({ documentId: r.document_id, page: r.page, passage: r.passage });
  const RefBtn = ({ r, side }: { r?: Ref; side: string }) => r ? (
    <button onClick={() => open(r)} className="w-full rounded border border-slate-200 p-2 text-left text-xs hover:border-navy-600">
      <div className="mb-0.5 font-medium text-slate-700">{side} · {r.document_title} · p.{r.page}</div>
      <div className="italic text-slate-600">“{r.passage}”</div>
    </button>
  ) : <div className="rounded border border-dashed border-slate-200 p-2 text-xs text-slate-400">Not mentioned</div>;
  const s = res?.content.structured;

  return (
    <div>
      <PageHeader title="Document Comparison" description="Side-by-side comparison of two documents. Every difference cites passages from both documents; the system does not decide which version is correct." />
      <Card>
        <CardBody className="grid items-end gap-3 md:grid-cols-[1fr_1fr_auto_auto]">
          <div><Label>Document A</Label><Select value={a} onChange={(e) => setA(e.target.value)} aria-label="Document A"><option value="">Select…</option>{items.map((d) => <option key={d.id} value={d.id}>{d.case_number ? `${d.case_number} · ` : ""}{d.title} ({d.doc_type})</option>)}</Select></div>
          <div><Label>Document B</Label><Select value={b} onChange={(e) => setB(e.target.value)} aria-label="Document B"><option value="">Select…</option>{items.filter((d) => d.id !== a).map((d) => <option key={d.id} value={d.id}>{d.case_number ? `${d.case_number} · ` : ""}{d.title} ({d.doc_type})</option>)}</Select></div>
          <label className="flex h-9 items-center gap-2 text-xs"><input type="checkbox" checked={narrative} onChange={(e) => setNarrative(e.target.checked)} /> AI narrative (local LLM)</label>
          <Button onClick={run} loading={busy} disabled={!a || !b}><GitCompare className="h-4 w-4" /> Compare</Button>
        </CardBody>
      </Card>
      {error && <ErrorBox className="mt-4" message={error} />}
      {!res && !busy && <Card className="mt-4"><EmptyState title="Select two documents to compare" description="e.g. the FIR and a witness statement of the same case." /></Card>}
      {res && s && (
        <div className="mt-4 space-y-4">
          <Notice>{res.content.disclaimer} {res.report && <Link to={`/reports/${res.report.id}`} className="font-medium underline">Saved as a draft report - export to PDF/DOCX</Link>}</Notice>
          <Card className={s.conflicts.length ? "border-amber-300" : ""}>
            <CardHeader title={<span className="flex items-center gap-2"><AlertTriangle className="h-4 w-4 text-amber-600" /> Potentially conflicting statements ({s.conflicts.length})</span>} />
            <CardBody className="space-y-4">
              {!s.conflicts.length && <p className="text-sm text-slate-500">No conflicting dates, times or vehicle numbers were detected for the same event.</p>}
              {s.conflicts.map((c, i) => (
                <div key={i}>
                  <p className="mb-2 text-sm font-medium text-slate-800">{c.message}</p>
                  <div className="grid gap-2 md:grid-cols-2">
                    <div className="space-y-1">{c.a.map((r, j) => <RefBtn key={j} r={r} side="A" />)}</div>
                    <div className="space-y-1">{c.b.map((r, j) => <RefBtn key={j} r={r} side="B" />)}</div>
                  </div>
                </div>
              ))}
            </CardBody>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            <Card>
              <CardHeader title={`Common facts (${s.common.length})`} />
              <div className="divide-y divide-slate-100">
                {s.common.map((c, i) => (
                  <div key={i} className="px-5 py-2.5">
                    <div className="mb-1 flex items-center gap-2 text-sm"><Badge>{c.label}</Badge><span className="font-medium">{c.value}</span></div>
                    <div className="grid gap-1 md:grid-cols-2"><RefBtn r={c.a} side="A" /><RefBtn r={c.b} side="B" /></div>
                  </div>
                ))}
              </div>
            </Card>
            <Card>
              <CardHeader title={`Different facts (${s.different.length})`} description="Values found in only one document. A difference may reflect wording or scope rather than a contradiction." />
              <div className="divide-y divide-slate-100">
                {s.different.map((d, i) => (
                  <div key={i} className="px-5 py-2.5">
                    <div className="mb-1 flex items-center gap-2 text-sm"><Badge>{d.label}</Badge><span className="font-medium">{d.value}</span><Badge tone={d.only_in === "a" ? "navy" : "violet"}>only in {d.only_in.toUpperCase()}</Badge></div>
                    <RefBtn r={d.only_in === "a" ? d.a : d.b} side={d.only_in.toUpperCase()} />
                  </div>
                ))}
              </div>
            </Card>
          </div>
          {s.missing.length > 0 && (
            <Card><CardHeader title="Missing information" /><CardBody><ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{s.missing.map((m, i) => <li key={i}>{m.message}</li>)}</ul></CardBody></Card>
          )}
          {res.content.narrative && (
            <Card>
              <CardHeader title="AI narrative comparison" description="Generated by the local LLM with validated citations - a draft for human review." />
              <CardBody>
                {!res.content.narrative.available ? <ErrorBox message={res.content.narrative.error ?? "LLM unavailable"} /> : (
                  <>
                    <CitationText text={res.content.narrative.text ?? ""} citations={res.content.narrative.citations ?? []} unsupported={res.content.narrative.unsupported_sentences}
                      onCite={(c) => c.document_id && setViewer({ documentId: c.document_id, page: c.page, passage: c.passage })} />
                    {(res.content.narrative.warnings?.length ?? 0) > 0 && <Notice className="mt-3">{res.content.narrative.warnings!.join(" ")}</Notice>}
                  </>
                )}
              </CardBody>
            </Card>
          )}
        </div>
      )}
      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
