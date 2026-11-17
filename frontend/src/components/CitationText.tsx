import { Fragment } from "react";
import type { Citation } from "@/types";
import { cn } from "@/utils/format";

const MARKER = /\[(S\d+(?:\s*[,;]\s*S\d+)*)\]/g;

/**
 * Renders an answer with clickable citation chips. Only labels present in `citations` (validated against the
 * retrieved chunks) become chips; any other bracket text is shown as plain text. Unsupported sentences are flagged.
 */
export function CitationText({ text, citations, unsupported = [], onCite }: {
  text: string; citations: Citation[]; unsupported?: string[]; onCite: (c: Citation) => void;
}) {
  const byLabel = new Map(citations.map((c) => [c.label, c]));
  const unsupportedSet = unsupported.map((s) => s.trim()).filter(Boolean);
  const lines = text.split("\n");
  return (
    <div className="space-y-1.5 text-sm leading-relaxed text-slate-800">
      {lines.map((line, li) => {
        if (!line.trim()) return <div key={li} className="h-1" />;
        const isBullet = /^\s*([-*•]|\d+[.)])\s+/.test(line);
        const isHeading = /^#{1,4}\s|^\*\*[^*]+\*\*:?$/.test(line.trim());
        const clean = line.replace(/^#{1,4}\s/, "").replace(/\*\*/g, "");
        const flagged = unsupportedSet.some((s) => clean.replace(MARKER, "").includes(s.slice(0, 50)));
        const parts: (string | JSX.Element)[] = [];
        let last = 0;
        for (const m of clean.matchAll(MARKER)) {
          parts.push(clean.slice(last, m.index));
          m[1].split(/\s*[,;]\s*/).forEach((label) => {
            const c = byLabel.get(label);
            parts.push(c ? (
              <button key={`${li}-${m.index}-${label}`} type="button" onClick={() => onCite(c)}
                title={`${c.document_title}, page ${c.page}`}
                className="mx-0.5 inline-flex -translate-y-px items-center rounded bg-navy-100 px-1 text-[11px] font-semibold text-navy-800 hover:bg-navy-800 hover:text-white">
                {label}
              </button>
            ) : <Fragment key={`${li}-${m.index}-${label}`} />);
          });
          last = (m.index ?? 0) + m[0].length;
        }
        parts.push(clean.slice(last));
        return (
          <p key={li} className={cn(isBullet && "pl-3", isHeading && "pt-1 font-semibold text-slate-900",
            flagged && "rounded bg-amber-50 px-1 decoration-amber-500 decoration-dotted underline underline-offset-4")}
            title={flagged ? "This statement could not be verified against the cited sources" : undefined}>
            {parts}
          </p>
        );
      })}
    </div>
  );
}
