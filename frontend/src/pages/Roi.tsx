import { useQueryClient } from "@tanstack/react-query";
import { AnalystOnly } from "../components/analyst";
import { RotateCcw, Save } from "lucide-react";
import { useEffect, useState } from "react";
import { Any, api, fmt, qsOf, useApi, useFilters } from "../api";
import { Card, ErrorBox, MoneyChip, QueryState } from "../components/ui";

const COLORS: Record<string, string> = {
  tickets: "var(--chart-human)", productivity: "var(--chart-machine)", licenses: "var(--serious)", hardware: "var(--text-dim)",
};
const SOURCE: Record<string, [string, string]> = {
  measured: ["Measured", "var(--machine)"], derived: ["Derived", "var(--machine)"],
  assumption: ["Assumption", "var(--human)"], "what-if": ["What-if", "var(--serious)"],
};
const LABEL: Record<string, string> = {
  tickets_avoided: "Tickets avoided", cost_per_ticket_usd: "Average cost per ticket", affected_employees: "Affected employees",
  minutes_saved_per_day: "Minutes saved per day", working_days_per_year: "Working days per year",
  hourly_employee_cost_usd: "Average hourly employee cost", unused_licenses: "Unused licenses",
  annual_license_cost_usd: "Annual license cost", avoided_replacements: "Avoided replacements", device_cost_usd: "Device cost",
};
// inputs that can be saved as defaults (tickets avoided and affected employees are always measured from the data)
const SETTING_KEY: Record<string, string> = {
  cost_per_ticket_usd: "cost_per_ticket_usd", hourly_employee_cost_usd: "hourly_employee_cost_usd",
  working_days_per_year: "working_days_per_year", minutes_saved_per_day: "roi_minutes_saved_per_day",
  unused_licenses: "roi_unused_licenses", annual_license_cost_usd: "annual_license_cost_usd",
  avoided_replacements: "roi_avoided_replacements", device_cost_usd: "device_cost_usd",
};
const usd = fmt.usdShort;

function SourceChip({ s }: { s: string }) {
  const [label, color] = SOURCE[s] || [s, "var(--text-dim)"];
  return <span className="badge" style={{ color, borderColor: color }}>{label}</span>;
}

export default function Benefits() {
  const qc = useQueryClient();
  const { filters } = useFilters();
  const [scenario, setScenario] = useState<"realized" | "with_plan">("realized");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [whatIf, setWhatIf] = useState<Record<string, string>>({});
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  useEffect(() => { const t = setTimeout(() => setWhatIf(draft), 400); return () => clearTimeout(t); }, [draft]);
  const q = useApi(`/v1/roi${qsOf({ department: filters.department, scenario, ...whatIf })}`);

  const refresh = () => qc.invalidateQueries({ predicate: (x) => /^\/v1\/(roi|dashboard|settings)/.test(String(x.queryKey[0])) });
  const saveDefaults = async () => {
    setErr(null); setMsg(null);
    const body: Record<string, number> = {};
    Object.entries(whatIf).forEach(([k, v]) => { if (SETTING_KEY[k] && v !== "") body[SETTING_KEY[k]] = +v; });
    try {
      await api("/v1/settings", { method: "PUT", body: JSON.stringify(body) });
      setDraft({}); setWhatIf({}); refresh();
      setMsg(`Saved ${Object.keys(body).length} assumption(s) as defaults for every page.`);
    } catch (e) { setErr(e); }
  };
  const resetAll = async () => {
    setErr(null); setMsg(null);
    try {
      await api("/v1/settings", { method: "PUT", body: JSON.stringify({ reset: ["roi_minutes_saved_per_day", "roi_unused_licenses", "roi_avoided_replacements",
        "working_days_per_year", "annual_license_cost_usd", "device_cost_usd"] }) });
      setDraft({}); setWhatIf({}); refresh(); setMsg("ROI inputs reset to the data-derived values and defaults.");
    } catch (e) { setErr(e); }
  };
  const saveable = Object.keys(whatIf).some((k) => SETTING_KEY[k] && whatIf[k] !== "");

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Annual Benefits · ROI</div>
          <h2>What DEX Sentinel is worth per year</h2>
          <p>What fixing the experience is worth per year. Edit any input to test a scenario.</p>
        </div>
        <div className="seg" role="group" aria-label="Scenario">
          <button className={scenario === "realized" ? "on" : ""} onClick={() => setScenario("realized")}>Realised (past fixes)</button>
          <button className={scenario === "with_plan" ? "on" : ""} onClick={() => setScenario("with_plan")}>+ Top 3 planned fixes</button>
        </div>
      </div>
      {msg && <div className="card-flat" role="status" style={{ marginBottom: 14, borderColor: "var(--machine-dim)" }}>{msg}</div>}
      {err ? <div style={{ marginBottom: 14 }}><ErrorBox error={err} /></div> : null}
      <QueryState q={q} label="Computing annual benefits…">
        {(d: Any) => (
          <>
            <Card>
              <div className="row between" style={{ alignItems: "flex-end" }}>
                <div>
                  <div className="eyebrow" style={{ margin: 0 }}>DEX Sentinel Annual Benefits{d.department ? ` · ${d.department}` : ""}
                    <MoneyChip kind="realised" />{scenario === "with_plan" && <MoneyChip kind="planned" />}</div>
                  <div style={{ fontSize: 52, fontWeight: 800, lineHeight: 1.05 }} className="good">{usd(d.total_usd)}<span className="faint" style={{ fontSize: 18 }}> / year</span></div>
                  <div className="note">{usd(d.data_backed_usd)} of it is data-backed (volumes measured from the dataset) · {d.note}</div>
                </div>
                <div className="row">
                  <button className="btn btn-primary btn-sm" onClick={saveDefaults} disabled={!saveable} title="Use the edited values everywhere (Settings)"><Save size={13} />Save as defaults</button>
                  <button className="btn btn-ghost btn-sm" onClick={resetAll}><RotateCcw size={13} />Reset to data</button>
                </div>
              </div>
              <AnalystOnly><div className="mono mt" style={{ fontSize: 12 }}>{d.formula}</div></AnalystOnly>
              <div style={{ display: "flex", height: 16, borderRadius: 8, overflow: "hidden", marginTop: 12 }} role="img" aria-label="Benefit mix">
                {d.components.map((c: Any) => c.value_usd > 0 && (
                  <div key={c.key} title={`${c.label}: ${usd(c.value_usd)}`} style={{ flex: c.value_usd, background: COLORS[c.key] }} />
                ))}
              </div>
              <div className="row mt" style={{ gap: 18 }}>
                {d.components.map((c: Any) => (
                  <span key={c.key} style={{ fontSize: 12.5 }}>
                    <i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: COLORS[c.key], marginRight: 6 }} />
                    {c.label} <b>{usd(c.value_usd)}</b> <span className="faint">{d.total_usd ? fmt.pct((100 * c.value_usd) / d.total_usd, 0) : ""}</span>
                  </span>
                ))}
              </div>
            </Card>

            <div className="grid g-2 mt">
              {d.components.map((c: Any) => (
                <Card key={c.key} title={c.label} style={{ borderTop: `3px solid ${COLORS[c.key]}` }}
                      right={<div style={{ textAlign: "right" }}><div style={{ fontSize: 26, fontWeight: 800 }}>{usd(c.value_usd)}</div>
                        <div className="note">{c.data_backed ? "data-backed" : "assumption-based"}</div></div>}>
                  <AnalystOnly><div className="mono" style={{ fontSize: 12, marginBottom: 12 }}>{c.formula}</div></AnalystOnly>
                  {c.inputs.map((k: string) => {
                    const inp = d.inputs[k];
                    return (
                      <div key={k} style={{ display: "grid", gridTemplateColumns: "minmax(150px, 1fr) 130px 90px", gap: 10, alignItems: "center", marginBottom: 8 }}>
                        <div style={{ fontSize: 13 }}>{LABEL[k]}<div className="faint" style={{ fontSize: 11 }}>{inp.note}</div></div>
                        <div className="row" style={{ gap: 4, flexWrap: "nowrap" }}>
                          <input type="number" min={0} aria-label={LABEL[k]} value={draft[k] ?? String(inp.value)} style={{ width: "100%" }}
                                 onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />
                          <span className="faint" style={{ fontSize: 11, whiteSpace: "nowrap" }}>{inp.unit}</span>
                        </div>
                        <SourceChip s={inp.source} />
                      </div>
                    );
                  })}
                  {c.key === "productivity" && <div className="note">= {fmt.i(c.recovered_hours)} recovered hours per year</div>}
                </Card>
              ))}
            </div>
            <AnalystOnly><footer className="foot">Ticket cost uses the service-desk handling cost only; employee time lost is counted once, in Productivity Recovery.
              Measured = counted in the dataset · Derived = computed from measured data by the stated rule · Assumption = replace with your own figures.</footer></AnalystOnly>
          </>
        )}
      </QueryState>
    </>
  );
}
