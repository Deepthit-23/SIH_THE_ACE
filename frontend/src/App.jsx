import Layout from "./components/Layout.jsx";
import ProjectsPage from "./pages/ProjectsPage.jsx";

// Single page for Phase 1. Routing (react-router) is wired in Phase 5.
export default function App() {
  return (
    <Layout>
      <ProjectsPage />
    </Layout>
  );
}
