import { useEffect, useState } from "react";
import { PlayCircle, Save, UserPlus } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { Badge, Card, CardBody, CardHeader, ErrorBox, Input, Label, Notice, PageHeader, Select, Spinner, Table, Td, Th } from "@/components/ui/primitives";
import { Dialog, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/overlay";
import { useToast } from "@/components/Toast";
import type { User } from "@/types";
import { formatDate } from "@/utils/format";

type Params = Record<string, string | number>;
interface Models {
  llm: { base_url: string; model: string; reachable: boolean; model_available: boolean; installed_models?: string[]; hint?: string | null; error?: string };
  embedding: { provider: string; model: string; dim: number; device: string; loaded: boolean; is_test_embedder: boolean };
  reranker: { provider: string; model: string | null; loaded: boolean };
  ocr: { version: string | null; languages: string[]; configured_languages: string; available: boolean };
  chunking: { chunk_size_tokens: number; chunk_overlap_tokens: number };
}

const PARAM_FIELDS: { key: string; label: string; help: string; step?: string }[] = [
  { key: "retrieval_top_k", label: "Retrieval top-K", help: "Candidates from dense and from sparse retrieval" },
  { key: "rerank_top_k", label: "Final context top-K", help: "Chunks passed to the LLM after (re)ranking" },
  { key: "dense_similarity_threshold", label: "Dense similarity threshold", help: "Cosine similarity cut-off (0-1)", step: "0.01" },
  { key: "rerank_score_threshold", label: "Rerank score threshold", help: "Cross-encoder logit cut-off; below → discarded", step: "0.1" },
  { key: "rrf_k", label: "RRF k", help: "Reciprocal Rank Fusion constant (default 60)" },
  { key: "citation_support_threshold", label: "Citation support threshold", help: "Min. lexical support for a citation to be kept (0-1)", step: "0.05" },
  { key: "llm_temperature", label: "LLM temperature", help: "Low values keep answers factual", step: "0.05" },
];

export default function SettingsPage() {
  const { user } = useAuth();
  const isAdmin = user?.role === "admin";
  return (
    <div>
      <PageHeader title="Settings" description="Local model configuration, retrieval parameters, users and audit trail." />
      <Tabs defaultValue="models">
        <TabsList>
          <TabsTrigger value="models">Models & retrieval</TabsTrigger>
          {isAdmin && <TabsTrigger value="users">Users</TabsTrigger>}
          {isAdmin && <TabsTrigger value="audit">Audit log</TabsTrigger>}
        </TabsList>
        <TabsContent value="models"><ModelsTab isAdmin={isAdmin} /></TabsContent>
        {isAdmin && <TabsContent value="users"><UsersTab /></TabsContent>}
        {isAdmin && <TabsContent value="audit"><AuditTab /></TabsContent>}
      </Tabs>
    </div>
  );
}

function ModelsTab({ isAdmin }: { isAdmin: boolean }) {
  const toast = useToast();
  const models = useApi<Models>("/settings/models");
  const params = useApi<Params>("/settings/retrieval");
  const [form, setForm] = useState<Params>({});
  const [tests, setTests] = useState<Record<string, { ok: boolean; [k: string]: unknown } | "running">>({});
  const [saving, setSaving] = useState(false);
  useEffect(() => { if (params.data) setForm(params.data); }, [params.data]);

  const test = async (c: string) => {
    setTests((t) => ({ ...t, [c]: "running" }));
    try { const r = await api.post(`/settings/models/test/${c}`); setTests((t) => ({ ...t, [c]: r.data })); models.reload(true); }
    catch (e) { setTests((t) => ({ ...t, [c]: { ok: false, error: errorMessage(e) } })); }
  };
  const save = async () => {
    setSaving(true);
    try {
      const body = Object.fromEntries(Object.entries(form).map(([k, v]) => [k, k === "ollama_model" ? v : Number(v)]));
      params.setData((await api.put("/settings/retrieval", body)).data);
      toast("Parameters saved");
      models.reload(true);
    } catch (e) { toast(errorMessage(e), "error"); } finally { setSaving(false); }
  };
  const TestResult = ({ c }: { c: string }) => {
    const t = tests[c];
    if (!t) return null;
    if (t === "running") return <Spinner label="Testing (first load can take a minute)…" className="py-1" />;
    return t.ok ? <Notice tone="blue" className="mt-2">OK · {JSON.stringify(Object.fromEntries(Object.entries(t).filter(([k]) => k !== "ok")))}</Notice> : <ErrorBox className="mt-2" message={String(t.error)} />;
  };
  const m = models.data;

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      <Card>
        <CardHeader title="Local models" description="No cloud fallback. Models are never downloaded automatically by the app." />
        <CardBody className="space-y-5 text-sm">
          {!m ? <Spinner /> : (
            <>
              <div>
                <div className="flex items-center justify-between"><b>LLM · Ollama</b><Badge tone={m.llm.reachable && m.llm.model_available ? "green" : "red"}>{m.llm.reachable ? (m.llm.model_available ? "ready" : "model missing") : "unreachable"}</Badge></div>
                <p className="text-xs text-slate-500">{m.llm.base_url} · model <code>{m.llm.model}</code></p>
                {m.llm.hint && <Notice className="mt-1">{m.llm.hint}{!m.llm.reachable && " Smaller models for low-RAM machines: llama3.2:3b, qwen2.5:3b, phi3:mini, gemma2:2b."}</Notice>}
                {m.llm.installed_models && m.llm.installed_models.length > 0 && <p className="mt-1 text-xs text-slate-500">Installed: {m.llm.installed_models.join(", ")}</p>}
                {isAdmin && <Button size="sm" variant="secondary" className="mt-2" onClick={() => test("llm")}><PlayCircle className="h-4 w-4" /> Test inference</Button>}
                <TestResult c="llm" />
              </div>
              <div>
                <div className="flex items-center justify-between"><b>Embeddings</b><Badge tone={m.embedding.is_test_embedder ? "amber" : "green"}>{m.embedding.provider}</Badge></div>
                <p className="text-xs text-slate-500"><code>{m.embedding.model}</code> · {m.embedding.dim} dimensions · {m.embedding.device} · {m.embedding.loaded ? "loaded" : "not loaded yet"}</p>
                {m.embedding.is_test_embedder && <Notice className="mt-1">The hashing test embedder is active. Set EMBEDDING_PROVIDER=sentence_transformers for semantic retrieval.</Notice>}
                <p className="mt-1 text-[11px] text-slate-500">Changing the embedding model requires re-indexing: <code>python -m app.cli reindex --recreate</code></p>
                {isAdmin && <Button size="sm" variant="secondary" className="mt-2" onClick={() => test("embedding")}><PlayCircle className="h-4 w-4" /> Load & test</Button>}
                <TestResult c="embedding" />
              </div>
              <div>
                <div className="flex items-center justify-between"><b>Cross-encoder reranker</b><Badge tone={m.reranker.provider === "none" ? "amber" : "green"}>{m.reranker.provider}</Badge></div>
                <p className="text-xs text-slate-500"><code>{m.reranker.model ?? "disabled"}</code> · {m.reranker.loaded ? "loaded" : "not loaded yet"}</p>
                {isAdmin && <Button size="sm" variant="secondary" className="mt-2" onClick={() => test("reranker")}><PlayCircle className="h-4 w-4" /> Load & test</Button>}
                <TestResult c="reranker" />
              </div>
              <div>
                <div className="flex items-center justify-between"><b>OCR · Tesseract</b><Badge tone={m.ocr.available ? "green" : "red"}>{m.ocr.version ?? "not found"}</Badge></div>
                <p className="text-xs text-slate-500">configured {m.ocr.configured_languages} · installed: {m.ocr.languages.filter((l) => ["eng", "hin"].includes(l)).join(", ") || "none"}</p>
              </div>
              <p className="text-xs text-slate-500">Chunking: {m.chunking.chunk_size_tokens} tokens, {m.chunking.chunk_overlap_tokens} overlap (CHUNK_SIZE_TOKENS / CHUNK_OVERLAP_TOKENS in .env; reprocess documents after changing).</p>
            </>
          )}
        </CardBody>
      </Card>
      <Card>
        <CardHeader title="Retrieval & generation parameters" description="Applied immediately to new queries." actions={isAdmin && <Button size="sm" onClick={save} loading={saving}><Save className="h-4 w-4" /> Save</Button>} />
        <CardBody className="grid grid-cols-2 gap-4">
          {params.loading ? <Spinner /> : (
            <>
              <div className="col-span-2"><Label>Ollama chat model</Label>
                {m?.llm.installed_models?.length ? (
                  <Select value={String(form.ollama_model ?? "")} disabled={!isAdmin} onChange={(e) => setForm((f) => ({ ...f, ollama_model: e.target.value }))}>
                    {!m.llm.installed_models.includes(String(form.ollama_model)) && <option>{String(form.ollama_model)}</option>}
                    {m.llm.installed_models.map((x) => <option key={x}>{x}</option>)}
                  </Select>
                ) : <Input value={String(form.ollama_model ?? "")} disabled={!isAdmin} onChange={(e) => setForm((f) => ({ ...f, ollama_model: e.target.value }))} />}
              </div>
              {PARAM_FIELDS.map((p) => (
                <div key={p.key}><Label>{p.label}</Label>
                  <Input type="number" step={p.step ?? "1"} value={form[p.key] ?? ""} disabled={!isAdmin} onChange={(e) => setForm((f) => ({ ...f, [p.key]: e.target.value }))} />
                  <p className="mt-0.5 text-[11px] text-slate-500">{p.help}</p></div>
              ))}
            </>
          )}
        </CardBody>
      </Card>
    </div>
  );
}

function UsersTab() {
  const toast = useToast();
  const users = useApi<User[]>("/users");
  const [open, setOpen] = useState(false);
  const [form, setForm] = useState({ username: "", full_name: "", password: "", role: "investigator" });
  const [error, setError] = useState<string | null>(null);
  const create = async () => {
    try { await api.post("/users", form); setOpen(false); setForm({ username: "", full_name: "", password: "", role: "investigator" }); users.reload(true); toast("User created"); }
    catch (e) { setError(errorMessage(e)); }
  };
  const patch = async (u: User, body: object) => { try { await api.patch(`/users/${u.id}`, body); users.reload(true); } catch (e) { toast(errorMessage(e), "error"); } };
  const resetPw = async (u: User) => {
    const pw = window.prompt(`New password for ${u.username} (min 8 characters)`);
    if (pw) { await patch(u, { password: pw }); toast("Password changed"); }
  };
  return (
    <Card>
      <CardHeader title="Users" description="Roles: admin (everything), investigator (upload/edit within own cases), analyst (read & query assigned cases)." actions={<Button size="sm" onClick={() => setOpen(true)}><UserPlus className="h-4 w-4" /> New user</Button>} />
      {users.loading ? <Spinner className="px-4" /> : (
        <Table><thead><tr><Th>Username</Th><Th>Name</Th><Th>Role</Th><Th>Status</Th><Th>Created</Th><Th /></tr></thead>
          <tbody>{users.data?.map((u) => (
            <tr key={u.id}>
              <Td className="font-mono text-xs">{u.username}</Td><Td>{u.full_name}</Td>
              <Td><Select className="h-8 w-36 text-xs" value={u.role} onChange={(e) => patch(u, { role: e.target.value })} aria-label={`Role of ${u.username}`}><option>admin</option><option>investigator</option><option>analyst</option></Select></Td>
              <Td><Badge tone={u.is_active ? "green" : "slate"}>{u.is_active ? "active" : "disabled"}</Badge></Td>
              <Td className="text-xs">{formatDate(u.created_at)}</Td>
              <Td className="whitespace-nowrap text-right">
                <Button size="sm" variant="ghost" onClick={() => resetPw(u)}>Reset password</Button>
                <Button size="sm" variant="ghost" onClick={() => patch(u, { is_active: !u.is_active })}>{u.is_active ? "Disable" : "Enable"}</Button>
              </Td>
            </tr>
          ))}</tbody></Table>
      )}
      <Dialog open={open} onOpenChange={setOpen} title="New user" footer={<><Button variant="secondary" onClick={() => setOpen(false)}>Cancel</Button><Button onClick={create}>Create</Button></>}>
        <div className="grid grid-cols-2 gap-3">
          <div><Label>Username</Label><Input value={form.username} onChange={(e) => setForm((f) => ({ ...f, username: e.target.value }))} /></div>
          <div><Label>Full name</Label><Input value={form.full_name} onChange={(e) => setForm((f) => ({ ...f, full_name: e.target.value }))} /></div>
          <div><Label>Password (min 8)</Label><Input type="password" value={form.password} onChange={(e) => setForm((f) => ({ ...f, password: e.target.value }))} /></div>
          <div><Label>Role</Label><Select value={form.role} onChange={(e) => setForm((f) => ({ ...f, role: e.target.value }))}><option>admin</option><option>investigator</option><option>analyst</option></Select></div>
        </div>
        {error && <ErrorBox className="mt-3" message={error} />}
      </Dialog>
    </Card>
  );
}

function AuditTab() {
  const logs = useApi<{ id: string; username: string | null; action: string; target_type: string | null; target_id: string | null; detail: object; created_at: string }[]>("/audit-logs");
  return (
    <Card>
      <CardHeader title="Audit log" description="Document access, uploads, queries and administrative actions. Document contents are never logged." actions={<Button size="sm" variant="secondary" onClick={() => logs.reload()}>Refresh</Button>} />
      {logs.loading ? <Spinner className="px-4" /> : (
        <Table><thead><tr><Th>Time</Th><Th>User</Th><Th>Action</Th><Th>Target</Th><Th>Detail</Th></tr></thead>
          <tbody>{logs.data?.map((l) => (
            <tr key={l.id}><Td className="whitespace-nowrap text-xs">{formatDate(l.created_at, true)}</Td><Td className="text-xs">{l.username ?? "—"}</Td>
              <Td><Badge>{l.action}</Badge></Td><Td className="font-mono text-[11px]">{l.target_type ? `${l.target_type}:${l.target_id?.slice(0, 8)}` : "—"}</Td>
              <Td className="max-w-xs truncate font-mono text-[11px] text-slate-500">{JSON.stringify(l.detail)}</Td></tr>
          ))}</tbody></Table>
      )}
    </Card>
  );
}
