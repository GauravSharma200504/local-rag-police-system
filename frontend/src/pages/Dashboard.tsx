import { Link } from "react-router-dom";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Activity, FileStack, FolderKanban, Layers, MessageSquare, ScanText } from "lucide-react";
import { useApi } from "@/hooks/useApi";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorBox, PageHeader, Spinner } from "@/components/ui/primitives";
import { DocTypeBadge, StatusBadge } from "@/components/StatusBadge";
import { formatDate } from "@/utils/format";
import type { DocStatus } from "@/types";

interface Dash {
  totals: { documents: number; chunks: number; cases: number; queries: number; reports: number; ocr_documents: number };
  status_counts: Record<string, number>;
  type_counts: Record<string, number>;
  language_counts: Record<string, number>;
  recent_documents: { id: string; title: string; doc_type: string; status: DocStatus; created_at: string }[];
  recent_activity: { type: string; config: string; results: number; abstained: boolean; total_ms: number; created_at: string }[];
  ingestion_trend: { date: string; count: number }[];
  performance: { avg_answer_ms: number | null; avg_retrieval_ms: number | null; avg_processing_seconds: number | null };
}
interface Models {
  llm: { reachable: boolean; model: string; model_available: boolean; hint?: string | null; error?: string };
  embedding: { model: string; provider: string; dim: number; loaded: boolean; is_test_embedder: boolean };
  reranker: { provider: string; model: string | null; loaded: boolean };
  ocr: { available: boolean; version: string | null; languages: string[] };
}

function Stat({ label, value, icon: Icon, sub }: { label: string; value: number | string; icon: typeof FileStack; sub?: string }) {
  return (
    <Card className="p-4">
      <div className="flex items-center justify-between">
        <span className="text-xs font-medium text-slate-500">{label}</span>
        <Icon className="h-4 w-4 text-slate-400" />
      </div>
      <div className="mt-2 text-2xl font-semibold tabular-nums text-slate-900">{value}</div>
      {sub && <div className="mt-0.5 text-[11px] text-slate-500">{sub}</div>}
    </Card>
  );
}

const NAVY = "#1a2d63";

export default function DashboardPage() {
  const { data, error, loading } = useApi<Dash>("/dashboard", undefined, 15_000);
  const { data: models } = useApi<Models>("/settings/models");
  if (loading && !data) return <Spinner />;
  if (error) return <ErrorBox message={error} />;
  if (!data) return null;
  const t = data.totals;
  const types = Object.entries(data.type_counts).map(([name, value]) => ({ name, value }));
  const statuses = ["uploaded", "extracting", "ocr", "chunking", "embedding", "indexed", "failed"].map((s) => ({ name: s, value: data.status_counts[s] ?? 0 }));
  const processing = statuses.filter((s) => !["indexed", "failed"].includes(s.name)).reduce((a, b) => a + b.value, 0);

  return (
    <div>
      <PageHeader title="Command Dashboard" description="Live statistics computed from the database for the documents you are authorized to access." />
      <div className="grid grid-cols-2 gap-4 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Documents" value={t.documents} icon={FileStack} sub={`${data.status_counts.failed ?? 0} failed · ${processing} processing`} />
        <Stat label="Indexed chunks" value={t.chunks} icon={Layers} />
        <Stat label="Cases" value={t.cases} icon={FolderKanban} />
        <Stat label="Queries" value={t.queries} icon={MessageSquare} sub={data.performance.avg_answer_ms ? `avg answer ${(data.performance.avg_answer_ms / 1000).toFixed(1)} s` : undefined} />
        <Stat label="OCR documents" value={t.ocr_documents} icon={ScanText} />
        <Stat label="Reports" value={t.reports} icon={Activity} sub={data.performance.avg_processing_seconds ? `avg ingest ${data.performance.avg_processing_seconds} s/doc` : undefined} />
      </div>

      <div className="mt-6 grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <CardHeader title="Document type distribution" />
          <CardBody className="h-64">
            {types.length ? (
              <ResponsiveContainer width="100%" height="100%">
                <BarChart data={types} margin={{ left: -20 }}>
                  <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                  <XAxis dataKey="name" tick={{ fontSize: 11 }} interval={0} />
                  <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                  <Tooltip />
                  <Bar dataKey="value" name="Documents" fill={NAVY} radius={[3, 3, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            ) : <EmptyState title="No documents yet" action={<Link to="/documents" className="text-sm text-navy-700 underline">Upload documents</Link>} />}
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Local model status" />
          <CardBody className="space-y-3 text-sm">
            {!models ? <Spinner /> : (
              <>
                <Row label="LLM (Ollama)" ok={models.llm.reachable && models.llm.model_available} value={models.llm.model} hint={models.llm.hint ?? undefined} />
                <Row label="Embeddings" ok value={models.embedding.model} warn={models.embedding.is_test_embedder}
                  hint={models.embedding.is_test_embedder ? "Test embedder active - not a semantic model" : `${models.embedding.dim}-d · ${models.embedding.loaded ? "loaded" : "loads on first use"}`} />
                <Row label="Reranker" ok value={models.reranker.model ?? "disabled"} hint={models.reranker.loaded ? "loaded" : "loads on first use"} />
                <Row label="OCR (Tesseract)" ok={models.ocr.available} value={models.ocr.version ?? "not found"} hint={models.ocr.languages.filter((l) => ["eng", "hin"].includes(l)).join(", ")} />
              </>
            )}
          </CardBody>
        </Card>
      </div>

      <div className="mt-4 grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Processing status" />
          <CardBody className="h-56">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={statuses} layout="vertical" margin={{ left: 10 }}>
                <XAxis type="number" allowDecimals={false} tick={{ fontSize: 11 }} />
                <YAxis type="category" dataKey="name" tick={{ fontSize: 11 }} width={70} />
                <Tooltip />
                <Bar dataKey="value" name="Documents" fill="#3b5a9e" radius={[0, 3, 3, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
        <Card>
          <CardHeader title="Recent uploads" actions={<Link to="/documents" className="text-xs text-navy-700 hover:underline">All documents</Link>} />
          <div className="divide-y divide-slate-100">
            {data.recent_documents.length === 0 && <EmptyState title="Nothing uploaded yet" />}
            {data.recent_documents.map((d) => (
              <Link key={d.id} to={`/documents/${d.id}`} className="flex items-center justify-between gap-2 px-5 py-2.5 hover:bg-slate-50">
                <div className="min-w-0">
                  <div className="truncate text-sm text-slate-800">{d.title}</div>
                  <div className="mt-0.5 flex items-center gap-1.5"><DocTypeBadge type={d.doc_type} /><span className="text-[11px] text-slate-400">{formatDate(d.created_at, true)}</span></div>
                </div>
                <StatusBadge status={d.status} />
              </Link>
            ))}
          </div>
        </Card>
        <Card>
          <CardHeader title="Recent AI activity" />
          <div className="divide-y divide-slate-100">
            {data.recent_activity.length === 0 && <EmptyState title="No queries yet" action={<Link to="/assistant" className="text-sm text-navy-700 underline">Ask the assistant</Link>} />}
            {data.recent_activity.map((a, i) => (
              <div key={i} className="flex items-center justify-between px-5 py-2.5 text-sm">
                <div>
                  <span className="capitalize text-slate-800">{a.type}</span>
                  <span className="ml-2 font-mono text-[11px] text-slate-400">{a.config}</span>
                  <div className="text-[11px] text-slate-400">{formatDate(a.created_at, true)}</div>
                </div>
                <div className="text-right">
                  {a.abstained ? <Badge tone="amber">abstained</Badge> : <Badge tone="green">{a.results} sources</Badge>}
                  {a.total_ms > 0 && <div className="text-[11px] text-slate-400">{(a.total_ms / 1000).toFixed(1)} s</div>}
                </div>
              </div>
            ))}
          </div>
        </Card>
      </div>
      {data.ingestion_trend.length > 0 && (
        <Card className="mt-4">
          <CardHeader title="Ingestion activity (last 14 days)" />
          <CardBody className="h-48">
            <ResponsiveContainer width="100%" height="100%">
              <BarChart data={data.ingestion_trend} margin={{ left: -20 }}>
                <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="#e2e8f0" />
                <XAxis dataKey="date" tick={{ fontSize: 11 }} />
                <YAxis allowDecimals={false} tick={{ fontSize: 11 }} />
                <Tooltip />
                <Bar dataKey="count" name="Uploaded" fill={NAVY} radius={[3, 3, 0, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </CardBody>
        </Card>
      )}
    </div>
  );
}

function Row({ label, value, ok, warn, hint }: { label: string; value: string; ok: boolean; warn?: boolean; hint?: string }) {
  return (
    <div className="flex items-start justify-between gap-3">
      <div>
        <div className="text-xs font-medium text-slate-500">{label}</div>
        <div className="break-all text-sm text-slate-800">{value}</div>
        {hint && <div className="text-[11px] text-slate-500">{hint}</div>}
      </div>
      <Badge tone={!ok ? "red" : warn ? "amber" : "green"}>{!ok ? "unavailable" : warn ? "test mode" : "ready"}</Badge>
    </div>
  );
}
