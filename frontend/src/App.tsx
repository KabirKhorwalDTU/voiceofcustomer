import { BrowserRouter, Navigate, Route, Routes, useLocation, useParams } from "react-router-dom";
import { LandingPage } from "./pages/LandingPage";
import { ProductWorkspace } from "./pages/ProductWorkspace";
import { ResultsPage } from "./pages/ResultsPage";
import { SampleReportPage } from "./pages/SampleReportPage";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route path="/" element={<LandingPage />} />
        <Route path="/sample/first-club" element={<SampleReportPage />} />
        <Route path="/app" element={<ProductWorkspace />} />
        <Route path="/app/runs/:runId" element={<ResultsPage />} />
        <Route path="/kabir" element={<LegacyWorkspaceRedirect />} />
        <Route path="/kabir/runs/:runId" element={<LegacyRunRedirect />} />
        <Route path="/runs/:runId" element={<LegacyRunRedirect />} />
        <Route path="/companies/:companyId/runs/:runId" element={<LegacyRunRedirect />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}

function LegacyWorkspaceRedirect() {
  const location = useLocation();
  return <Navigate to={{ pathname: "/app", search: location.search }} replace />;
}

function LegacyRunRedirect() {
  const { runId } = useParams();
  const location = useLocation();
  return <Navigate to={{ pathname: `/app/runs/${runId || ""}`, search: location.search }} replace />;
}
