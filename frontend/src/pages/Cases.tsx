import { useState } from "react";
import { Link } from "react-router-dom";
import { FolderPlus } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { canWrite, useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState, ErrorBox, Input, Label, PageHeader, Spinner, Table, Td, Textarea, Th } from "@/components/ui/primitives";
import { Dialog } from "@/components/ui/overlay";
import { useToast } from "@/components/Toast";
import type { CaseItem } from "@/types";
import { formatDate } from "@/utils/format";

export default function CasesPage() {
  const { user } = useAuth();
  const toast = useToast();
  const cases = useApi<CaseItem[]>("/cases");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ case_number: "", title: "", description: "", police_station: "", district: "" });
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const set = (k: keyof typeof form) => (e: { target: { value: string } }) => setForm((f) => ({ ...f, [k]: e.target.value }));

  const create = async () => {
    setBusy(true);
    setError(null);
    try {
      await api.post("/cases", form);
      toast("Case workspace created");
      setOpen(false);
      setForm({ case_number: "", title: "", description: "", police_station: "", district: "" });
      cases.reload(true);
    } catch (e) { setError(errorMessage(e)); } finally { setBusy(false); }
  };

  return (
    <div>
      <PageHeader title="Case Intelligence" description="Case workspaces group documents explicitly. Documents are never merged into a case automatically."
        actions={canWrite(user) && <Button onClick={() => setOpen(true)}><FolderPlus className="h-4 w-4" /> New case</Button>} />
      <Card>
        {cases.loading ? <Spinner className="px-4" /> : cases.error ? <ErrorBox className="m-4" message={cases.error} /> : !cases.data?.length ? (
          <EmptyState title="No case workspaces" description="Create a case and associate documents with it to generate timelines, summaries and case-scoped answers." />
        ) : (
          <Table>
            <thead><tr><Th>Case</Th><Th>Title</Th><Th>Police station</Th><Th>District</Th><Th>Documents</Th><Th>Status</Th><Th>Created</Th></tr></thead>
            <tbody>
              {cases.data.map((c) => (
                <tr key={c.id} className="hover:bg-slate-50">
                  <Td><Link to={`/cases/${c.id}`} className="font-mono font-medium text-navy-700 hover:underline">{c.case_number}</Link></Td>
                  <Td>{c.title}</Td><Td>{c.police_station ?? "—"}</Td><Td>{c.district ?? "—"}</Td>
                  <Td className="tabular-nums">{c.document_count}</Td>
                  <Td><Badge tone={c.status === "open" ? "blue" : "slate"}>{c.status}</Badge></Td>
                  <Td className="text-xs">{formatDate(c.created_at)}</Td>
                </tr>
              ))}
            </tbody>
          </Table>
        )}
      </Card>
      <Dialog open={open} onOpenChange={setOpen} title="New case workspace"
        footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={create} loading={busy} disabled={!form.case_number || !form.title}>Create</Button></>}>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Case number</Label><Input placeholder="RJ-2026-001" value={form.case_number} onChange={set("case_number")} /></div>
          <div><Label>Title</Label><Input value={form.title} onChange={set("title")} /></div>
          <div><Label>Police station</Label><Input value={form.police_station} onChange={set("police_station")} /></div>
          <div><Label>District</Label><Input value={form.district} onChange={set("district")} /></div>
          <div className="col-span-2"><Label>Description</Label><Textarea rows={3} value={form.description} onChange={set("description")} /></div>
        </div>
        {error && <ErrorBox className="mt-3" message={error} />}
      </Dialog>
    </div>
  );
}
