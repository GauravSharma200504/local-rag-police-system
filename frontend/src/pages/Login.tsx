import { useState, type FormEvent } from "react";
import { Navigate, useNavigate } from "react-router-dom";
import { ShieldCheck } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";
import { ErrorBox, Input, Label } from "@/components/ui/primitives";
import { errorMessage } from "@/services/api";

export default function LoginPage() {
  const { user, login } = useAuth();
  const nav = useNavigate();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  if (user) return <Navigate to="/" replace />;

  const submit = async (e: FormEvent) => {
    e.preventDefault();
    setBusy(true);
    setError(null);
    try {
      await login(username, password);
      nav("/");
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-navy-900 px-4">
      <div className="w-full max-w-sm">
        <div className="mb-6 flex flex-col items-center text-center">
          <div className="mb-3 rounded-xl bg-amber-500/15 p-3"><ShieldCheck className="h-8 w-8 text-amber-400" /></div>
          <h1 className="text-lg font-semibold text-white">Bharat Police Intelligence</h1>
          <p className="mt-1 text-xs text-slate-400">Local AI document intelligence & legal assistance</p>
        </div>
        <form onSubmit={submit} className="rounded-lg bg-white p-6 shadow-xl">
          <div className="space-y-4">
            <div><Label htmlFor="username">Username</Label><Input id="username" autoComplete="username" value={username} onChange={(e) => setUsername(e.target.value)} required /></div>
            <div><Label htmlFor="password">Password</Label><Input id="password" type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></div>
            {error && <ErrorBox message={error} />}
            <Button type="submit" className="w-full" loading={busy}>Sign in</Button>
          </div>
          <p className="mt-4 text-center text-[11px] text-slate-500">Authorized personnel only. All access is recorded in the audit log.</p>
        </form>
      </div>
    </div>
  );
}
