import { useState } from "react";
import { useDropzone } from "react-dropzone";
import { FileUp, X } from "lucide-react";
import { Dialog } from "@/components/ui/overlay";
import { Button } from "@/components/ui/button";
import { ErrorBox, Input, Label, Notice, Select } from "@/components/ui/primitives";
import { api, errorMessage } from "@/services/api";
import { useApi } from "@/hooks/useApi";
import { useAuth } from "@/contexts/AuthContext";
import { useToast } from "@/components/Toast";
import { DOC_TYPES, type CaseItem } from "@/types";
import { formatBytes } from "@/utils/format";

const ACCEPT = { "application/pdf": [".pdf"], "application/vnd.openxmlformats-officedocument.wordprocessingml.document": [".docx"],
  "text/plain": [".txt"], "image/png": [".png"], "image/jpeg": [".jpg", ".jpeg"] };

export function UploadDialog({ open, onOpenChange, onUploaded, defaultCaseId, legal }: {
  open: boolean; onOpenChange: (o: boolean) => void; onUploaded: () => void; defaultCaseId?: string; legal?: boolean;
}) {
  const { user } = useAuth();
  const toast = useToast();
  const { data: cases } = useApi<CaseItem[]>(open ? "/cases" : null);
  const [files, setFiles] = useState<File[]>([]);
  const [meta, setMeta] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const docType = legal ? "Legal Document" : meta.doc_type ?? "FIR";
  const { getRootProps, getInputProps, isDragActive } = useDropzone({
    accept: ACCEPT, multiple: true, onDrop: (accepted) => setFiles((f) => [...f, ...accepted]),
  });
  const set = (k: string) => (e: { target: { value: string } }) => setMeta((m) => ({ ...m, [k]: e.target.value }));

  const submit = async () => {
    setBusy(true);
    setError(null);
    const form = new FormData();
    files.forEach((f) => form.append("files", f));
    form.append("doc_type", docType);
    const caseId = meta.case_id ?? defaultCaseId;
    if (caseId && !legal) form.append("case_id", caseId);
    ["title", "incident_date", "police_station", "district", "language", "classification", "act_name", "short_name", "version",
      "effective_date", "source_url", "publication", "verified_by", "verification_date", "replaced_by"].forEach((k) => meta[k] && form.append(k, meta[k]));
    if (legal) {
      form.append("is_official_text", meta.is_official_text === "true" ? "true" : "false");
      form.append("is_historical", meta.is_historical === "true" ? "true" : "false");
    }
    try {
      const r = await api.post("/documents/upload", form);
      const results = r.data.results as { filename: string; duplicate?: boolean; error?: string }[];
      const errors = results.filter((x) => x.error);
      const dups = results.filter((x) => x.duplicate && !x.error);
      const ok = results.length - errors.length - dups.length;
      if (ok) toast(`${ok} document(s) uploaded - processing started`);
      if (dups.length) toast(`${dups.length} duplicate file(s) skipped (identical SHA-256 already stored)`, "info");
      if (errors.length) setError(errors.map((e) => `${e.filename}: ${e.error}`).join(" · "));
      else {
        setFiles([]);
        setMeta({});
        onOpenChange(false);
      }
      onUploaded();
    } catch (e) {
      setError(errorMessage(e));
    } finally {
      setBusy(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange} title={legal ? "Add legal reference source" : "Upload documents"}
      description={legal ? "Upload the official text (e.g. Gazette PDF) and record its provenance." : "PDF, DOCX, TXT or scanned images. Duplicates are detected by SHA-256."}
      footer={<><Button variant="secondary" onClick={() => onOpenChange(false)}>Cancel</Button>
        <Button onClick={submit} loading={busy} disabled={!files.length}>Upload {files.length ? `(${files.length})` : ""}</Button></>}>
      <div {...getRootProps()} className={`cursor-pointer rounded-lg border-2 border-dashed p-6 text-center ${isDragActive ? "border-navy-600 bg-navy-50" : "border-slate-300 hover:border-slate-400"}`}>
        <input {...getInputProps()} aria-label="Choose files" />
        <FileUp className="mx-auto mb-2 h-6 w-6 text-slate-400" />
        <p className="text-sm text-slate-700">Drag & drop files here, or click to browse</p>
        <p className="text-xs text-slate-500">.pdf .docx .txt .png .jpg</p>
      </div>
      {files.length > 0 && (
        <ul className="mt-3 space-y-1">
          {files.map((f, i) => (
            <li key={i} className="flex items-center justify-between rounded bg-slate-50 px-2 py-1 text-xs">
              <span className="truncate">{f.name} <span className="text-slate-400">({formatBytes(f.size)})</span></span>
              <button onClick={() => setFiles((x) => x.filter((_, j) => j !== i))} aria-label={`Remove ${f.name}`}><X className="h-3.5 w-3.5 text-slate-400" /></button>
            </li>
          ))}
        </ul>
      )}
      <div className="mt-4 grid grid-cols-2 gap-3">
        {!legal && (
          <>
            <div><Label>Document type</Label>
              <Select value={docType} onChange={set("doc_type")}>{DOC_TYPES.filter((t) => t !== "Legal Document" || user?.role === "admin").map((t) => <option key={t}>{t}</option>)}</Select></div>
            <div><Label>Case</Label>
              <Select value={meta.case_id ?? defaultCaseId ?? ""} onChange={set("case_id")}>
                <option value="">— none —</option>
                {cases?.map((c) => <option key={c.id} value={c.id}>{c.case_number} · {c.title}</option>)}
              </Select></div>
            <div><Label>Incident date</Label><Input type="date" value={meta.incident_date ?? ""} onChange={set("incident_date")} /></div>
            <div><Label>Language</Label>
              <Select value={meta.language ?? ""} onChange={set("language")}><option value="">Auto-detect</option><option value="en">English</option><option value="hi">Hindi</option><option value="mixed">Mixed</option></Select></div>
            <div><Label>Police station</Label><Input value={meta.police_station ?? ""} onChange={set("police_station")} /></div>
            <div><Label>District</Label><Input value={meta.district ?? ""} onChange={set("district")} /></div>
          </>
        )}
        {legal && (
          <>
            <div className="col-span-2"><Label>Act name</Label><Input placeholder="Bharatiya Nyaya Sanhita, 2023" value={meta.act_name ?? ""} onChange={set("act_name")} /></div>
            <div><Label>Short name</Label><Input placeholder="BNS / BNSS / BSA / IPC / CRPC / IEA / COI" value={meta.short_name ?? ""} onChange={set("short_name")} /></div>
            <div><Label>Version</Label><Input placeholder="As published in Gazette, 25-12-2023" value={meta.version ?? ""} onChange={set("version")} /></div>
            <div><Label>Effective date</Label><Input type="date" value={meta.effective_date ?? ""} onChange={set("effective_date")} /></div>
            <div><Label>Verification date</Label><Input type="date" value={meta.verification_date ?? ""} onChange={set("verification_date")} /></div>
            <div className="col-span-2"><Label>Source URL / publication</Label><Input placeholder="https://www.indiacode.nic.in/..." value={meta.source_url ?? ""} onChange={set("source_url")} /></div>
            <div><Label>Verified by</Label><Input value={meta.verified_by ?? ""} onChange={set("verified_by")} /></div>
            <div><Label>Replaced by (if historical)</Label><Input placeholder="e.g. BNS, 2023" value={meta.replaced_by ?? ""} onChange={set("replaced_by")} /></div>
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={meta.is_official_text === "true"} onChange={(e) => setMeta((m) => ({ ...m, is_official_text: String(e.target.checked) }))} /> Official statutory text</label>
            <label className="flex items-center gap-2 text-xs"><input type="checkbox" checked={meta.is_historical === "true"} onChange={(e) => setMeta((m) => ({ ...m, is_historical: String(e.target.checked) }))} /> Historical / repealed law</label>
            <Notice className="col-span-2">Mark “official statutory text” only for an official publication you have verified. Search results will label all other sources as non-official.</Notice>
          </>
        )}
      </div>
      {error && <ErrorBox message={error} className="mt-3" />}
    </Dialog>
  );
}
