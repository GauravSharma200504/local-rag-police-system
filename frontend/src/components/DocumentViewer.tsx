import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Download, Highlighter } from "lucide-react";
import { Dialog } from "@/components/ui/overlay";
import { Button } from "@/components/ui/button";
import { ErrorBox, Notice, Spinner } from "@/components/ui/primitives";
import { api, authedUrl, errorMessage } from "@/services/api";
import type { DocumentItem } from "@/types";

export interface ViewerTarget {
  documentId: string;
  page: number;
  passage?: string;
  title?: string;
}

function highlightText(text: string, passage?: string) {
  if (!passage) return [text];
  const probe = passage.replace(/…$/, "").trim().slice(0, 120);
  const norm = (s: string) => s.replace(/\s+/g, " ");
  const flat = norm(text);
  const idx = flat.toLowerCase().indexOf(norm(probe).toLowerCase().slice(0, 60));
  if (idx < 0) return [flat];
  const end = Math.min(flat.length, idx + norm(passage).length);
  return [flat.slice(0, idx), <mark key="m" className="bg-amber-200">{flat.slice(idx, end)}</mark>, flat.slice(end)];
}

/** Opens the ORIGINAL document at the cited page. PDFs/images are rendered server-side with the passage highlighted. */
export function DocumentViewer({ target, onClose }: { target: ViewerTarget | null; onClose: () => void }) {
  const [doc, setDoc] = useState<DocumentItem | null>(null);
  const [page, setPage] = useState(1);
  const [error, setError] = useState<string | null>(null);
  const [imgLoading, setImgLoading] = useState(true);
  const [hits, setHits] = useState<number | null>(null);
  const [text, setText] = useState<string | null>(null);

  useEffect(() => {
    if (!target) return;
    setDoc(null);
    setError(null);
    setPage(target.page || 1);
    api.get<DocumentItem>(`/documents/${target.documentId}`).then((r) => setDoc(r.data)).catch((e) => setError(errorMessage(e)));
  }, [target]);

  const isVisual = doc && [".pdf", ".png", ".jpg", ".jpeg"].includes(doc.file_ext);
  const passage = target && page === target.page ? target.passage : undefined;
  const imgUrl = doc && isVisual ? authedUrl(`/documents/${doc.id}/pages/${page}/image`, { passage }) : null;

  useEffect(() => {
    if (!doc || isVisual) return;
    setText(null);
    api.get(`/documents/${doc.id}/pages/${page}/text`).then((r) => setText(r.data.text)).catch((e) => setError(errorMessage(e)));
  }, [doc, page, isVisual]);

  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  useEffect(() => {
    if (!imgUrl) return;
    let revoked: string | null = null;
    const ctrl = new AbortController();
    setImgLoading(true);
    setHits(null);
    fetch(imgUrl, { signal: ctrl.signal })
      .then(async (r) => {
        if (!r.ok) throw new Error(`Page could not be rendered (${r.status})`);
        setHits(Number(r.headers.get("X-Highlight-Count") ?? 0));
        revoked = URL.createObjectURL(await r.blob());
        setBlobUrl(revoked);
      })
      .catch((e) => e.name !== "AbortError" && setError(String(e.message ?? e)))
      .finally(() => setImgLoading(false));
    return () => {
      ctrl.abort();
      if (revoked) URL.revokeObjectURL(revoked);
    };
  }, [imgUrl]);

  return (
    <Dialog open={!!target} onOpenChange={(o) => !o && onClose()} wide title={doc?.title ?? target?.title ?? "Document"}
      description={doc ? `${doc.doc_type} · ${doc.original_filename} · page ${page} of ${doc.page_count}${doc.ocr_pages.includes(page) ? " · OCR page" : ""}` : undefined}
      footer={doc && (
        <>
          <a href={authedUrl(`/documents/${doc.id}/file`)} target="_blank" rel="noreferrer">
            <Button variant="secondary" size="sm"><Download className="h-4 w-4" /> Open original file</Button>
          </a>
          <Button variant="secondary" size="sm" disabled={page <= 1} onClick={() => setPage((p) => p - 1)}><ChevronLeft className="h-4 w-4" /> Prev</Button>
          <Button variant="secondary" size="sm" disabled={page >= doc.page_count} onClick={() => setPage((p) => p + 1)}>Next <ChevronRight className="h-4 w-4" /></Button>
        </>
      )}>
      {error && <ErrorBox message={error} />}
      {!doc && !error && <Spinner />}
      {doc && passage && (
        <Notice tone={hits === 0 ? "amber" : "blue"} className="mb-3 flex items-start gap-2">
          <Highlighter className="mt-0.5 h-3.5 w-3.5 shrink-0" />
          <span>
            {hits === 0 ? "Cited passage could not be located visually on this page (it may span pages or contain OCR noise). Cited text: " : "Cited passage: "}
            <em>“{passage}”</em>
          </span>
        </Notice>
      )}
      {doc && isVisual && (
        <div className="relative flex min-h-[300px] justify-center rounded border border-slate-200 bg-slate-100 p-2">
          {imgLoading && <Spinner className="absolute top-4" label="Rendering page…" />}
          {blobUrl && !imgLoading && <img src={blobUrl} alt={`Page ${page} of ${doc.title}`} className="max-w-full shadow" />}
        </div>
      )}
      {doc && !isVisual && (
        text === null ? <Spinner /> : (
          <div className="whitespace-pre-wrap rounded border border-slate-200 bg-white p-4 text-sm leading-relaxed text-slate-800">
            {doc.file_ext === ".docx" && <Notice tone="slate" className="mb-3">DOCX files have no fixed pages; page numbers follow page breaks in the file.</Notice>}
            {highlightText(text, passage)}
          </div>
        )
      )}
    </Dialog>
  );
}
