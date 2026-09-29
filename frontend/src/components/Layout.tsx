import { Activity, Bot, Cpu, Database, Gauge, GitCompareArrows, LayoutDashboard, Moon, Settings, Stethoscope, Sun, TrendingUp, UploadCloud, X } from "lucide-react";
import { useQueryClient } from "@tanstack/react-query";
import { KeyRound } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { ApiError, getApiKey, setApiKey, useApi, useFilters, useMeta } from "../api";

const NAV = [
  { section: "OVERVIEW" },
  { to: "/", label: "Executive Dashboard", icon: LayoutDashboard, n: "" },
  { section: "MODULES" },
  { to: "/experience", label: "Experience Analytics", icon: Activity, n: "M1" },
  { to: "/telemetry", label: "Telemetry Intelligence", icon: Cpu, n: "M2" },
  { to: "/correlation", label: "Correlation Engine", icon: GitCompareArrows, n: "M3" },
  { to: "/diagnosis", label: "Diagnosis Assist", icon: Stethoscope, n: "M4" },
  { to: "/copilot", label: "DEX Copilot", icon: Bot, n: "M5" },
  { to: "/outcomes", label: "Outcome Reporting", icon: TrendingUp, n: "M6" },
  { to: "/dex-score", label: "DEX Score", icon: Gauge, n: "M7" },
  { to: "/upload", label: "Upload Dataset", icon: UploadCloud, n: "M8" },
  { section: "ADMIN" },
  { to: "/settings", label: "Data & Settings", icon: Settings, n: "" },
] as const;

// Pages whose content honours the global filter row
const FILTERED = ["/", "/experience", "/telemetry", "/correlation", "/dex-score"];

function useTheme(): [string, () => void] {
  const [theme, setTheme] = useState<string>(() => {
    try { return localStorage.getItem("dex.theme") || "dark"; } catch { return "dark"; }
  });
  useEffect(() => {
    document.documentElement.setAttribute("data-theme", theme);
    try { localStorage.setItem("dex.theme", theme); } catch { /* ignore */ }
  }, [theme]);
  return [theme, () => setTheme(theme === "dark" ? "light" : "dark")];
}

function FilterBar() {
  const meta = useMeta();
  const { filters, set, clear, active } = useFilters();
  const dims = meta.data?.dimensions;
  if (meta.error) return null;
  if (!dims) return <span className="filter-label">loading filters…</span>;
  return (
    <div className="row" role="group" aria-label="Global filters">
      <span className="filter-label">FILTER</span>
      <select aria-label="Department" value={filters.department || ""} onChange={(e) => set({ department: e.target.value })}>
        <option value="">All departments</option>
        {dims.departments.map((d: string) => <option key={d}>{d}</option>)}
      </select>
      <select aria-label="Device model" value={filters.device_model || ""} onChange={(e) => set({ device_model: e.target.value })}>
        <option value="">All device models</option>
        {dims.device_models.map((d: string) => <option key={d}>{d}</option>)}
      </select>
      <select aria-label="Work mode" value={filters.work_mode || ""} onChange={(e) => set({ work_mode: e.target.value })}>
        <option value="">All work modes</option>
        {dims.work_modes.map((d: string) => <option key={d}>{d}</option>)}
      </select>
      <select aria-label="From week" value={filters.week_from || ""} onChange={(e) => set({ week_from: e.target.value })}>
        <option value="">From W1</option>
        {dims.weeks.map((w: { week: number; week_start: string }) => <option key={w.week} value={w.week} title={w.week_start}>From W{w.week}</option>)}
      </select>
      <select aria-label="To week" value={filters.week_to || ""} onChange={(e) => set({ week_to: e.target.value })}>
        <option value="">To W{dims.weeks.length}</option>
        {dims.weeks.map((w: { week: number; week_start: string }) => <option key={w.week} value={w.week}>To W{w.week}</option>)}
      </select>
      {active > 0 && <button className="btn btn-ghost btn-sm" onClick={clear}><X size={12} />Clear ({active})</button>}
    </div>
  );
}

/** Shown when the server requires an access key (DEX_API_KEY) and none / a wrong one is stored. */
function AccessKeyPrompt() {
  const qc = useQueryClient();
  const [key, setKey] = useState("");
  const hadKey = !!getApiKey();
  const save = () => { setApiKey(key.trim()); qc.invalidateQueries(); };
  return (
    <div className="card" role="dialog" aria-labelledby="ak-title" style={{ maxWidth: 520, margin: "60px auto" }}>
      <h3 id="ak-title" className="card-title" style={{ display: "flex", gap: 8, alignItems: "center" }}><KeyRound size={16} />Access key required</h3>
      <p className="note">{hadKey ? "The stored access key was rejected. Enter the current key." : "This DEX Sentinel instance is protected. Enter the access key you were given."}</p>
      <form className="row" onSubmit={(e) => { e.preventDefault(); if (key.trim()) save(); }}>
        <input type="password" autoFocus value={key} onChange={(e) => setKey(e.target.value)} placeholder="Access key"
               aria-label="Access key" style={{ flex: 1 }} autoComplete="off" />
        <button className="btn btn-primary" type="submit" disabled={!key.trim()}>Continue</button>
      </form>
      <p className="note" style={{ marginTop: 10 }}>The key is kept only in this browser.</p>
    </div>
  );
}

export default function Layout({ children }: { children: ReactNode }) {
  const [theme, toggle] = useTheme();
  const loc = useLocation();
  const meta = useMeta();
  const status = useApi("/v1/copilot/status");
  const showFilters = FILTERED.includes(loc.pathname);
  const counts = meta.data?.counts;
  return (
    <div className="app">
      <aside className="sidebar" aria-label="Main navigation">
        <div className="brand">
          <div className="brand-mark">
            <svg width="20" height="20" viewBox="0 0 32 32" aria-hidden="true"><path d="M4 21 L11 12 L17 18 L27 7" stroke="var(--machine)" strokeWidth="3.2" fill="none" strokeLinecap="round" strokeLinejoin="round" /><circle cx="27" cy="7" r="3" fill="var(--human)" /></svg>
          </div>
          <div><h1>DEX Sentinel</h1><small>sentiment × telemetry</small></div>
        </div>
        {NAV.map((item, i) =>
          "section" in item ? <div key={i} className="nav-section">{item.section}</div> : (
            <NavLink key={item.to} to={{ pathname: item.to, search: FILTERED.includes(item.to) ? loc.search : "" }} end={item.to === "/"}
                     className={({ isActive }) => `nav-link${isActive ? " active" : ""}`}>
              <item.icon size={16} />{item.label}{item.n && <span className="n">{item.n}</span>}
            </NavLink>
          ))}
        <div className="sidebar-foot">
          {counts ? <>{counts.devices.toLocaleString()} devices · {counts.tickets.toLocaleString()} tickets<br />{counts.remediations.toLocaleString()} remediations · {meta.data.dimensions.weeks.length} wks</> : "…"}
          <br /><Database size={10} style={{ verticalAlign: -1 }} /> {meta.data?.dataset?.source ? String(meta.data.dataset.source).slice(0, 34) : "dataset"}
        </div>
      </aside>
      <div className="main">
        <header className="topbar">
          {showFilters ? <FilterBar /> : <span className="filter-label">{loc.pathname === "/diagnosis" ? "TICKET + DEVICE INTAKE" : ""}</span>}
          <div className="spacer" />
          {status.data && (
            <span className="chip" title={status.data.llm_enabled ? `LLM: ${status.data.model}` : "No LLM key configured — grounded template engine"}>
              <Bot size={12} />Copilot: {status.data.llm_enabled ? status.data.provider : "grounded template"}
            </span>
          )}
          <button className="btn btn-ghost btn-sm" onClick={toggle} aria-label={`Switch to ${theme === "dark" ? "light" : "dark"} theme`}>
            {theme === "dark" ? <Sun size={13} /> : <Moon size={13} />}
          </button>
        </header>
        <main className="content">
          {meta.error instanceof ApiError && meta.error.status === 401 ? <AccessKeyPrompt /> : children}
        </main>
      </div>
    </div>
  );
}
