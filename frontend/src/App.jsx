import { Link, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout.jsx";
import RiskListPage from "./pages/RiskListPage.jsx";
import ProjectDetailPage from "./pages/ProjectDetailPage.jsx";
import PatternsPage from "./pages/PatternsPage.jsx";
import CasesPage from "./pages/CasesPage.jsx";

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
  return (
    <Layout>
      <Routes>
        <Route path="/" element={<RiskListPage />} />
        <Route path="/projects/:id" element={<ProjectDetailPage />} />
        <Route path="/patterns" element={<PatternsPage />} />
        <Route path="/cases" element={<CasesPage />} />
        <Route path="*" element={<NotFound />} />
      </Routes>
    </Layout>
  );
}
