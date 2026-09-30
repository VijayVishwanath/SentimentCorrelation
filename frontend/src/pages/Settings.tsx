import { useQueryClient } from "@tanstack/react-query";
import { Save, UploadCloud } from "lucide-react";
import { Link } from "react-router-dom";
import { useEffect, useState } from "react";
import { Any, api, fmt, getApiKey, setApiKey, useApi } from "../api";
import { Card, ErrorBox, QueryState } from "../components/ui";

export default function SettingsPage() {
  const qc = useQueryClient();
  const meta = useApi("/v1/meta");
  const settings = useApi("/v1/settings");
  const metrics = useApi("/v1/models/metrics");
  const status = useApi("/v1/copilot/status");
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

  const save = () => act(async () => { await api("/v1/settings", { method: "PUT", body: JSON.stringify(form) }); return "Assumptions saved — business impact recalculated."; });

  const FIELDS: [string, string, number][] = [
    ["cost_per_ticket_usd", "Cost per ticket (USD)", 1], ["hourly_employee_cost_usd", "Employee cost per hour (USD)", 1],
    ["productivity_loss_factor", "Productivity loss while impaired (0-1)", 0.05], ["resolution_sla_hours", "Resolution SLA (hours)", 0.5],
  ];

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Admin</div>
          <h2>Data & Settings</h2>
          <p>Dataset management, business-impact assumptions, AI model evaluation and API access.</p>
        </div>
      </div>
      {msg && <div className="card-flat" role="status" style={{ marginBottom: 14, borderColor: "var(--machine-dim)" }}>{msg}</div>}
      {err ? <div style={{ marginBottom: 14 }}><ErrorBox error={err} />{issues.length > 0 && <ul className="note">{issues.map((i) => <li key={i}>{i}</li>)}</ul>}</div> : null}
      <div className="grid g-2">
        <Card title="Dataset" sub="the data every module is analysing">
          <QueryState q={meta}>
            {(m: Any) => (
              <dl className="kv">
                <dt>Source</dt><dd>{m.dataset?.source}</dd>
                <dt>Loaded</dt><dd>{m.dataset?.loaded_at ? new Date(m.dataset.loaded_at).toLocaleString() : "—"}</dd>
                <dt>Rows</dt><dd className="mono">{m.counts.devices} devices · {m.counts.telemetry_rows} telemetry · {m.counts.tickets} tickets · {m.counts.remediations} remediations</dd>
                <dt>Weeks</dt><dd className="mono">{m.dimensions.weeks.length} ({m.dimensions.weeks[0]?.week_start} → {m.dimensions.weeks[m.dimensions.weeks.length - 1]?.week_start})</dd>
              </dl>
            )}
          </QueryState>
          <Link to="/upload" className="btn btn-primary mt"><UploadCloud size={14} />Upload a new dataset</Link>
        </Card>

        <Card title="Business-impact assumptions" sub="drive Business Impact Savings and Resolution Efficiency">
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
                  scores are near-perfect by construction. Telemetry-only accuracy and the out-of-time forecast below are the fair read;
                  real ticket text will score lower.</div>
                <table className="t mt">
                  <thead><tr><th>Next-week frustrated-ticket prediction</th><th className="num">Caught (top 5%)</th><th className="num">PR-AUC</th><th className="num">ROC-AUC</th></tr></thead>
                  <tbody>
                    {m.forecast.available ? (
                      <>
                        <tr><td>ML: LightGBM on telemetry trends + experience history</td><td className="num">{fmt.pct(m.forecast.backtest.ml.recall_pct)}</td>
                          <td className="num">{fmt.n(m.forecast.backtest.ml.pr_auc, 3)}</td><td className="num">{fmt.n(m.forecast.backtest.ml.roc_auc, 3)}</td></tr>
                        <tr><td>Rules: at-risk score (60% severity + 40% burden)</td><td className="num">{fmt.pct(m.forecast.backtest.rules.recall_pct)}</td>
                          <td className="num">{fmt.n(m.forecast.backtest.rules.pr_auc, 3)}</td><td className="num">{fmt.n(m.forecast.backtest.rules.roc_auc, 3)}</td></tr>
                      </>
                    ) : <tr><td colSpan={4} className="faint">{m.forecast.reason}</td></tr>}
                  </tbody>
                </table>
                {m.forecast.available && <div className="note mt">{m.forecast.backtest.method} · {fmt.i(m.forecast.backtest.positives)} frustrated tickets scored
                  {m.forecast.low_sample ? " · low sample — indicative only" : ""}.</div>}
              </>
            )}
          </QueryState>
        </Card>

        <Card title="Copilot & API access">
          <QueryState q={status}>
            {(s: Any) => (
              <dl className="kv">
                <dt>Provider</dt><dd>{s.provider}</dd><dt>Model</dt><dd className="mono">{s.model}</dd>
                <dt>KB articles</dt><dd>{s.kb_articles}</dd>
              </dl>
            )}
          </QueryState>
          <div className="note mt">Enable LLM mode by setting <span className="mono">ANTHROPIC_API_KEY</span> (Claude, default) or <span className="mono">AZURE_OPENAI_*</span> on the server.
            Without a key the Copilot answers from the grounded template engine using the same tools.</div>
          <label className="field mt" htmlFor="apikey">API key (only if the server sets DEX_API_KEY)</label>
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
