import { Link, Route, Routes } from "react-router-dom";
import { useState } from "react";
import Layout from "./components/Layout.jsx";
import RiskListPage from "./pages/RiskListPage.jsx";
import ProjectDetailPage from "./pages/ProjectDetailPage.jsx";
import PatternsPage from "./pages/PatternsPage.jsx";
import CasesPage from "./pages/CasesPage.jsx";
import LoginPage from "./pages/LoginPage.jsx";
import EarlyWarningPage from "./pages/EarlyWarningPage.jsx";
import AdminUsersPage from "./pages/AdminUsersPage.jsx";
import ChangePasswordPage from "./pages/ChangePasswordPage.jsx";
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

function NotAuthorised() {
  return (
    <div className="rounded border border-slate-200 bg-white p-6 text-sm text-slate-600">
      <p className="font-medium">Ministry access required</p>
      <p className="mt-1 text-slate-500">User management is available to the Ministry role only.</p>
      <Link to="/" className="mt-2 inline-block text-slate-500 underline hover:text-ink">← Back to the risk list</Link>
    </div>
  );
}

export default function App() {
  const [session, setSession] = useState(loadSession);
  if (!session) return <LoginPage onLogin={setSession} />;
  const logout = () => { clearSession(); setSession(null); };
  // A freshly provisioned account must replace its temporary password before anything else loads
  // (the backend enforces this too: every other endpoint answers 403 until it is done).
  if (session.must_change_password) {
    return <ChangePasswordPage session={session} onDone={setSession} onLogout={logout} />;
  }
  return (
    <Layout session={session} onLogout={logout}>
      <Routes>
        <Route path="/" element={<RiskListPage role={session.role} scopeLabel={session.scope_label} />} />
        <Route path="/early-warning" element={<EarlyWarningPage role={session.role} />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/patterns" element={<PatternsPage />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="/admin/users" element={session.role === "ministry" ? <AdminUsersPage session={session} /> : <NotAuthorised />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  );
}
