import { useQueryClient } from "@tanstack/react-query";
import { Save } from "lucide-react";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { Any, api, fmt, getApiKey, setApiKey, useApi } from "../api";
import { Card, ErrorBox, QueryState } from "../components/ui";

export default function SettingsPage() {
  const qc = useQueryClient();
  const settings = useApi("/v1/settings");
  const metrics = useApi("/v1/models/metrics");
  const [form, setForm] = useState<Record<string, number>>({});
  const [key, setKey] = useState(getApiKey());
  const [msg, setMsg] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const [issues, setIssues] = useState<string[]>([]);
  const [busy, setBusy] = useState(false);

  useEffect(() => { if (settings.data) setForm(settings.data); }, [settings.data]);

  const refreshAll = () => qc.invalidateQueries();
  const act = async (fn: () => Promise<string>) => {
    setBusy(true); setErr(null); setMsg(null); setIssues([]);
    try { setMsg(await fn()); refreshAll(); } catch (e) { setErr(e); } finally { setBusy(false); }
  };

  // cost assumptions (per ticket, per hour, licences, devices) are edited once, on Value & Priorities
  const FIELDS: [string, string, number][] = [
    ["productivity_loss_factor", "Productivity loss while impaired (0-1)", 0.05], ["resolution_sla_hours", "Resolution SLA (hours)", 0.5],
  ];
  const save = () => act(async () => {
    const body = Object.fromEntries(FIELDS.map(([k]) => [k, form[k]]));
    await api("/v1/settings", { method: "PUT", body: JSON.stringify(body) });
    return "Assumptions saved — every view recalculated.";
  });

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Admin</div>
          <h2>Data & Settings</h2>
          <p>Analysis assumptions, AI model evaluation and API access. Data is managed on <Link to="/upload">Data Sources</Link>;
            cost assumptions on <Link to="/roi">Value &amp; Priorities</Link>.</p>
        </div>
      </div>
      {msg && <div className="card-flat" role="status" style={{ marginBottom: 14, borderColor: "var(--machine-dim)" }}>{msg}</div>}
      {err ? <div style={{ marginBottom: 14 }}><ErrorBox error={err} />{issues.length > 0 && <ul className="note">{issues.map((i) => <li key={i}>{i}</li>)}</ul>}</div> : null}
      <div className="grid g-2">
        <Card title="Analysis assumptions" sub="drive Resolution Efficiency in the DEX Score and the productivity share of benefits">
          {FIELDS.map(([k, label, step]) => (
            <div key={k} style={{ marginBottom: 10 }}>
              <label className="field" htmlFor={k}>{label}</label>
              <input id={k} type="number" step={step} value={form[k] ?? ""} onChange={(e) => setForm({ ...form, [k]: +e.target.value })} style={{ width: "100%" }} />
            </div>
          ))}
          <button className="btn btn-primary" onClick={save} disabled={busy}><Save size={14} />Save assumptions</button>
        </Card>

        <Card title="AI models" sub="how each engine is evaluated">
          <QueryState q={metrics}>
            {(m: Any) => (
              <>
                <table className="t">
                  <thead><tr><th>Root-cause model</th><th className="num">Top-1 accuracy</th></tr></thead>
                  <tbody>
                    <tr><td>Rule fusion engine (65% telemetry / 35% text) — primary</td><td className="num">{fmt.pct(m.root_cause.rule_engine)}</td></tr>
                    <tr><td>ML: TF-IDF text + telemetry (logistic regression) <span className="faint">†</span></td><td className="num">{fmt.pct(m.root_cause.fused_ml)}</td></tr>
                    <tr><td>ML: text only <span className="faint">†</span></td><td className="num">{fmt.pct(m.root_cause.text_only_ml)}</td></tr>
                    <tr><td>ML: telemetry only</td><td className="num">{fmt.pct(m.root_cause.telemetry_only_ml)}</td></tr>
                    <tr><td>Sentiment lexicon vs hidden ground-truth tier <span className="faint">†</span></td><td className="num">{fmt.pct(m.sentiment_lexicon.validated_agreement_pct)}</td></tr>
                  </tbody>
                </table>
                <div className="note mt">{m.root_cause.evaluation} · n = {m.root_cause.n}. {m.disclosure}</div>
                <div className="note">† Upper bound: the simulated tickets are written from a few sentence templates per category, so text-based
                  scores are near-perfect by construction. Telemetry-only accuracy and the out-of-time forecast are the fair read;
                  real ticket text will score lower.</div>
                <div className="note mt">The next-week frustration forecast is evaluated against the rule baseline on <Link to="/proactive">Proactive Watchlist</Link>.</div>
              </>
            )}
          </QueryState>
        </Card>

        <Card title="API access">
          <label className="field" htmlFor="apikey">API key (only if the server sets DEX_API_KEY)</label>
          <div className="row">
            <input id="apikey" type="text" value={key} onChange={(e) => setKey(e.target.value)} style={{ flex: 1 }} autoComplete="off" />
            <button className="btn btn-ghost" onClick={() => { setApiKey(key.trim()); refreshAll(); setMsg("API key stored in this browser."); }}>Save</button>
          </div>
          <div className="note mt">API reference: <a href="/docs" target="_blank" rel="noreferrer">/docs</a> (OpenAPI)</div>
        </Card>
      </div>
    </>
  );
}
