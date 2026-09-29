import { AlertTriangle, CheckCircle2, DollarSign, GitCompareArrows, HeartPulse, Info, Repeat, ShieldAlert, Smile, TrendingUp } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Any, bandColor, fmt, useApi, useFilters } from "../api";
import { Bars, TrendChart } from "../components/charts";
import { Card, ChartCard, DataTable, Kpi, Meter, PrePost, QueryState } from "../components/ui";

const COMP_LABEL: Record<string, string> = { eei: "Experience Index", dhs: "Device Health", rss: "Remediation Success", tre: "Resolution Efficiency", sts: "Sentiment Trend" };
const INSIGHT_ACCENT: Record<string, string> = { high: "var(--critical)", medium: "var(--human)", positive: "var(--machine)", info: "var(--text-faint)" };

export default function Executive() {
  const { qs } = useFilters();
  const q = useApi(`/v1/dashboard/executive${qs}`);
  const nav = useNavigate();
  return (
    <QueryState q={q}>
      {(d: Any) => {
        const k = d.kpis;
        return (
          <>
            <div className="page-head">
              <div>
                <div className="eyebrow">Executive Dashboard · outcome-based DEX</div>
                <h2>Is the employee experience actually getting better?</h2>
                <p>Employee sentiment from calls, tickets and chats, fused with endpoint telemetry. Scope: {d.scope.devices} devices,
                  {" "}{d.scope.tickets} tickets, weeks {d.scope.weeks[0]}–{d.scope.weeks[d.scope.weeks.length - 1]}.</p>
              </div>
            </div>

            <div className="grid g-main">
              <Card title="DEX Score" sub="0.35·EEI + 0.25·Device Health + 0.20·Remediation Success + 0.10·Resolution Efficiency + 0.10·Sentiment Trend">
                <div className="hero">
                  <div>
                    <div className="hero-num">{fmt.n(k.dex_score)}</div>
                    <div className="row mt" style={{ gap: 8 }}>
                      <span className="band" style={{ color: bandColor(k.dex_band) }}>{k.dex_band}</span>
                      {k.dex_delta !== null && <span className={k.dex_delta >= 0 ? "good" : "crit"} style={{ fontSize: 12.5, fontWeight: 600 }}>
                        {fmt.signed(k.dex_delta)} pts vs first half of window</span>}
                    </div>
                  </div>
                  <div style={{ flex: 1, minWidth: 220 }}>
                    {Object.entries(k.components as Record<string, number>).map(([key, v]) => (
                      <div key={key} style={{ marginBottom: 8 }}>
                        <div className="row between" style={{ fontSize: 12, marginBottom: 3 }}>
                          <span className="dim">{COMP_LABEL[key]}</span>
                          <span className="mono">{fmt.n(v)} <span className="faint">→ {fmt.n(k.contributions[key])} pts</span></span>
                        </div>
                        <Meter value={v} color={v >= 80 ? "var(--chart-machine)" : v >= 60 ? "var(--chart-human)" : "var(--critical)"} />
                      </div>
                    ))}
                  </div>
                </div>
              </Card>
              <div className="grid g-2">
                <Kpi label="Experience Recovery" icon={<TrendingUp size={12} />} value={fmt.signed(k.experience_recovery_pct)} unit="%" accent="var(--machine)"
                     deltaLabel={k.experience_recovery_pct === null ? "needs remediation records (Module 8)" : "DEX after vs before remediation"}
                     hint="(after − before) / before, remediated cohort" />
                <Kpi label="Business impact" icon={<DollarSign size={12} />} value={fmt.usd(k.business_impact_savings_usd)} accent="var(--machine)"
                     deltaLabel={k.business_impact_savings_usd === null ? "needs remediation records (Module 8)" : "annualised savings from fixes"} />
                <Kpi label="Correlation score" icon={<GitCompareArrows size={12} />} value={fmt.n(k.correlation_score, 2)} accent="var(--human)"
                     deltaLabel={`${k.correlation_strength} · frustration × telemetry r`} />
                <Kpi label="At-risk devices" icon={<ShieldAlert size={12} />} value={k.at_risk_devices} accent="var(--critical)"
                     deltaLabel="proactive remediation candidates" />
              </div>
            </div>

            <div className="grid g-4 mt">
              <Kpi label="Employee Experience Index" icon={<Smile size={12} />} value={fmt.n(k.employee_experience_index)} accent="var(--human)" deltaLabel="100 − weekly frustration burden" />
              <Kpi label="Device Health Score" icon={<HeartPulse size={12} />} value={fmt.n(k.device_health_score)} accent="var(--machine)" deltaLabel="fleet mean, 0-100" />
              <Kpi label="Repeat contact rate" icon={<Repeat size={12} />} value={fmt.pct(k.repeat_contact_rate_pct)} accent="var(--human)" deltaLabel="same device + issue seen earlier in window" hint="Recomputed inside the selected window (drives Remediation Success Score); the service-desk repeat flag is shown on Experience Analytics" />
              <Kpi label="Avg frustration" icon={<AlertTriangle size={12} />} value={fmt.n(k.avg_frustration)} unit="/100" accent="var(--human)" deltaLabel="text + repeat + escalation" />
            </div>

            <div className="grid g-2 mt">
              <ChartCard title="DEX Score trend" sub="rolling 4-week window" table={d.dex_trend}
                         columns={[{ key: "week", label: "Week" }, { key: "dex_score", label: "DEX", num: true }, { key: "eei", label: "EEI", num: true }, { key: "dhs", label: "DHS", num: true }, { key: "rss", label: "RSS", num: true }]}>
                <TrendChart data={d.dex_trend} series={[{ key: "dex_score", name: "DEX Score", color: "var(--chart-machine)" }]} />
              </ChartCard>
              <ChartCard title="Frustration trend" sub="average frustration score of tickets raised each week" table={d.frustration_trend}
                         columns={[{ key: "week", label: "Week" }, { key: "tickets", label: "Tickets", num: true }, { key: "avg_frustration", label: "Avg frustration", num: true }, { key: "repeat_rate_pct", label: "Repeat %", num: true }]}>
                <TrendChart data={d.frustration_trend} series={[{ key: "avg_frustration", name: "Avg frustration", color: "var(--chart-human)" }]} yDomain={[0, 100]} />
              </ChartCard>
            </div>

            <div className="grid g-2 mt">
              <Card title="Top telemetry drivers" sub="ranked by excess tickets on breached device-weeks × frustration × repeat share">
                {d.top_telemetry_drivers.map((r: Any, i: number) => {
                  const max = d.top_telemetry_drivers[0].impact_score || 1;
                  return (
                    <div className="rank-row" key={r.signal} title={`${r.excess_tickets} excess tickets · ${r.devices_affected} devices · avg frustration ${r.avg_frustration}`}>
                      <span className="rn">{i + 1}</span><span style={{ fontWeight: 600 }}>{r.label}</span>
                      <div className="bar-track"><div className="bar-fill" style={{ width: `${(100 * r.impact_score) / max}%`, opacity: i === 0 ? 1 : 0.55 }} /></div>
                      <span className="rc">{fmt.n(r.impact_score, 0)}</span>
                    </div>
                  );
                })}
                <div className="note mt">Impact = excess tickets vs the healthy-week rate, weighted by the frustration they carry. <Link to="/correlation">Full correlation analysis →</Link></div>
              </Card>
              <Card title="Top experience drivers" sub="language that drives frustration (lexicon weight × tickets)">
                {d.top_experience_drivers.phrases.map((p: Any, i: number) => {
                  const max = d.top_experience_drivers.phrases[0].contribution || 1;
                  return (
                    <div className="rank-row" key={p.phrase} title={`${p.tickets} tickets · avg frustration ${p.avg_frustration}`}>
                      <span className="rn">{i + 1}</span><span style={{ fontWeight: 600 }}>“{p.phrase}”</span>
                      <div className="bar-track"><div className="bar-fill" style={{ width: `${(100 * p.contribution) / max}%`, background: "var(--chart-human)", opacity: i === 0 ? 1 : 0.55 }} /></div>
                      <span className="rc">{p.tickets}</span>
                    </div>
                  );
                })}
                <div className="row mt" style={{ gap: 18 }}>
                  {d.top_experience_drivers.behaviours.map((b: Any) => (
                    <span key={b.driver} className="note"><b className="dim">{b.driver}:</b> {fmt.n(b.avg_frustration)} vs {fmt.n(b.vs_first_contact)} otherwise</span>
                  ))}
                </div>
              </Card>
            </div>

            <div className="grid g-split mt">
              <Card title="Executive insights" sub="generated from the analytics — each finding traces to a metric">
                <div className="grid" style={{ gap: 10 }}>
                  {d.insights.map((ins: Any, i: number) => (
                    <div key={i} className="insight" style={{ ["--accent" as string]: INSIGHT_ACCENT[ins.severity] }}>
                      <h4>{ins.severity === "positive" ? <CheckCircle2 size={14} className="machine" /> : ins.severity === "high" ? <AlertTriangle size={14} className="crit" /> : <Info size={14} className="dim" />}{ins.title}</h4>
                      <p>{ins.detail}</p>
                    </div>
                  ))}
                </div>
              </Card>
              <ChartCard title="DEX Score by department" sub="lowest first — where to invest" table={d.departments}
                         columns={[{ key: "group", label: "Department" }, { key: "dex_score", label: "DEX", num: true }, { key: "eei", label: "EEI", num: true }, { key: "tickets", label: "Tickets", num: true }]}>
                <Bars data={d.departments} x="group" y="dex_score" name="DEX Score" horizontal height={260} labels
                      emphasize={(_, i) => i === 0} yFmt={(v) => fmt.n(v)} />
              </ChartCard>
            </div>

            <div className="grid g-2 mt">
              <Card title="Before vs after remediation" sub={`${d.outcome_summary.cases} remediation cases in scope`}
                    right={<Link to="/outcomes" className="btn btn-ghost btn-sm">Outcome report →</Link>}>
                {d.outcome_summary.cases ? (
                  <dl className="kv">
                    <dt>DEX Score</dt><dd><PrePost pre={d.outcome_summary.dex_before} post={d.outcome_summary.dex_after} lowerIsBetter={false} /></dd>
                    <dt>Frustration</dt><dd><PrePost pre={d.outcome_summary.aggregate.frustration.pre} post={d.outcome_summary.aggregate.frustration.post} /></dd>
                    <dt>Repeat contact</dt><dd><PrePost pre={d.outcome_summary.aggregate.repeat_rate.pre} post={d.outcome_summary.aggregate.repeat_rate.post} suffix="%" /></dd>
                    <dt>Tickets / week</dt><dd><PrePost pre={d.outcome_summary.aggregate.ticket_rate.pre} post={d.outcome_summary.aggregate.ticket_rate.post} d={2} /></dd>
                    <dt>Hours recovered</dt><dd className="mono">{fmt.n(d.outcome_summary.business_impact?.productivity_hours_recovered, 0)} / yr</dd>
                  </dl>
                ) : <div className="empty">No remediations for this scope</div>}
              </Card>
              <Card title="At-risk devices" sub={`highest telemetry severity + frustration burden, weeks ${d.at_risk.window_weeks}`}>
                <DataTable rows={d.at_risk.devices} onRow={(r: Any) => nav(`/devices/${r.device_id}`)} columns={[
                  { key: "device_id", label: "Device", render: (r: Any) => <b>{r.device_id}</b> },
                  { key: "employee_name", label: "Employee", render: (r: Any) => <span>{r.employee_name}<div className="faint" style={{ fontSize: 11 }}>{r.department}</div></span> },
                  { key: "primary_issue", label: "Primary issue" },
                  { key: "tickets_last_4w", label: "Tickets", num: true },
                  { key: "risk_score", label: "Risk", num: true },
                ]} max={6} />
              </Card>
            </div>
            <footer className="foot">DEX Sentinel · fully simulated dataset with seeded, verifiable correlations · no employee data used</footer>
          </>
        );
      }}
    </QueryState>
  );
}
