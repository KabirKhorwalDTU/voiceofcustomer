import { BrowserRouter, Navigate, Route, Routes } from "react-router-dom";
import { Dashboard } from "./pages/Dashboard";
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
        <Route path="/kabir" element={<Dashboard />} />
        <Route path="/kabir/runs/:runId" element={<ResultsPage />} />
        <Route path="/runs/:runId" element={<ResultsPage />} />
        <Route path="/companies/:companyId/runs/:runId" element={<ResultsPage />} />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    </BrowserRouter>
  );
}
