import { useState } from "react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { ArrowLeft, FilePlus2, FileText, Link2, Trash2, Upload, UserPlus } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { canWrite, useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, EmptyState, ErrorBox, Notice, PageHeader, Select, Spinner, Table, Td, Th } from "@/components/ui/primitives";
import { Dialog, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { DocTypeBadge, isProcessing, StatusBadge } from "@/components/StatusBadge";
import { UploadDialog } from "@/components/UploadDialog";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { TimelineView } from "@/components/TimelineView";
import { useToast } from "@/components/Toast";
import AssistantPage from "@/pages/Assistant";
import type { CaseItem, DocumentItem, Entity, ReportItem, Timeline } from "@/types";
import { ENTITY_LABELS, formatDate } from "@/utils/format";

export default function CaseDetailPage() {
  const { id } = useParams();
  const nav = useNavigate();
  const { user } = useAuth();
  const toast = useToast();
  const kase = useApi<CaseItem>(`/cases/${id}`, undefined, (d) => (d?.documents?.some((x) => isProcessing(x.status)) ? 2000 : null));
  const timeline = useApi<Timeline>(`/cases/${id}/timeline`);
  const entities = useApi<Entity[]>(`/cases/${id}/entities`);
  const reports = useApi<ReportItem[]>("/reports", undefined, (d) => (d?.some((r) => r.status === "generating") ? 3000 : null));
  const [uploadOpen, setUploadOpen] = useState(false);
  const [assignOpen, setAssignOpen] = useState(false);
  const [memberOpen, setMemberOpen] = useState(false);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [entityType, setEntityType] = useState("");

  if (kase.loading && !kase.data) return <Spinner />;
  if (kase.error) return <ErrorBox message={kase.error} />;
  const c = kase.data!;
  const writer = canWrite(user);
  const caseReports = (reports.data ?? []).filter((r) => r.case_id === c.id);
  const ents = (entities.data ?? []).filter((e) => !entityType || e.entity_type === entityType);
  const entityGroups = ents.reduce<Record<string, { value: string; type: string; mentions: Entity[] }>>((acc, e) => {
    const k = `${e.entity_type}|${e.normalized_value}`;
    (acc[k] ??= { value: e.value, type: e.entity_type, mentions: [] }).mentions.push(e);
    return acc;
  }, {});

  const summarize = async () => {
    try {
      const r = await api.post<ReportItem>(`/cases/${c.id}/summary`);
      toast("Case summary generation started (runs on the local LLM; this can take a few minutes)", "info");
      reports.reload(true);
      nav(`/reports/${r.data.id}`);
    } catch (e) { toast(errorMessage(e), "error"); }
  };
  const open = (documentId: string, page: number, passage?: string) => setViewer({ documentId, page, passage });

  return (
    <div>
      <Link to="/cases" className="mb-3 inline-flex items-center gap-1 text-xs text-slate-500 hover:text-slate-800"><ArrowLeft className="h-3.5 w-3.5" /> Cases</Link>
      <PageHeader title={`${c.case_number} · ${c.title}`} description={[c.police_station, c.district, c.description].filter(Boolean).join(" · ")}
        actions={<>
          <Button variant="secondary" onClick={summarize} disabled={!c.documents?.some((d) => d.status === "indexed")}><FileText className="h-4 w-4" /> Generate case summary</Button>
          {writer && <Button variant="secondary" onClick={() => setAssignOpen(true)}><Link2 className="h-4 w-4" /> Add existing documents</Button>}
          {writer && <Button onClick={() => setUploadOpen(true)}><Upload className="h-4 w-4" /> Upload to case</Button>}
        </>} />
      <Tabs defaultValue="documents">
        <TabsList>
          <TabsTrigger value="documents">Documents ({c.documents?.length ?? 0})</TabsTrigger>
          <TabsTrigger value="timeline">Timeline{timeline.data?.conflicts.length ? ` (${timeline.data.conflicts.length} discrepancies)` : ""}</TabsTrigger>
          <TabsTrigger value="entities">Entities</TabsTrigger>
          <TabsTrigger value="assistant">Case assistant</TabsTrigger>
          <TabsTrigger value="reports">Reports ({caseReports.length})</TabsTrigger>
          <TabsTrigger value="members">Members</TabsTrigger>
        </TabsList>
        <TabsContent value="documents">
          <Card>
            {!c.documents?.length ? <EmptyState title="No documents in this case" action={writer && <Button size="sm" onClick={() => setUploadOpen(true)}><FilePlus2 className="h-4 w-4" /> Upload</Button>} /> : (
              <Table>
                <thead><tr><Th>Document</Th><Th>Type</Th><Th>Pages</Th><Th>Status</Th><Th>Uploaded</Th><Th /></tr></thead>
                <tbody>{c.documents.map((d: DocumentItem) => (
                  <tr key={d.id}>
                    <Td><Link to={`/documents/${d.id}`} className="font-medium hover:underline">{d.title}</Link><div className="text-[11px] text-slate-400">{d.original_filename}</div></Td>
                    <Td><DocTypeBadge type={d.doc_type} /></Td><Td>{d.page_count || "—"}</Td><Td><StatusBadge status={d.status} /></Td>
                    <Td className="text-xs">{formatDate(d.created_at, true)}</Td>
                    <Td><Button size="sm" variant="ghost" disabled={d.status !== "indexed"} onClick={() => open(d.id, 1)}>Preview</Button></Td>
                  </tr>
                ))}</tbody>
              </Table>
            )}
          </Card>
        </TabsContent>
        <TabsContent value="timeline">
          {timeline.loading ? <Spinner /> : timeline.error ? <ErrorBox message={timeline.error} /> : timeline.data && (
            <>
              <div className="mb-3 flex justify-end"><Button size="sm" variant="secondary" onClick={() => timeline.reload()}>Refresh timeline</Button></div>
              <TimelineView timeline={timeline.data} onOpen={open} />
            </>
          )}
        </TabsContent>
        <TabsContent value="entities">
          <Card>
            <CardHeader title="Entities across case documents" description="Rule-based extraction with source page. Identical values are grouped; similar names are NOT merged."
              actions={<Select className="h-8 w-48 text-xs" value={entityType} onChange={(e) => setEntityType(e.target.value)} aria-label="Entity type">
                <option value="">All types</option>{Object.entries(ENTITY_LABELS).map(([k, v]) => <option key={k} value={k}>{v}</option>)}
              </Select>} />
            {entities.loading ? <Spinner className="px-4" /> : !Object.keys(entityGroups).length ? <EmptyState title="No entities" /> : (
              <Table>
                <thead><tr><Th>Value</Th><Th>Type</Th><Th>Mentions (document · page)</Th></tr></thead>
                <tbody>{Object.values(entityGroups).map((g, i) => (
                  <tr key={i}>
                    <Td className="font-medium">{g.value}</Td><Td><Badge>{ENTITY_LABELS[g.type] ?? g.type}</Badge></Td>
                    <Td><div className="flex flex-wrap gap-1">{g.mentions.map((m) => (
                      <button key={m.id} onClick={() => open(m.document_id, m.page, m.context)} className="rounded bg-slate-100 px-1.5 py-0.5 text-[11px] text-slate-700 hover:bg-navy-100" title={m.context}>
                        {m.document_title} · p.{m.page}
                      </button>
                    ))}</div></Td>
                  </tr>
                ))}</tbody>
              </Table>
            )}
          </Card>
        </TabsContent>
        <TabsContent value="assistant"><AssistantPage caseId={c.id} /></TabsContent>
        <TabsContent value="reports">
          <Card>
            {!caseReports.length ? <EmptyState title="No reports yet" action={<Button size="sm" onClick={summarize}>Generate case summary</Button>} /> : (
              <div className="divide-y divide-slate-100">
                {caseReports.map((r) => (
                  <Link key={r.id} to={`/reports/${r.id}`} className="flex items-center justify-between px-5 py-3 hover:bg-slate-50">
                    <div><div className="text-sm font-medium">{r.title}</div><div className="text-[11px] text-slate-400">{formatDate(r.created_at, true)}{r.progress && r.status === "generating" ? ` · ${r.progress}` : ""}</div></div>
                    <Badge tone={r.status === "human_verified" ? "green" : r.status === "failed" ? "red" : r.status === "generating" ? "blue" : "amber"}>{r.status.replace("_", " ")}</Badge>
                  </Link>
                ))}
              </div>
            )}
          </Card>
        </TabsContent>
        <TabsContent value="members">
          <Card>
            <CardHeader title="Case members" description="Only members (and administrators) can access this case's documents." actions={writer && <Button size="sm" onClick={() => setMemberOpen(true)}><UserPlus className="h-4 w-4" /> Add member</Button>} />
            <CardBody className="space-y-2">
              {c.members?.map((m) => (
                <div key={m.id} className="flex items-center justify-between text-sm">
                  <span>{m.full_name || m.username} <span className="text-xs text-slate-400">@{m.username}</span> <Badge className="ml-1">{m.role}</Badge></span>
                  {writer && m.id !== user?.id && <Button size="icon" variant="ghost" aria-label={`Remove ${m.username}`} onClick={async () => { await api.delete(`/cases/${c.id}/members/${m.id}`); kase.reload(true); }}><Trash2 className="h-4 w-4 text-red-600" /></Button>}
                </div>
              ))}
            </CardBody>
          </Card>
        </TabsContent>
      </Tabs>
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} defaultCaseId={c.id} onUploaded={() => { kase.reload(true); setTimeout(() => { timeline.reload(true); entities.reload(true); }, 4000); }} />
      <AssignDialog open={assignOpen} onOpenChange={setAssignOpen} caseId={c.id} onDone={() => { kase.reload(true); timeline.reload(true); entities.reload(true); }} />
      <MemberDialog open={memberOpen} onOpenChange={setMemberOpen} caseId={c.id} existing={c.members?.map((m) => m.id) ?? []} onDone={() => kase.reload(true)} />
      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}

function AssignDialog({ open, onOpenChange, caseId, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; caseId: string; onDone: () => void }) {
  const docs = useApi<{ items: DocumentItem[] }>(open ? "/documents" : null, { page_size: 200 });
  const [sel, setSel] = useState<string[]>([]);
  const [error, setError] = useState<string | null>(null);
  const candidates = (docs.data?.items ?? []).filter((d) => d.case_id !== caseId && d.doc_type !== "Legal Document");
  const submit = async () => {
    try { await api.post(`/cases/${caseId}/documents`, { document_ids: sel }); setSel([]); onOpenChange(false); onDone(); } catch (e) { setError(errorMessage(e)); }
  };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Associate existing documents" description="Each association is an explicit, audited user action."
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!sel.length} onClick={submit}>Associate ({sel.length})</Button></>}>
      {docs.loading ? <Spinner /> : !candidates.length ? <EmptyState title="No other documents available" /> : (
        <div className="space-y-1">
          {candidates.map((d) => (
            <label key={d.id} className="flex items-center gap-2 rounded px-2 py-1.5 text-sm hover:bg-slate-50">
              <input type="checkbox" checked={sel.includes(d.id)} onChange={(e) => setSel((s) => (e.target.checked ? [...s, d.id] : s.filter((x) => x !== d.id)))} />
              <span className="flex-1 truncate">{d.title}</span><DocTypeBadge type={d.doc_type} />
              {d.case_number && <span className="text-[11px] text-amber-700">currently in {d.case_number}</span>}
            </label>
          ))}
        </div>
      )}
      <Notice className="mt-3">Moving a document from another case removes it from that case.</Notice>
      {error && <ErrorBox className="mt-2" message={error} />}
    </Dialog>
  );
}

function MemberDialog({ open, onOpenChange, caseId, existing, onDone }: { open: boolean; onOpenChange: (o: boolean) => void; caseId: string; existing: string[]; onDone: () => void }) {
  const users = useApi<{ id: string; username: string; full_name: string }[]>(open ? "/users/directory" : null);
  const [userId, setUserId] = useState("");
  const add = async () => { await api.post(`/cases/${caseId}/members`, { user_id: userId }); setUserId(""); onOpenChange(false); onDone(); };
  return (
    <Dialog open={open} onOpenChange={onOpenChange} title="Add case member"
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button><Button disabled={!userId} onClick={add}>Add</Button></>}>
      <Select value={userId} onChange={(e) => setUserId(e.target.value)} aria-label="User">
        <option value="">Select user…</option>
        {users.data?.filter((u) => !existing.includes(u.id)).map((u) => <option key={u.id} value={u.id}>{u.full_name || u.username} (@{u.username})</option>)}
      </Select>
    </Dialog>
  );
}
