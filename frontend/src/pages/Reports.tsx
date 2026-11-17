import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, Legend, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { CheckCircle2, FileDown, FlaskConical, Play, Trash2 } from "lucide-react";
import { api, downloadFile, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { canWrite, useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorBox, Notice, PageHeader, Spinner, Table, Td, Th } from "@/components/ui/primitives";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { CitationText } from "@/components/CitationText";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { useToast } from "@/components/Toast";
import type { Citation, ReportItem } from "@/types";
import { formatDate, pct } from "@/utils/format";

const statusTone = (s: string) => (s === "human_verified" ? "green" : s === "failed" ? "red" : s === "generating" ? "blue" : "amber");

export default function ReportsPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const reports = useApi<ReportItem[]>("/reports", undefined, (d) => (d?.some((r) => r.status === "generating") ? 3000 : null));
  return (
    <div>
      <PageHeader title="Reports" description="AI-generated drafts (case summaries, comparisons) requiring human verification, and the experimental evaluation." />
      <Tabs defaultValue="reports">
        <TabsList><TabsTrigger value="reports">Reports</TabsTrigger><TabsTrigger value="evaluation">Experimental evaluation</TabsTrigger></TabsList>
        <TabsContent value="reports">
          <div className="grid gap-4 lg:grid-cols-[320px_1fr]">
            <Card className="h-fit">
              {reports.loading ? <Spinner className="px-4" /> : !reports.data?.length ? (
                <EmptyState title="No reports yet" description="Generate a case summary from a case workspace or save a document comparison." />
              ) : (
                <div className="divide-y divide-slate-100">
                  {reports.data.map((r) => (
                    <button key={r.id} onClick={() => nav(`/reports/${r.id}`)} className={`block w-full px-4 py-3 text-left hover:bg-slate-50 ${id === r.id ? "bg-navy-50" : ""}`}>
                      <div className="text-sm font-medium text-slate-800">{r.title}</div>
                      <div className="mt-1 flex items-center gap-2 text-[11px] text-slate-400">
                        <Badge tone={statusTone(r.status)}>{r.status.replace("_", " ")}</Badge>{formatDate(r.created_at, true)}
                      </div>
                      {r.status === "generating" && r.progress && <div className="mt-1 text-[11px] text-blue-700">{r.progress}</div>}
                    </button>
                  ))}
                </div>
              )}
            </Card>
            <div>{id ? <ReportView key={id} id={id} canEdit={canWrite(user)} onChanged={() => reports.reload(true)} onDeleted={() => { reports.reload(true); nav("/reports"); }} />
              : <Card><EmptyState title="Select a report" /></Card>}</div>
          </div>
        </TabsContent>
        <TabsContent value="evaluation"><Evaluation isAdmin={user?.role === "admin"} /></TabsContent>
      </Tabs>
    </div>
  );
}

function ReportView({ id, canEdit, onChanged, onDeleted }: { id: string; canEdit: boolean; onChanged: () => void; onDeleted: () => void }) {
  const toast = useToast();
  const r = useApi<ReportItem>(`/reports/${id}`, undefined, (d) => (d?.status === "generating" ? 2500 : null));
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  if (r.loading && !r.data) return <Spinner />;
  if (r.error) return <ErrorBox message={r.error} />;
  const rep = r.data!;
  const c = rep.content ?? {};
  const cite = (x: Citation) => x.document_id && setViewer({ documentId: x.document_id, page: x.page, passage: x.passage });
  const exp = async (format: string) => {
    try { await downloadFile(`/reports/${id}/export`, { format }, `report.${format}`); } catch (e) { toast(errorMessage(e), "error"); }
  };
  const setStatus = async (status: string) => { await api.patch(`/reports/${id}`, { status }); r.reload(true); onChanged(); toast(status === "human_verified" ? "Marked as human verified" : "Marked as draft"); };

  return (
    <Card>
      <CardHeader title={rep.title} description={`${rep.report_type.replace("_", " ")} · ${formatDate(rep.created_at, true)}`}
        actions={rep.status !== "generating" && rep.status !== "failed" && <>
          <Button size="sm" variant="secondary" onClick={() => exp("pdf")}><FileDown className="h-4 w-4" /> PDF</Button>
          <Button size="sm" variant="secondary" onClick={() => exp("docx")}><FileDown className="h-4 w-4" /> DOCX</Button>
          {canEdit && (rep.status === "draft"
            ? <Button size="sm" onClick={() => setStatus("human_verified")}><CheckCircle2 className="h-4 w-4" /> Mark verified</Button>
            : <Button size="sm" variant="secondary" onClick={() => setStatus("draft")}>Revert to draft</Button>)}
          {canEdit && <Button size="icon" variant="ghost" aria-label="Delete report" onClick={async () => { if (window.confirm("Delete report?")) { await api.delete(`/reports/${id}`); onDeleted(); } }}><Trash2 className="h-4 w-4 text-red-600" /></Button>}
        </>} />
      <CardBody className="space-y-5">
        {rep.status === "generating" && <Spinner label={rep.progress ?? "Generating with the local LLM…"} />}
        {rep.status === "failed" && <ErrorBox message={rep.error ?? "Generation failed"} />}
        <Badge tone={statusTone(rep.status)}>{rep.status === "human_verified" ? "HUMAN VERIFIED" : rep.status.toUpperCase()}</Badge>
        {c.disclaimer && <Notice>{c.disclaimer}</Notice>}
        {rep.report_type === "case_summary" && rep.status !== "generating" && rep.status !== "failed" && (
          <>
            {c.sections?.map((s: { key: string; title: string; text: string; abstained: boolean; citations: Citation[]; llm_error?: string }) => (
              <section key={s.key}>
                <h3 className="mb-1 text-sm font-semibold text-slate-900">{s.title}</h3>
                {s.llm_error ? <ErrorBox message={s.llm_error} /> : <CitationText text={s.text} citations={s.citations} onCite={cite} />}
              </section>
            ))}
            {c.witness_statements?.length > 0 && (
              <section>
                <h3 className="mb-1 text-sm font-semibold">Witness statements</h3>
                {c.witness_statements.map((w: { document_id: string; document_title: string; text: string; citations: Citation[] }) => (
                  <div key={w.document_id} className="mb-2 rounded border border-slate-200 p-3"><div className="mb-1 text-xs font-medium text-slate-500">{w.document_title}</div>
                    <CitationText text={w.text} citations={w.citations} onCite={cite} /></div>
                ))}
              </section>
            )}
            {c.important_dates?.length > 0 && (
              <section>
                <h3 className="mb-1 text-sm font-semibold">Important dates</h3>
                <Table><thead><tr><Th>Date</Th><Th>Event</Th><Th>Source</Th></tr></thead><tbody>
                  {c.important_dates.flatMap((d: { date: string; events: { time: string | null; description: string; document_title: string; page: number; nature: string }[] }) =>
                    d.events.map((e, i) => <tr key={d.date + i}><Td className="whitespace-nowrap font-mono text-xs">{d.date} {e.time ?? ""}</Td><Td className="text-xs">{e.description}</Td><Td className="whitespace-nowrap text-xs">{e.document_title} p.{e.page}<div className="text-slate-400">{e.nature}</div></Td></tr>))}
                </tbody></Table>
              </section>
            )}
            {c.people?.length > 0 && (
              <section><h3 className="mb-1 text-sm font-semibold">People and entities mentioned</h3>
                <div className="flex flex-wrap gap-1.5">{c.people.map((p: { value: string; mentions: number }) => <Badge key={p.value}>{p.value} · {p.mentions}</Badge>)}</div></section>
            )}
            {c.missing_information?.length > 0 && (
              <section><h3 className="mb-1 text-sm font-semibold">Missing information & unresolved discrepancies</h3>
                <ul className="list-disc space-y-1 pl-5 text-sm text-slate-700">{c.missing_information.map((m: string, i: number) => <li key={i}>{m}</li>)}</ul></section>
            )}
          </>
        )}
        {rep.report_type === "comparison" && (
          <section className="space-y-2 text-sm">
            <p>A: <b>{c.a?.title}</b> · B: <b>{c.b?.title}</b></p>
            <ul className="list-disc space-y-1 pl-5">{c.structured?.conflicts?.map((x: { message: string }, i: number) => <li key={i}>{x.message}</li>)}</ul>
            <p className="text-xs text-slate-500">{c.structured?.common?.length ?? 0} common facts · {c.structured?.different?.length ?? 0} differing facts. <Link className="underline" to="/compare">Open comparison tool</Link></p>
          </section>
        )}
      </CardBody>
      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
    </Card>
  );
}

interface EvalSummary { [k: string]: number | null }
interface EvalResponse { state: { running: boolean; error: string | null }; log: string[];
  results: null | { timestamp: string; questions: number; environment: Record<string, unknown>; summary: Record<string, EvalSummary>;
    avg_document_processing_seconds: number | null; by_category: Record<string, Record<string, { "recall@5": number | null; mrr: number | null }>> } }

function Evaluation({ isAdmin }: { isAdmin: boolean }) {
  const toast = useToast();
  const ev = useApi<EvalResponse>("/evaluation/results", undefined, (d) => (d?.state.running ? 3000 : null));
  const [configs, setConfigs] = useState(["vector", "hybrid", "proposed"]);
  const [generation, setGeneration] = useState(true);
  const run = async () => {
    try { await api.post("/evaluation/run", { configs, generation }); toast("Evaluation started", "info"); setTimeout(() => ev.reload(true), 800); }
    catch (e) { toast(errorMessage(e), "error"); }
  };
  const r = ev.data?.results;
  const cfgs = r ? Object.keys(r.summary) : [];
  const chart = (keys: string[]) => keys.map((k) => ({ metric: k, ...Object.fromEntries(cfgs.map((c) => [c, r!.summary[c][k] ?? 0])) }));
  const colors: Record<string, string> = { vector: "#94a3b8", hybrid: "#3b82f6", proposed: "#1e3a8a" };
  const env = r?.environment as Record<string, string | boolean | number | null> | undefined;

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Run evaluation" description="Runs evaluation/dataset/eval_dataset.json against the configurations. Results are measured, never estimated, and saved as JSON/CSV/PNG in evaluation/results/." />
        <CardBody className="flex flex-wrap items-center gap-4">
          {["vector", "hybrid", "proposed"].map((c) => (
            <label key={c} className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={configs.includes(c)} disabled={!isAdmin}
              onChange={(e) => setConfigs((x) => (e.target.checked ? [...x, c] : x.filter((y) => y !== c)))} />
              {c === "vector" ? "Baseline 1: vector-only" : c === "hybrid" ? "Baseline 2: hybrid + RRF" : "Proposed: hybrid + RRF + rerank + citation validation"}</label>
          ))}
          <label className="flex items-center gap-1.5 text-sm"><input type="checkbox" checked={generation} disabled={!isAdmin} onChange={(e) => setGeneration(e.target.checked)} /> include generation metrics (LLM)</label>
          {isAdmin ? <Button onClick={run} loading={ev.data?.state.running} disabled={!configs.length}><Play className="h-4 w-4" /> Run</Button> : <span className="text-xs text-slate-500">Only administrators can start runs.</span>}
        </CardBody>
        {ev.data?.state.error && <ErrorBox className="mx-5 mb-4" message={ev.data.state.error} />}
        {(ev.data?.log.length ?? 0) > 0 && <pre className="mx-5 mb-4 max-h-40 overflow-auto rounded bg-slate-900 p-3 text-[11px] text-slate-200">{ev.data!.log.join("\n")}</pre>}
      </Card>
      {!r ? <Card><EmptyState icon={<FlaskConical className="h-5 w-5" />} title="No evaluation results yet" description="Run the evaluation above or with: python evaluation/scripts/run_evaluation.py" /></Card> : (
        <>
          {env?.embedding_provider === "hashing" && <Notice>These results were produced with the test (hashing) embedder and are not representative of the semantic models.</Notice>}
          <Card>
            <CardHeader title={`Results · run ${r.timestamp}`} description={`${r.questions} questions · embedding ${env?.embedding_model} · reranker ${env?.reranker_model} · LLM ${env?.llm ?? "not evaluated"} · avg ingestion ${r.avg_document_processing_seconds ?? "—"} s/doc`} />
            <Table>
              <thead><tr><Th>Configuration</Th>{["Recall@5", "Precision@5", "MRR", "nDCG@5", "Faithfulness", "Answer rel.", "Citation acc.", "Abstention acc.", "Retrieval ms", "Total ms"].map((h) => <Th key={h}>{h}</Th>)}</tr></thead>
              <tbody>{cfgs.map((c) => { const s = r.summary[c]; return (
                <tr key={c}><Td className="font-medium">{c}</Td>
                  {["recall@5", "precision@5", "mrr", "ndcg@5", "faithfulness", "answer_relevance", "citation_accuracy", "abstention_accuracy"].map((k) => <Td key={k} className="tabular-nums">{pct(s[k])}</Td>)}
                  <Td className="tabular-nums">{s.retrieval_ms?.toFixed(0) ?? "—"}</Td><Td className="tabular-nums">{s.total_ms?.toFixed(0) ?? "—"}</Td></tr>); })}
              </tbody>
            </Table>
          </Card>
          <div className="grid gap-4 lg:grid-cols-2">
            {[["Retrieval", ["recall@5", "precision@5", "mrr", "ndcg@5"]], ["Generation", ["faithfulness", "answer_relevance", "citation_accuracy", "abstention_accuracy"]]].map(([title, keys]) => (
              <Card key={title as string}><CardHeader title={`${title} metrics`} />
                <CardBody className="h-64">
                  <ResponsiveContainer width="100%" height="100%">
                    <BarChart data={chart(keys as string[])} margin={{ left: -20 }}>
                      <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                      <XAxis dataKey="metric" tick={{ fontSize: 11 }} /><YAxis domain={[0, 1]} tick={{ fontSize: 11 }} /><Tooltip formatter={(v: number) => pct(v)} /><Legend wrapperStyle={{ fontSize: 11 }} />
                      {cfgs.map((c) => <Bar key={c} dataKey={c} fill={colors[c]} radius={[2, 2, 0, 0]} />)}
                    </BarChart>
                  </ResponsiveContainer>
                </CardBody></Card>
            ))}
          </div>
          <Card><CardHeader title="Retrieval by question category (Recall@5 / MRR)" />
            <Table><thead><tr><Th>Category</Th>{cfgs.map((c) => <Th key={c}>{c}</Th>)}</tr></thead>
              <tbody>{Object.entries(r.by_category).map(([cat, v]) => (
                <tr key={cat}><Td>{cat}</Td>{cfgs.map((c) => <Td key={c} className="tabular-nums text-xs">{v[c]?.["recall@5"] === null ? "n/a (unanswerable)" : `${pct(v[c]?.["recall@5"])} / ${pct(v[c]?.mrr)}`}</Td>)}</tr>
              ))}</tbody></Table>
          </Card>
        </>
      )}
    </div>
  );
}
