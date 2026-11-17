import { Loader2 } from "lucide-react";
import { Badge, type Tone } from "@/components/ui/primitives";
import type { DocStatus } from "@/types";

const MAP: Record<DocStatus, { tone: Tone; label: string }> = {
  uploaded: { tone: "slate", label: "Uploaded" },
  extracting: { tone: "blue", label: "Extracting" },
  ocr: { tone: "violet", label: "OCR" },
  chunking: { tone: "blue", label: "Chunking" },
  embedding: { tone: "blue", label: "Embedding" },
  indexed: { tone: "green", label: "Indexed" },
  failed: { tone: "red", label: "Failed" },
};

export const isProcessing = (s: DocStatus) => !["indexed", "failed"].includes(s);

export function StatusBadge({ status }: { status: DocStatus }) {
  const m = MAP[status] ?? MAP.uploaded;
  return (
    <Badge tone={m.tone}>
      {isProcessing(status) && <Loader2 className="h-3 w-3 animate-spin" />}
      {m.label}
    </Badge>
  );
}

const TYPE_TONE: Record<string, Tone> = {
  FIR: "navy", "Witness Statement": "violet", "Investigation Report": "blue", "Evidence Report": "amber",
  "Charge Sheet": "red", "Legal Document": "green", Other: "slate",
};
export function DocTypeBadge({ type }: { type: string }) {
  return <Badge tone={TYPE_TONE[type] ?? "slate"}>{type}</Badge>;
}
