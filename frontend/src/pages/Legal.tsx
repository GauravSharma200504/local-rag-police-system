import { useState } from "react";
import { BookOpen, Plus, Search } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorBox, Input, Notice, PageHeader, Select, Spinner } from "@/components/ui/primitives";
import { CitationText } from "@/components/CitationText";
import { UploadDialog } from "@/components/UploadDialog";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { StatusBadge } from "@/components/StatusBadge";
import type { Citation, DocStatus } from "@/types";

interface LegalMeta { act_name: string | null; short_name?: string; version?: string; effective_date?: string | null; source_url?: string; publication?: string;
  is_official_text: boolean; verified_by?: string; verification_date?: string | null; is_historical?: boolean; replaced_by?: string }
interface LegalResult { chunk_id: string; document_id: string; document_title: string; page_start: number; page_end: number; section_number: string | null;
  heading: string | null; text: string; scores: Record<string, number>; legal: LegalMeta; text_label: string }
interface SearchResponse { query: string; act: string | null; results: LegalResult[]; message: string | null;
  explanation: { label: string; text: string; abstained: boolean; citations: Citation[]; warnings: string[]; llm_error?: string | null } | null }
interface Source extends LegalMeta { document_id: string; title: string; status: DocStatus; chunks: number; pages: number }

export default function LegalPage() {
  const { user } = useAuth();
  const sources = useApi<Source[]>("/legal/sources", undefined, (d) => (d?.some((s) => !["indexed", "failed"].includes(s.status)) ? 2000 : null));
  const [q, setQ] = useState("");
  const [act, setAct] = useState("");
  const [explain, setExplain] = useState(false);
  const [busy, setBusy] = useState(false);
  const [res, setRes] = useState<SearchResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [addOpen, setAddOpen] = useState(false);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const acts = Array.from(new Set((sources.data ?? []).map((s) => s.short_name).filter(Boolean))) as string[];

  const search = async () => {
    setBusy(true);
    setError(null);
    try { setRes((await api.post<SearchResponse>("/legal/search", { query: q, act: act || null, explain })).data); }
    catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Legal Research" description="Search uploaded, versioned legal sources (BNS, BNSS, BSA, Constitution, historical IPC/CrPC/Evidence Act). Statutory text is shown verbatim; AI explanations are labelled separately."
        actions={user?.role === "admin" && <Button onClick={() => setAddOpen(true)}><Plus className="h-4 w-4" /> Add legal source</Button>} />
      <div className="grid gap-4 lg:grid-cols-[1fr_340px]">
        <div className="space-y-4">
          <Card>
            <CardBody>
              <form className="flex flex-wrap gap-2" onSubmit={(e) => { e.preventDefault(); search(); }}>
                <div className="relative min-w-[260px] flex-1">
                  <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
                  <Input className="pl-8" placeholder='e.g. "Section 309 BNS", "punishment for robbery", "धारा 309"' value={q} onChange={(e) => setQ(e.target.value)} aria-label="Legal query" />
                </div>
                <Select className="w-36" value={act} onChange={(e) => setAct(e.target.value)} aria-label="Act filter"><option value="">All sources</option>{acts.map((a) => <option key={a}>{a}</option>)}</Select>
                <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={explain} onChange={(e) => setExplain(e.target.checked)} /> AI explanation</label>
                <Button type="submit" loading={busy} disabled={q.trim().length < 2}>Search</Button>
              </form>
            </CardBody>
          </Card>
          {error && <ErrorBox message={error} />}
          {res?.message && <Notice>{res.message}</Notice>}
          {res && !res.results.length && !res.message && <Card><EmptyState title="No matching provision found" description="Nothing is generated from model memory: upload the official text of the Act to search it." /></Card>}
          {res?.results.map((r) => (
            <Card key={r.chunk_id}>
              <CardHeader title={<span>{r.legal.act_name ?? r.document_title}{r.section_number ? ` - Section ${r.section_number}` : ""}</span>}
                description={[r.legal.version, r.legal.effective_date && `effective ${r.legal.effective_date}`, `p.${r.page_start}`].filter(Boolean).join(" · ")}
                actions={<>
                  <Badge tone={r.legal.is_official_text ? "green" : "amber"}>{r.legal.is_official_text ? "Official text" : "Not official text"}</Badge>
                  {r.legal.is_historical && <Badge tone="slate">Historical{r.legal.replaced_by ? ` → ${r.legal.replaced_by}` : ""}</Badge>}
                  <Button size="sm" variant="ghost" onClick={() => setViewer({ documentId: r.document_id, page: r.page_start, passage: r.text.slice(0, 300) })}>Open source</Button>
                </>} />
              <CardBody>
                <div className="mb-2 text-[11px] font-semibold uppercase tracking-wide text-slate-500">{r.text_label}</div>
                <pre className="whitespace-pre-wrap rounded border-l-4 border-navy-700 bg-slate-50 p-3 font-serif text-sm leading-relaxed text-slate-800">{r.text}</pre>
                <div className="mt-2 text-[11px] text-slate-500">
                  {r.legal.source_url && <>Source: <a className="underline" href={r.legal.source_url} target="_blank" rel="noreferrer">{r.legal.source_url}</a> · </>}
                  {r.legal.verification_date && <>verified {r.legal.verification_date}{r.legal.verified_by ? ` by ${r.legal.verified_by}` : ""} · </>}
                  {r.scores.exact_section_match ? "exact section match" : `rerank ${r.scores.rerank?.toFixed?.(2) ?? "—"}`}
                </div>
              </CardBody>
            </Card>
          ))}
          {res?.explanation && (
            <Card className="border-violet-200">
              <CardHeader title="AI-generated explanation" description={res.explanation.label} />
              <CardBody>
                {res.explanation.llm_error ? <ErrorBox message={res.explanation.llm_error} /> : (
                  <CitationText text={res.explanation.text} citations={res.explanation.citations} onCite={(c) => c.document_id && setViewer({ documentId: c.document_id, page: c.page, passage: c.passage })} />
                )}
              </CardBody>
            </Card>
          )}
        </div>
        <Card className="h-fit">
          <CardHeader title="Legal sources" description="Only uploaded sources are searchable." />
          {sources.loading ? <Spinner className="px-4" /> : !sources.data?.length ? (
            <EmptyState icon={<BookOpen className="h-5 w-5" />} title="No legal sources uploaded"
              description="An administrator should upload the official Gazette / India Code PDFs of BNS, BNSS, BSA and the Constitution with their version details." />
          ) : (
            <div className="divide-y divide-slate-100">
              {sources.data.map((s) => (
                <div key={s.document_id} className="px-5 py-3 text-sm">
                  <div className="flex items-center justify-between gap-2"><span className="font-medium">{s.act_name}</span><StatusBadge status={s.status} /></div>
                  <div className="mt-1 flex flex-wrap gap-1">
                    {s.short_name && <Badge tone="navy">{s.short_name}</Badge>}
                    <Badge tone={s.is_official_text ? "green" : "amber"}>{s.is_official_text ? "official" : "not official"}</Badge>
                    {s.is_historical && <Badge>historical</Badge>}
                  </div>
                  <div className="mt-1 text-[11px] text-slate-500">{[s.version, `${s.pages} pages`, `${s.chunks} chunks`].filter(Boolean).join(" · ")}</div>
                </div>
              ))}
            </div>
          )}
        </Card>
      </div>
      <UploadDialog open={addOpen} onOpenChange={setAddOpen} legal onUploaded={() => sources.reload(true)} />
      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
