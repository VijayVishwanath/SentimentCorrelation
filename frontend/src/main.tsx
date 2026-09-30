import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import React, { lazy, Suspense } from "react";
import ReactDOM from "react-dom/client";
import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import { Loading } from "./components/ui";
import "./styles.css";

try { document.documentElement.setAttribute("data-theme", localStorage.getItem("dex.theme") || "dark"); } catch { /* ignore */ }

const Executive = lazy(() => import("./pages/Executive"));
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

const qc = new QueryClient({ defaultOptions: { queries: { refetchOnWindowFocus: false } } });

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={qc}>
      <BrowserRouter>
        <Layout>
          <Suspense fallback={<Loading />}>
            <Routes>
              <Route path="/" element={<Executive />} />
              <Route path="/experience" element={<Experience />} />
              <Route path="/telemetry" element={<Telemetry />} />
              <Route path="/correlation" element={<Correlation />} />
              <Route path="/diagnosis" element={<Diagnosis />} />
              <Route path="/copilot" element={<Copilot />} />
              <Route path="/outcomes" element={<Outcomes />} />
              <Route path="/dex-score" element={<DexScore />} />
              <Route path="/proactive" element={<Proactive />} />
              <Route path="/devices/:id" element={<Device />} />
              <Route path="/settings" element={<SettingsPage />} />
              <Route path="/upload" element={<UploadPage />} />
              <Route path="*" element={<div className="empty">Page not found</div>} />
            </Routes>
          </Suspense>
        </Layout>
      </BrowserRouter>
    </QueryClientProvider>
  </React.StrictMode>,
);
