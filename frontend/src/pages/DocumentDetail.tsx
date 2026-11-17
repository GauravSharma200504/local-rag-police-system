import { useEffect, useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, Check, Eye, RefreshCw, Save, Trash2, X } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { canWrite, useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorBox, Input, Label, Notice, PageHeader, Select, Spinner } from "@/components/ui/primitives";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { DocTypeBadge, isProcessing, StatusBadge } from "@/components/StatusBadge";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { useToast } from "@/components/Toast";
import { DOC_TYPES, type CaseItem, type DocumentItem, type Entity } from "@/types";
import { ENTITY_LABELS, formatBytes, formatDate } from "@/utils/format";

interface Chunk { id: string; chunk_index: number; page_start: number; page_end: number; heading: string | null; section_number: string | null; token_count: number; text: string }

export default function DocumentDetailPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const toast = useToast();
  const doc = useApi<DocumentItem>(`/documents/${id}`, undefined, (d) => (d && isProcessing(d.status) ? 1500 : null));
  const indexed = doc.data?.status === "indexed";
  const chunks = useApi<Chunk[]>(indexed ? `/documents/${id}/chunks` : null);
  const entities = useApi<Entity[]>(indexed ? `/documents/${id}/entities` : null);
  const { data: cases } = useApi<CaseItem[]>("/cases");
  const [form, setForm] = useState<Partial<DocumentItem>>({});
  const [saving, setSaving] = useState(false);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  useEffect(() => { if (doc.data) setForm(doc.data); }, [doc.data?.id, doc.data?.updated_at]); // eslint-disable-line react-hooks/exhaustive-deps

  if (doc.loading && !doc.data) return <Spinner />;
  if (doc.error) return <ErrorBox message={doc.error} />;
  const d = doc.data!;
  const editable = canWrite(user) && d.can_modify;

  const save = async () => {
    setSaving(true);
    try {
      await api.patch(`/documents/${d.id}`, {
        title: form.title, doc_type: form.doc_type, incident_date: form.incident_date || null, police_station: form.police_station,
        district: form.district, language: form.language, classification: form.classification,
        ...(form.case_id ? { case_id: form.case_id } : { clear_case: true }),
      });
      toast("Metadata saved");
      doc.reload(true);
    } catch (e) { toast(errorMessage(e), "error"); } finally { setSaving(false); }
  };
  const reviewEntity = async (e: Entity, status: string) => {
    try { await api.patch(`/entities/${e.id}`, { verification_status: status }); entities.reload(true); } catch (err) { toast(errorMessage(err), "error"); }
  };
  const field = (k: keyof DocumentItem) => ({ value: (form[k] as string) ?? "", onChange: (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value })), disabled: !editable });
  const grouped = (entities.data ?? []).reduce<Record<string, Entity[]>>((acc, e) => { (acc[e.entity_type] ??= []).push(e); return acc; }, {});

  return (
    <div>
      <Link to="/documents" className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"><ArrowLeft className="h-3.5 w-3.5" /> Documents</Link>
      <PageHeader title={d.title} description={`${d.original_filename} · ${formatBytes(d.size_bytes)} · SHA-256 ${d.sha256?.slice(0, 16)}…`}
        actions={<>
          <Button variant="secondary" disabled={!indexed} onClick={() => setViewer({ documentId: d.id, page: 1 })}><Eye className="h-4 w-4" /> Preview</Button>
          {editable && <Button variant="secondary" disabled={isProcessing(d.status)} onClick={async () => { await api.post(`/documents/${d.id}/reprocess`); toast("Reprocessing started"); doc.reload(true); }}><RefreshCw className="h-4 w-4" /> Reprocess</Button>}
          {editable && <Button variant="destructive" onClick={async () => { if (!window.confirm("Delete this document and all derived data?")) return; await api.delete(`/documents/${d.id}`); toast("Deleted"); nav("/documents"); }}><Trash2 className="h-4 w-4" /> Delete</Button>}
        </>} />
      <div className="grid gap-4 lg:grid-cols-3">
        <Card>
          <CardHeader title="Processing" />
          <CardBody className="space-y-2 text-sm">
            <div className="flex items-center gap-2"><StatusBadge status={d.status} /><DocTypeBadge type={d.doc_type} /></div>
            {d.status_detail && <p className="text-xs text-slate-600">{d.status_detail}</p>}
            {d.error_message && <ErrorBox message={d.error_message} />}
            <dl className="grid grid-cols-2 gap-y-1 text-xs">
              <dt className="text-slate-500">Pages</dt><dd>{d.page_count}</dd>
              <dt className="text-slate-500">OCR pages</dt><dd>{d.ocr_pages.length ? d.ocr_pages.join(", ") : "none"}</dd>
              <dt className="text-slate-500">Chunks</dt><dd>{d.chunk_count}</dd>
              <dt className="text-slate-500">Embedding model</dt><dd className="break-all">{d.embedding_model ?? "—"}</dd>
              <dt className="text-slate-500">Processing time</dt><dd>{d.processing_seconds ? `${d.processing_seconds} s` : "—"}</dd>
              <dt className="text-slate-500">Uploaded</dt><dd>{formatDate(d.created_at, true)}</dd>
            </dl>
            {Array.isArray(d.metadata?.extraction_warnings) && (d.metadata.extraction_warnings as string[]).length > 0 && (
              <Notice>{(d.metadata.extraction_warnings as string[]).join(" · ")}</Notice>
            )}
          </CardBody>
        </Card>
        <Card className="lg:col-span-2">
          <CardHeader title="Metadata" description="Metadata is entered by users; nothing here is inferred by the AI." actions={editable && <Button size="sm" onClick={save} loading={saving}><Save className="h-4 w-4" /> Save</Button>} />
          <CardBody className="grid grid-cols-2 gap-3 md:grid-cols-3">
            <div className="col-span-2"><Label>Title</Label><Input {...field("title")} /></div>
            <div><Label>Type</Label><Select {...field("doc_type")}>{DOC_TYPES.map((t) => <option key={t}>{t}</option>)}</Select></div>
            <div><Label>Case</Label><Select {...field("case_id")}><option value="">— none —</option>{cases?.map((c) => <option key={c.id} value={c.id}>{c.case_number}</option>)}</Select></div>
            <div><Label>Incident date</Label><Input type="date" {...field("incident_date")} /></div>
            <div><Label>Language</Label><Select {...field("language")}><option value="">unknown</option><option value="en">en</option><option value="hi">hi</option><option value="mixed">mixed</option></Select></div>
            <div><Label>Police station</Label><Input {...field("police_station")} /></div>
            <div><Label>District</Label><Input {...field("district")} /></div>
            <div><Label>Classification</Label><Select {...field("classification")}><option>restricted</option><option>confidential</option><option>internal</option></Select></div>
          </CardBody>
        </Card>
      </div>
      {indexed && (
        <Tabs defaultValue="entities" className="mt-6">
          <TabsList><TabsTrigger value="entities">Extracted entities ({entities.data?.length ?? 0})</TabsTrigger><TabsTrigger value="text">Extracted text & chunks ({chunks.data?.length ?? 0})</TabsTrigger></TabsList>
          <TabsContent value="entities">
            {entities.loading ? <Spinner /> : !entities.data?.length ? <EmptyState title="No entities extracted" /> : (
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
                {Object.entries(grouped).map(([type, list]) => (
                  <Card key={type}>
                    <CardHeader title={ENTITY_LABELS[type] ?? type} description={`${list.length} mention(s) · rule-based extraction, unverified unless reviewed`} />
                    <div className="divide-y divide-slate-100">
                      {list.map((e) => (
                        <div key={e.id} className="px-4 py-2">
                          <div className="flex items-center justify-between gap-2">
                            <button className="text-left text-sm font-medium text-slate-800 hover:text-navy-700" onClick={() => setViewer({ documentId: d.id, page: e.page, passage: e.context })}>{e.value}</button>
                            <div className="flex items-center gap-1">
                              <Badge tone={e.verification_status === "verified" ? "green" : e.verification_status === "rejected" ? "red" : "slate"}>{e.verification_status}</Badge>
                              {editable && <>
                                <button title="Mark verified" aria-label="Mark verified" onClick={() => reviewEntity(e, "verified")} className="rounded p-0.5 text-slate-400 hover:text-emerald-600"><Check className="h-3.5 w-3.5" /></button>
                                <button title="Reject" aria-label="Reject" onClick={() => reviewEntity(e, "rejected")} className="rounded p-0.5 text-slate-400 hover:text-red-600"><X className="h-3.5 w-3.5" /></button>
                              </>}
                            </div>
                          </div>
                          <p className="mt-0.5 line-clamp-2 text-[11px] text-slate-500">p.{e.page} · {e.context}</p>
                        </div>
                      ))}
                    </div>
                  </Card>
                ))}
              </div>
            )}
          </TabsContent>
          <TabsContent value="text">
            <div className="space-y-3">
              {chunks.data?.map((c) => (
                <Card key={c.id}>
                  <div className="flex items-center gap-2 border-b border-slate-100 px-4 py-2 text-xs text-slate-500">
                    <Badge>#{c.chunk_index}</Badge> pages {c.page_start}{c.page_end !== c.page_start && `–${c.page_end}`} · {c.token_count} tokens
                    {c.heading && <span className="truncate">· {c.heading}</span>}{c.section_number && <Badge tone="green">Section {c.section_number}</Badge>}
                  </div>
                  <pre className="whitespace-pre-wrap px-4 py-3 font-sans text-xs leading-relaxed text-slate-700">{c.text}</pre>
                </Card>
              ))}
            </div>
          </TabsContent>
        </Tabs>
      )}
      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
