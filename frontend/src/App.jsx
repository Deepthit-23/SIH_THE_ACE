import { Link, Route, Routes } from "react-router-dom";
import { useState } from "react";
import Layout from "./components/Layout.jsx";
import RiskListPage from "./pages/RiskListPage.jsx";
import ProjectDetailPage from "./pages/ProjectDetailPage.jsx";
import PatternsPage from "./pages/PatternsPage.jsx";
import CasesPage from "./pages/CasesPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import EarlyWarningPage from "./pages/EarlyWarningPage.jsx";
import { clearSession, loadSession } from "./lib/session";

function NotFound() {
  return (
    <div className="rounded border border-slate-200 bg-white p-6 text-sm text-slate-600">
      <p className="font-medium">Page not found</p>
      <Link to="/" className="mt-2 inline-block text-slate-500 underline hover:text-ink">
        ← Back to the risk list
      </Link>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState(loadSession);
  if (!session) return <LoginPage onLogin={setSession} />;
  return (
    <Layout session={session} onLogout={() => { clearSession(); setSession(null); }}>
      <Routes>
        <Route path="/" element={<RiskListPage role={session.role} scopeLabel={session.scope_label} />} />
        <Route path="/early-warning" element={<EarlyWarningPage role={session.role} />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/patterns" element={<PatternsPage />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  );
}
