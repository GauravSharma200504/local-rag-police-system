import { Navigate, Route, Routes } from "react-router-dom";
import { useAuth } from "@/contexts/AuthContext";
import { AppLayout } from "@/layouts/AppLayout";
import { Spinner } from "@/components/ui/primitives";
import LoginPage from "@/pages/Login";
import DashboardPage from "@/pages/Dashboard";
import AssistantPage from "@/pages/Assistant";
import DocumentsPage from "@/pages/Documents";
import DocumentDetailPage from "@/pages/DocumentDetail";
import CasesPage from "@/pages/Cases";
import CaseDetailPage from "@/pages/CaseDetail";
import ComparePage from "@/pages/Compare";
import LegalPage from "@/pages/Legal";
import ReportsPage from "@/pages/Reports";
import SettingsPage from "@/pages/Settings";

function Protected({ children }: { children: JSX.Element }) {
  const { user, loading } = useAuth();
  if (loading) return <div className="flex h-screen items-center justify-center"><Spinner /></div>;
  return user ? children : <Navigate to="/login" replace />;
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<LoginPage />} />
      <Route element={<Protected><AppLayout /></Protected>}>
        <Route index element={<DashboardPage />} />
        <Route path="assistant" element={<AssistantPage />} />
        <Route path="assistant/:conversationId" element={<AssistantPage />} />
        <Route path="documents" element={<DocumentsPage />} />
        <Route path="documents/:id" element={<DocumentDetailPage />} />
        <Route path="cases" element={<CasesPage />} />
        <Route path="cases/:id" element={<CaseDetailPage />} />
        <Route path="compare" element={<ComparePage />} />
        <Route path="legal" element={<LegalPage />} />
        <Route path="reports" element={<ReportsPage />} />
        <Route path="reports/:id" element={<ReportsPage />} />
        <Route path="settings" element={<SettingsPage />} />
      </Route>
      <Route path="*" element={<Navigate to="/" replace />} />
    </Routes>
  );
}
