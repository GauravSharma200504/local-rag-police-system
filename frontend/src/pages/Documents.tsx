import { useState } from "react";
import { Link } from "react-router-dom";
import { Eye, RefreshCw, Search, Trash2, Upload } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { canWrite, useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Card, EmptyState, ErrorBox, Input, PageHeader, Select, Spinner, Table, Td, Th } from "@/components/ui/primitives";
import { DocTypeBadge, isProcessing, StatusBadge } from "@/components/StatusBadge";
import { UploadDialog } from "@/components/UploadDialog";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { useToast } from "@/components/Toast";
import { DOC_TYPES, type CaseItem, type DocumentItem } from "@/types";
import { formatBytes, formatDate } from "@/utils/format";

interface Page { total: number; items: DocumentItem[]; page: number; page_size: number }

export default function DocumentsPage() {
  const { user } = useAuth();
  const toast = useToast();
  const [filters, setFilters] = useState({ q: "", status: "", doc_type: "", case_id: "" });
  const [page, setPage] = useState(1);
  const [uploadOpen, setUploadOpen] = useState(false);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const params = { ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v)), page, page_size: 25 };
  const docs = useApi<Page>("/documents", params, (d) => (d?.items.some((x) => isProcessing(x.status)) ? 2000 : null));
  const { data: cases } = useApi<CaseItem[]>("/cases");
  const set = (k: keyof typeof filters) => (e: { target: { value: string } }) => { setPage(1); setFilters((f) => ({ ...f, [k]: e.target.value })); };

  const reprocess = async (d: DocumentItem) => {
    try { await api.post(`/documents/${d.id}/reprocess`); toast("Reprocessing started"); docs.reload(true); } catch (e) { toast(errorMessage(e), "error"); }
  };
  const remove = async (d: DocumentItem) => {
    if (!window.confirm(`Delete "${d.title}"? Its chunks, embeddings, entities and stored file are removed permanently.`)) return;
    try { await api.delete(`/documents/${d.id}`); toast("Document deleted"); docs.reload(true); } catch (e) { toast(errorMessage(e), "error"); }
  };

  return (
    <div>
      <PageHeader title="Documents" description="Upload, search and manage police documents. Processing runs locally: extraction → OCR → chunking → embedding → indexing."
        actions={canWrite(user) && <Button onClick={() => setUploadOpen(true)}><Upload className="h-4 w-4" /> Upload</Button>} />
      <Card>
        <div className="grid grid-cols-1 gap-3 border-b border-slate-100 p-4 md:grid-cols-4">
          <div className="relative">
            <Search className="absolute left-2.5 top-2.5 h-4 w-4 text-slate-400" />
            <Input className="pl-8" placeholder="Search title, file, station, case…" value={filters.q} onChange={set("q")} aria-label="Search documents" />
          </div>
          <Select value={filters.doc_type} onChange={set("doc_type")} aria-label="Filter by type"><option value="">All types</option>{DOC_TYPES.map((t) => <option key={t}>{t}</option>)}</Select>
          <Select value={filters.status} onChange={set("status")} aria-label="Filter by status">
            <option value="">All statuses</option>{["uploaded", "extracting", "ocr", "chunking", "embedding", "indexed", "failed"].map((s) => <option key={s}>{s}</option>)}
          </Select>
          <Select value={filters.case_id} onChange={set("case_id")} aria-label="Filter by case"><option value="">All cases</option>{cases?.map((c) => <option key={c.id} value={c.id}>{c.case_number}</option>)}</Select>
        </div>
        {docs.error && <ErrorBox className="m-4" message={docs.error} />}
        {docs.loading && !docs.data ? <Spinner className="px-4" /> : docs.data && docs.data.items.length === 0 ? (
          <EmptyState title="No documents found" description="Upload FIRs, witness statements, reports or legal references to start." />
        ) : (
          <Table>
            <thead><tr><Th>Title</Th><Th>Type</Th><Th>Case</Th><Th>Pages</Th><Th>Chunks</Th><Th>Language</Th><Th>Status</Th><Th>Uploaded</Th><Th className="text-right">Actions</Th></tr></thead>
            <tbody>
              {docs.data?.items.map((d) => (
                <tr key={d.id} className="hover:bg-slate-50">
                  <Td>
                    <Link to={`/documents/${d.id}`} className="font-medium text-slate-900 hover:text-navy-700 hover:underline">{d.title}</Link>
                    <div className="text-[11px] text-slate-400">{d.original_filename} · {formatBytes(d.size_bytes)}{d.ocr_pages.length ? ` · OCR ${d.ocr_pages.length} p.` : ""}</div>
                    {d.status === "failed" && d.error_message && <div className="mt-1 max-w-md text-[11px] text-red-700">{d.error_message}</div>}
                    {isProcessing(d.status) && d.status_detail && <div className="text-[11px] text-blue-700">{d.status_detail}</div>}
                  </Td>
                  <Td><DocTypeBadge type={d.doc_type} /></Td>
                  <Td>{d.case_id ? <Link className="text-navy-700 hover:underline" to={`/cases/${d.case_id}`}>{d.case_number}</Link> : <span className="text-slate-400">—</span>}</Td>
                  <Td className="tabular-nums">{d.page_count || "—"}</Td>
                  <Td className="tabular-nums">{d.chunk_count || "—"}</Td>
                  <Td>{d.language ?? "—"}</Td>
                  <Td><StatusBadge status={d.status} /></Td>
                  <Td className="whitespace-nowrap text-xs">{formatDate(d.created_at, true)}</Td>
                  <Td className="whitespace-nowrap text-right">
                    <Button size="icon" variant="ghost" title="Preview" aria-label={`Preview ${d.title}`} disabled={d.status !== "indexed"} onClick={() => setViewer({ documentId: d.id, page: 1 })}><Eye className="h-4 w-4" /></Button>
                    {canWrite(user) && <Button size="icon" variant="ghost" title="Reprocess" aria-label={`Reprocess ${d.title}`} disabled={isProcessing(d.status)} onClick={() => reprocess(d)}><RefreshCw className="h-4 w-4" /></Button>}
                    {canWrite(user) && <Button size="icon" variant="ghost" title="Delete" aria-label={`Delete ${d.title}`} onClick={() => remove(d)}><Trash2 className="h-4 w-4 text-red-600" /></Button>}
                  </Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
        {docs.data && docs.data.total > docs.data.page_size && (
          <div className="flex items-center justify-between border-t border-slate-100 px-4 py-2 text-xs text-slate-500">
            <span>{docs.data.total} documents</span>
            <div className="flex gap-2">
              <Button size="sm" variant="secondary" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}>Previous</Button>
              <Button size="sm" variant="secondary" disabled={page * docs.data.page_size >= docs.data.total} onClick={() => setPage((p) => p + 1)}>Next</Button>
            </div>
          </div>
        )}
      </Card>
      <UploadDialog open={uploadOpen} onOpenChange={setUploadOpen} onUploaded={() => docs.reload(true)} />
      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
