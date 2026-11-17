import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { BarChart3, Bot, FileStack, FolderKanban, GitCompare, LogOut, Scale, ScrollText, Settings, ShieldCheck } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { useApi } from "@/hooks/useApi";
import { cn } from "@/utils/format";

const NAV = [
  { to: "/", label: "Dashboard", icon: BarChart3, end: true },
  { to: "/assistant", label: "AI Assistant", icon: Bot },
  { to: "/documents", label: "Documents", icon: FileStack },
  { to: "/cases", label: "Case Intelligence", icon: FolderKanban },
  { to: "/compare", label: "Document Comparison", icon: GitCompare },
  { to: "/legal", label: "Legal Research", icon: Scale },
  { to: "/reports", label: "Reports", icon: ScrollText },
  { to: "/settings", label: "Settings", icon: Settings },
];

interface ModelStatus {
  llm: { reachable: boolean; model_available: boolean; model: string };
  embedding: { model: string; is_test_embedder: boolean };
  ocr: { available: boolean };
}

function Dot({ ok, warn }: { ok: boolean; warn?: boolean }) {
  return <span className={cn("inline-block h-2 w-2 rounded-full", ok ? (warn ? "bg-amber-400" : "bg-emerald-500") : "bg-red-500")} />;
}

export function AppLayout() {
  const { user, logout } = useAuth();
  const nav = useNavigate();
  const { data: status } = useApi<ModelStatus>("/settings/models", undefined, 60_000);
  return (
    <div className="flex min-h-screen">
      <aside className="fixed inset-y-0 left-0 z-30 flex w-60 flex-col bg-navy-900 text-slate-300">
        <div className="flex items-center gap-2.5 border-b border-white/10 px-5 py-4">
          <div className="rounded-md bg-amber-500/15 p-1.5"><ShieldCheck className="h-5 w-5 text-amber-400" /></div>
          <div className="leading-tight">
            <div className="text-sm font-semibold text-white">Bharat Police</div>
            <div className="text-[11px] tracking-wide text-slate-400">INTELLIGENCE</div>
          </div>
        </div>
        <nav className="flex-1 space-y-0.5 px-3 py-4">
          {NAV.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end}
              className={({ isActive }) => cn("flex items-center gap-3 rounded-md px-3 py-2 text-sm",
                isActive ? "bg-white/10 font-medium text-white" : "hover:bg-white/5 hover:text-white")}>
              <Icon className="h-4 w-4" /> {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-white/10 px-5 py-3 text-[10px] leading-relaxed text-slate-500">
          Decision-support tool. AI outputs are drafts that require human verification. Runs fully on local models.
        </div>
      </aside>
      <div className="ml-60 flex min-h-screen flex-1 flex-col">
        <header className="sticky top-0 z-20 flex h-14 items-center justify-between border-b border-slate-200 bg-white/95 px-6 backdrop-blur">
          <div className="flex items-center gap-4 text-xs text-slate-600">
            {status ? (
              <>
                <span className="flex items-center gap-1.5" title={status.llm.model}><Dot ok={status.llm.reachable && status.llm.model_available} /> LLM {status.llm.model}</span>
                <span className="flex items-center gap-1.5" title={status.embedding.model}><Dot ok warn={status.embedding.is_test_embedder} /> Embeddings{status.embedding.is_test_embedder ? " (test)" : ""}</span>
                <span className="flex items-center gap-1.5"><Dot ok={status.ocr.available} /> OCR</span>
              </>
            ) : <span className="text-slate-400">Checking local models…</span>}
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right leading-tight">
              <div className="text-sm font-medium text-slate-800">{user?.full_name || user?.username}</div>
              <div className="text-[11px] capitalize text-slate-500">{user?.role}</div>
            </div>
            <button onClick={() => { logout(); nav("/login"); }} className="rounded-md p-2 text-slate-500 hover:bg-slate-100" aria-label="Log out" title="Log out">
              <LogOut className="h-4 w-4" />
            </button>
          </div>
        </header>
        <main className="flex-1 p-6"><Outlet /></main>
      </div>
    </div>
  );
}
