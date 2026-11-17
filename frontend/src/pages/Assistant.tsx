import { useEffect, useRef, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { AlertTriangle, Bot, Copy, MessageSquarePlus, Send, Square, Trash2, User as UserIcon } from "lucide-react";
import { api, errorMessage } from "@/services/api";
import { streamAnswer } from "@/services/stream";
import { useApi } from "@/hooks/useApi";
import { Button } from "@/components/ui/button";
import { Badge, Card, EmptyState, ErrorBox, Notice, Select, Spinner, Textarea } from "@/components/ui/primitives";
import { CitationText } from "@/components/CitationText";
import { EvidencePanel } from "@/components/EvidencePanel";
import { DocumentViewer, type ViewerTarget } from "@/components/DocumentViewer";
import { useToast } from "@/components/Toast";
import type { CaseItem, Citation, Conversation, Message } from "@/types";
import { cn, formatDate } from "@/utils/format";

const EXAMPLES = [
  "Summarize FIR RJ-2026-001.",
  "What evidence is mentioned in the investigation report?",
  "Find differences in incident times across documents.",
  "Compare the FIR with the witness statement of Mohan Lal Saini.",
  "Extract all important dates and locations.",
  "Who has been arrested in this case?",
  "What is the name of the security guard at the shop?",
];

export default function AssistantPage({ caseId: fixedCaseId }: { caseId?: string } = {}) {
  const { conversationId } = useParams();
  const nav = useNavigate();
  const toast = useToast();
  const embedded = !!fixedCaseId;
  const [activeId, setActiveId] = useState<string | undefined>(embedded ? undefined : conversationId);
  const convs = useApi<Conversation[]>("/chat/conversations");
  const { data: cases } = useApi<CaseItem[]>("/cases");
  const [conv, setConv] = useState<Conversation | null>(null);
  const [question, setQuestion] = useState("");
  const [config, setConfig] = useState("proposed");
  const [newCaseId, setNewCaseId] = useState(fixedCaseId ?? "");
  const [streaming, setStreaming] = useState<{ text: string; sources: number } | null>(null);
  const [selected, setSelected] = useState<Message | null>(null);
  const [viewer, setViewer] = useState<ViewerTarget | null>(null);
  const [error, setError] = useState<string | null>(null);
  const abortRef = useRef<AbortController | null>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const justCreated = useRef<string | null>(null);

  useEffect(() => { if (!embedded) setActiveId(conversationId); }, [conversationId, embedded]);
  useEffect(() => {
    if (!activeId) { setConv(null); setSelected(null); return; }
    if (justCreated.current === activeId) return; // conversation was just created locally; keep streaming state
    api.get<Conversation>(`/chat/conversations/${activeId}`).then((r) => {
      setConv(r.data);
      const last = [...(r.data.messages ?? [])].reverse().find((m) => m.role === "assistant");
      setSelected(last ?? null);
    }).catch((e) => setError(errorMessage(e)));
  }, [activeId]);
  useEffect(() => { bottomRef.current?.scrollIntoView({ behavior: "smooth" }); }, [conv?.messages?.length, streaming?.text]);

  const open = (id: string) => (embedded ? setActiveId(id) : nav(`/assistant/${id}`));
  const visibleConvs = (convs.data ?? []).filter((c) => !embedded || c.case_id === fixedCaseId);

  const ensureConversation = async (): Promise<Conversation> => {
    if (conv) return conv;
    const r = await api.post<Conversation>("/chat/conversations", { case_id: newCaseId || null });
    setConv(r.data);
    justCreated.current = r.data.id;
    if (embedded) setActiveId(r.data.id);
    else nav(`/assistant/${r.data.id}`, { replace: true });
    return r.data;
  };

  const ask = async (q?: string) => {
    const text = (q ?? question).trim();
    if (!text || streaming) return;
    setError(null);
    setQuestion("");
    try {
      const c = await ensureConversation();
      const userMsg: Message = { id: `tmp-${Date.now()}`, role: "user", content: text, abstained: false, created_at: new Date().toISOString(), citations: [], retrieval: {} };
      setConv((cv) => ({ ...(cv ?? c), messages: [...(cv?.messages ?? c.messages ?? []), userMsg] }));
      setStreaming({ text: "", sources: 0 });
      abortRef.current = new AbortController();
      await streamAnswer(c.id, { question: text, config }, {
        onSources: (p) => setStreaming((s) => ({ text: s?.text ?? "", sources: p.sources.length })),
        onToken: (t) => setStreaming((s) => ({ text: (s?.text ?? "") + t, sources: s?.sources ?? 0 })),
        onFinal: (m) => {
          setConv((cv) => (cv ? { ...cv, messages: [...(cv.messages ?? []), m] } : cv));
          setSelected(m);
          setStreaming(null);
          convs.reload(true);
        },
        onError: (d) => { setError(d); setStreaming(null); },
      }, abortRef.current.signal);
    } catch (e) {
      if ((e as Error).name !== "AbortError") setError(errorMessage(e));
      setStreaming(null);
    }
  };

  const remove = async (id: string) => {
    await api.delete(`/chat/conversations/${id}`);
    convs.reload(true);
    if (activeId === id) (embedded ? setActiveId(undefined) : nav("/assistant"));
  };

  const openCitation = (c: Citation) => c.document_id && setViewer({ documentId: c.document_id, page: c.page, passage: c.passage, title: c.document_title });
  const caseLabel = (id: string | null) => cases?.find((c) => c.id === id)?.case_number;

  return (
    <div className={cn("grid gap-4", embedded ? "h-[70vh] grid-cols-[220px_1fr_340px]" : "h-[calc(100vh-7.5rem)] grid-cols-[240px_1fr_360px]")}>
      <Card className="flex min-h-0 flex-col">
        <div className="border-b border-slate-100 p-3">
          <Button className="w-full" size="sm" onClick={() => (embedded ? setActiveId(undefined) : nav("/assistant"))}><MessageSquarePlus className="h-4 w-4" /> New conversation</Button>
        </div>
        <div className="min-h-0 flex-1 overflow-y-auto p-2">
          {convs.loading && <Spinner />}
          {!convs.loading && visibleConvs.length === 0 && <p className="p-2 text-xs text-slate-500">No conversations yet.</p>}
          {visibleConvs.map((c) => (
            <div key={c.id} className={cn("group flex items-center rounded-md", c.id === activeId ? "bg-navy-50" : "hover:bg-slate-50")}>
              <button onClick={() => open(c.id)} className="min-w-0 flex-1 px-2 py-2 text-left">
                <div className="truncate text-xs font-medium text-slate-800">{c.title}</div>
                <div className="text-[10px] text-slate-400">{caseLabel(c.case_id) ?? "All authorized documents"} · {formatDate(c.updated_at)}</div>
              </button>
              <button onClick={() => remove(c.id)} className="mr-1 hidden rounded p-1 text-slate-400 hover:text-red-600 group-hover:block" aria-label="Delete conversation"><Trash2 className="h-3.5 w-3.5" /></button>
            </div>
          ))}
        </div>
      </Card>

      <Card className="flex min-h-0 flex-col">
        <div className="flex items-center justify-between gap-3 border-b border-slate-100 px-4 py-2.5">
          <div className="min-w-0 text-sm">
            <span className="font-medium text-slate-900">{conv?.title ?? "New conversation"}</span>
            <span className="ml-2 text-xs text-slate-500">Scope: {conv ? (caseLabel(conv.case_id) ?? "all authorized documents") : (caseLabel(newCaseId || null) ?? "all authorized documents")}</span>
          </div>
          <div className="flex items-center gap-2">
            {!conv && !embedded && (
              <Select value={newCaseId} onChange={(e) => setNewCaseId(e.target.value)} className="h-8 w-48 text-xs" aria-label="Case scope">
                <option value="">All authorized documents</option>
                {cases?.map((c) => <option key={c.id} value={c.id}>{c.case_number}</option>)}
              </Select>
            )}
            <Select value={config} onChange={(e) => setConfig(e.target.value)} className="h-8 w-44 text-xs" aria-label="Retrieval configuration" title="Retrieval configuration">
              <option value="proposed">Proposed (hybrid + rerank)</option>
              <option value="hybrid">Baseline 2: hybrid RRF</option>
              <option value="vector">Baseline 1: vector only</option>
            </Select>
          </div>
        </div>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4">
          {!conv?.messages?.length && !streaming && (
            <EmptyState icon={<Bot className="h-5 w-5" />} title="Ask about your authorized documents"
              description="Answers are generated by the local LLM only from retrieved evidence, with validated page-level citations. If evidence is insufficient the assistant says so."
              action={<div className="flex max-w-xl flex-wrap justify-center gap-2">{EXAMPLES.map((e) => (
                <button key={e} onClick={() => ask(e)} className="rounded-full border border-slate-200 px-3 py-1 text-xs text-slate-700 hover:border-navy-600 hover:bg-navy-50">{e}</button>
              ))}</div>} />
          )}
          {conv?.messages?.map((m) => m.role === "user" ? (
            <div key={m.id} className="flex justify-end gap-2">
              <div className="max-w-[80%] rounded-lg bg-navy-800 px-3 py-2 text-sm text-white">{m.content}</div>
              <UserIcon className="mt-1 h-5 w-5 shrink-0 text-slate-400" />
            </div>
          ) : (
            <div key={m.id} className="flex gap-2">
              <Bot className="mt-1 h-5 w-5 shrink-0 text-navy-700" />
              <div onClick={() => setSelected(m)} className={cn("max-w-[90%] cursor-pointer rounded-lg border px-3 py-2", selected?.id === m.id ? "border-navy-600 bg-white" : "border-slate-200 bg-white hover:border-slate-300")}>
                {m.abstained && <div className="mb-1 flex items-center gap-1 text-xs font-medium text-amber-700"><AlertTriangle className="h-3.5 w-3.5" /> Insufficient evidence</div>}
                <CitationText text={m.content} citations={m.citations} unsupported={m.retrieval.unsupported_sentences} onCite={openCitation} />
                {(m.retrieval.warnings?.length ?? 0) > 0 && (
                  <Notice className="mt-2">{m.retrieval.warnings!.map((w, i) => <div key={i}>{w}</div>)}</Notice>
                )}
                <div className="mt-2 flex items-center gap-2 text-[11px] text-slate-400">
                  <Badge tone="slate">AI-generated · verify before use</Badge>
                  <span>{m.citations.length} citation(s)</span>
                  <button className="ml-auto flex items-center gap-1 hover:text-slate-700" onClick={(e) => { e.stopPropagation(); navigator.clipboard?.writeText(m.content).then(() => toast("Answer copied")); }}>
                    <Copy className="h-3 w-3" /> Copy
                  </button>
                </div>
              </div>
            </div>
          ))}
          {streaming && (
            <div className="flex gap-2">
              <Bot className="mt-1 h-5 w-5 shrink-0 text-navy-700" />
              <div className="max-w-[90%] rounded-lg border border-dashed border-slate-300 bg-white px-3 py-2 text-sm text-slate-700">
                <div className="mb-1 text-[11px] text-slate-400">{streaming.sources ? `Generating from ${streaming.sources} retrieved source(s) - citations are validated when complete…` : "Retrieving evidence…"}</div>
                <div className="whitespace-pre-wrap">{streaming.text || <Spinner label="Waiting for local model…" className="py-0" />}</div>
              </div>
            </div>
          )}
          {error && <ErrorBox message={error} />}
          <div ref={bottomRef} />
        </div>
        <form className="border-t border-slate-100 p-3" onSubmit={(e) => { e.preventDefault(); ask(); }}>
          <div className="flex items-end gap-2">
            <Textarea rows={2} value={question} onChange={(e) => setQuestion(e.target.value)} placeholder="Ask a question about the case documents… (Enter to send, Shift+Enter for new line)"
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); ask(); } }} aria-label="Question" />
            {streaming
              ? <Button type="button" variant="secondary" onClick={() => abortRef.current?.abort()} aria-label="Stop"><Square className="h-4 w-4" /></Button>
              : <Button type="submit" disabled={!question.trim()} aria-label="Send"><Send className="h-4 w-4" /></Button>}
          </div>
        </form>
      </Card>

      <Card className="min-h-0 overflow-hidden"><EvidencePanel message={selected} onOpen={openCitation} /></Card>
      <DocumentViewer target={viewer} onClose={() => setViewer(null)} />
    </div>
  );
}
