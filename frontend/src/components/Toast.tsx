import { createContext, useCallback, useContext, useState, type ReactNode } from "react";
import { CheckCircle2, XCircle, Info } from "lucide-react";
import { cn } from "@/utils/format";

type Kind = "success" | "error" | "info";
interface ToastItem { id: number; kind: Kind; text: string }
const Ctx = createContext<(text: string, kind?: Kind) => void>(() => {});

export function ToastProvider({ children }: { children: ReactNode }) {
  const [items, setItems] = useState<ToastItem[]>([]);
  const push = useCallback((text: string, kind: Kind = "success") => {
    const id = Date.now() + Math.random();
    setItems((x) => [...x, { id, kind, text }]);
    setTimeout(() => setItems((x) => x.filter((t) => t.id !== id)), kind === "error" ? 7000 : 3500);
  }, []);
  return (
    <Ctx.Provider value={push}>
      {children}
      <div className="pointer-events-none fixed bottom-4 right-4 z-[60] flex w-80 flex-col gap-2" aria-live="polite">
        {items.map((t) => (
          <div key={t.id} className={cn("pointer-events-auto flex items-start gap-2 rounded-md border bg-white px-3 py-2 text-sm shadow-lg",
            t.kind === "error" ? "border-red-200" : t.kind === "success" ? "border-emerald-200" : "border-slate-200")}>
            {t.kind === "error" ? <XCircle className="mt-0.5 h-4 w-4 text-red-600" /> : t.kind === "success" ? <CheckCircle2 className="mt-0.5 h-4 w-4 text-emerald-600" /> : <Info className="mt-0.5 h-4 w-4 text-slate-500" />}
            <span className="text-slate-800">{t.text}</span>
          </div>
        ))}
      </div>
    </Ctx.Provider>
  );
}

export const useToast = () => useContext(Ctx);
