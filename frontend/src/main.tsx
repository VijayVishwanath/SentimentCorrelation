import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import TabbedPage, { TabRedirect } from "./components/TabbedPage";
import { Loading } from "./components/ui";
import "./styles.css";

try { document.documentElement.setAttribute("data-theme", localStorage.getItem("dex.theme") || "dark"); } catch { /* ignore */ }

const CommandCenter = lazy(() => import("./pages/CommandCenter"));
const Experience = lazy(() => import("./pages/Experience"));
const Telemetry = lazy(() => import("./pages/Telemetry"));
const Correlation = lazy(() => import("./pages/Correlation"));
const Diagnosis = lazy(() => import("./pages/Diagnosis"));
const Copilot = lazy(() => import("./pages/Copilot"));
const Outcomes = lazy(() => import("./pages/Outcomes"));
const DexScore = lazy(() => import("./pages/DexScore"));
const Proactive = lazy(() => import("./pages/Proactive"));
const Device = lazy(() => import("./pages/Device"));
const SettingsPage = lazy(() => import("./pages/Settings"));
const UploadPage = lazy(() => import("./pages/Upload"));
const Remediation = lazy(() => import("./pages/Remediation"));
const Benefits = lazy(() => import("./pages/Roi"));
const CriticalFew = lazy(() => import("./pages/CriticalFew"));

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Layout>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={<CommandCenter />} />
              <Route path="/proactive" element={<Proactive />} />
              <Route path="/diagnosis" element={<TabbedPage label="Diagnose" tabs={[
                { key: "diagnosis", label: "Diagnosis Assist", element: <Diagnosis /> },
                { key: "copilot", label: "DEX Copilot", element: <Copilot /> }]} />} />
              <Route path="/remediation" element={<Remediation />} />
              <Route path="/value" element={<TabbedPage label="Proof and value" tabs={[
                { key: "outcomes", label: "Outcomes", element: <Outcomes /> },
                { key: "benefits", label: "Annual Benefits", element: <Benefits /> },
                { key: "critical-few", label: "Critical Few · 80/20", element: <CriticalFew /> }]} />} />
              <Route path="/evidence" element={<TabbedPage label="Evidence" tabs={[
                { key: "dex-score", label: "DEX Score", element: <DexScore /> },
                { key: "experience", label: "Experience", element: <Experience /> },
                { key: "telemetry", label: "Telemetry", element: <Telemetry /> },
                { key: "correlation", label: "Correlation", element: <Correlation /> }]} />} />
              <Route path="/data" element={<TabbedPage label="Data and settings" tabs={[
                { key: "sources", label: "Data Sources", element: <UploadPage /> },
                { key: "settings", label: "Settings", element: <SettingsPage /> }]} />} />
              <Route path="/devices/:id" element={<Device />} />
              {/* old page URLs: keep every link and deep link working */}
              <Route path="/copilot" element={<TabRedirect to="/diagnosis" tab="copilot" />} />
              <Route path="/outcomes" element={<TabRedirect to="/value" tab="outcomes" />} />
              <Route path="/roi" element={<TabRedirect to="/value" tab="benefits" />} />
              <Route path="/dex-score" element={<TabRedirect to="/evidence" tab="dex-score" />} />
              <Route path="/experience" element={<TabRedirect to="/evidence" tab="experience" />} />
              <Route path="/telemetry" element={<TabRedirect to="/evidence" tab="telemetry" />} />
              <Route path="/correlation" element={<TabRedirect to="/evidence" tab="correlation" />} />
              <Route path="/upload" element={<TabRedirect to="/data" tab="sources" />} />
              <Route path="/settings" element={<TabRedirect to="/data" tab="settings" />} />
              <Route path="*" element={<div className="empty">Page not found</div>} />
            </Routes>
          </Suspense>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
