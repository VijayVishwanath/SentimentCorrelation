import { Download } from "lucide-react";
import { useState } from "react";
import { Link } from "react-router-dom";
import { Any, downloadFile, fmt, qsOf, useApi } from "../api";
import { PrePostBars } from "../components/charts";
import { Card, ChartCard, DataTable, Kpi, PrePost, QueryState } from "../components/ui";


function downloadCsv(category: string) {
  return downloadFile(`/v1/outcomes/export.csv${qsOf({ category })}`, "dex_sentinel_outcomes.csv");
}

export default function Outcomes() {
  const [category, setCategory] = useState("");
  const all = useApi("/v1/outcomes");
  const q = useApi(`/v1/outcomes${qsOf({ category })}`);
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Module 6 · Outcome Reporting</div>
          <h2>Did the fix actually improve the experience?</h2>
          <p>Before vs after every remediation: frustration, repeat-contact rate, ticket volume and DEX Score. Tickets close on
            verified recovery, not on silence.</p>
        </div>
        <div className="row">
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Root cause">
            <option value="">All root causes</option>{(all.data?.by_category || []).map((c: Any) => <option key={c.category}>{c.category}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={() => downloadCsv(category)}><Download size={14} />Export CSV</button>
        </div>
      </div>
      <QueryState q={q}>
        {(d: Any) => !d.cases ? <div className="empty">No remediation cases</div> : (
          <>
            <div className="grid g-3">
              <Kpi label="Experience Recovery %" value={fmt.signed(d.dex.experience_recovery_pct)} unit="%" accent="var(--machine)"
                   deltaLabel={`DEX ${fmt.n(d.dex.before.dex_score)} → ${fmt.n(d.dex.after.dex_score)} (remediated cohort)`} delta={d.dex.experience_recovery_pct} />
              <Kpi label="Cases improved" value={`${d.improved_cases}/${d.cases}`} accent="var(--machine)" deltaLabel="repeat rate and ticket rate both down or flat" />
              <Kpi label="Annualised value" value={fmt.usd(d.business_impact.total_annual_savings_usd)} accent="var(--machine)"
                   deltaLabel={`${fmt.n(d.business_impact.annual_tickets_avoided, 0)} tickets avoided · ${fmt.n(d.business_impact.productivity_hours_recovered, 0)} h recovered`} />
            </div>
            <div className="grid g-4 mt">
              {([["frustration", "Avg frustration score", 1, ""], ["repeat_rate", "Repeat-contact rate", 1, "%"], ["ticket_rate", "Tickets / week", 2, ""], ["boot", "Avg boot (s)", 1, ""]] as const).map(([key, label, dd, suf]) => {
                const a = d.aggregate[key];
                return <Kpi key={key} label={label} value={<PrePost pre={a.pre} post={a.post} d={dd} suffix={suf} />} accent="var(--human)"
                            deltaLabel={`${a.improved ? "improved" : "worsened"} ${fmt.n(a.change_pct, 0)}%`} delta={-a.change} goodWhen="up" />;
              })}
            </div>

            <div className="grid g-split mt">
              <ChartCard title="DEX Score before vs after, by root cause" sub="same devices, pre-fix weeks vs post-fix weeks"
                         table={all.data?.by_category || []} columns={[{ key: "category", label: "Root cause" }, { key: "cases", label: "Cases", num: true }, { key: "dex_before", label: "DEX before", num: true }, { key: "dex_after", label: "DEX after", num: true }, { key: "recovery_pct", label: "Recovery %", num: true }]}>
                {all.data && <PrePostBars data={all.data.by_category.map((c: Any) => ({ name: c.category, pre: c.dex_before, post: c.dex_after }))} />}
              </ChartCard>
              <Card title="Business impact" sub="annualised from the remediated cohort" right={<Link to="/settings" className="note">Edit assumptions →</Link>}>
                <dl className="kv">
                  <dt>Tickets avoided</dt><dd className="mono">{fmt.n(d.business_impact.annual_tickets_avoided, 0)} / yr</dd>
                  <dt>Support savings</dt><dd className="mono">{fmt.usd(d.business_impact.support_cost_savings_usd)}</dd>
                  <dt>Hours recovered</dt><dd className="mono">{fmt.n(d.business_impact.productivity_hours_recovered, 0)} h</dd>
                  <dt>Productivity value</dt><dd className="mono">{fmt.usd(d.business_impact.productivity_savings_usd)}</dd>
                  <dt>Total</dt><dd className="mono" style={{ fontWeight: 700 }}>{fmt.usd(d.business_impact.total_annual_savings_usd)}</dd>
                  <dt>Per device</dt><dd className="mono">{fmt.usd(d.business_impact.savings_per_remediated_device_usd)}</dd>
                </dl>
                <div className="note mt">Assumptions: ${d.business_impact.assumptions.cost_per_ticket_usd}/ticket, ${d.business_impact.assumptions.hourly_employee_cost_usd}/h,
                  {" "}{d.business_impact.assumptions.productivity_loss_factor * 100}% productivity loss during {d.business_impact.assumptions.avg_resolution_hours} h avg resolution.</div>
              </Card>
            </div>

            <Card className="mt" title="By root cause" sub="aggregate across cases — the statistically meaningful read">
              <DataTable rows={d.by_category} columns={[
                { key: "category", label: "Root cause", render: (r: Any) => <b>{r.category}</b> },
                { key: "cases", label: "Cases", num: true },
                { key: "action", label: "Action taken" },
                { key: "frustration", label: "Frustration", render: (r: Any) => <PrePost pre={r.frustration.pre} post={r.frustration.post} /> },
                { key: "repeat_rate", label: "Repeat %", render: (r: Any) => <PrePost pre={r.repeat_rate.pre} post={r.repeat_rate.post} suffix="%" /> },
                { key: "ticket_rate", label: "Tickets/wk", render: (r: Any) => <PrePost pre={r.ticket_rate.pre} post={r.ticket_rate.post} d={2} /> },
                { key: "dex", label: "DEX", render: (r: Any) => <PrePost pre={r.dex_before} post={r.dex_after} lowerIsBetter={false} /> },
                { key: "recovery_pct", label: "Recovery", num: true, render: (r: Any) => <span className="good">{fmt.signed(r.recovery_pct)}%</span> },
              ]} />
            </Card>

            <Card className="mt" title="Remediation case register" sub={`${d.cases} cases · n = post-fix tickets behind each post-fix average`}>
              <DataTable rows={d.rows} columns={[
                { key: "device_id", label: "Device / cause", render: (r: Any) => <span><Link to={`/devices/${r.device_id}`}><b>{r.device_id}</b></Link> · {r.root_cause_category}<div className="faint" style={{ fontSize: 11 }}>{r.employee_name} · {r.department} · W{r.week_of_remediation}</div></span> },
                { key: "action_taken", label: "Action taken", render: (r: Any) => <span className="dim" style={{ fontSize: 12 }}>{r.action_taken}</span> },
                { key: "f", label: "Frustration", render: (r: Any) => <span><PrePost pre={r.frustration_pre} post={r.frustration_post} /> <span className="faint mono" style={{ fontSize: 10 }}>(n={r.post_ticket_count})</span></span> },
                { key: "r", label: "Repeat %", render: (r: Any) => <PrePost pre={r.repeat_rate_pre} post={r.repeat_rate_post} suffix="%" /> },
                { key: "t", label: "Tickets/wk", render: (r: Any) => <PrePost pre={r.ticket_rate_pre} post={r.ticket_rate_post} d={2} /> },
                { key: "dex", label: "DEX", render: (r: Any) => r.dex_before !== null ? <PrePost pre={r.dex_before} post={r.dex_after} lowerIsBetter={false} /> : "—" },
                { key: "recovery_pct", label: "Recovery", num: true, render: (r: Any) => r.recovery_pct !== null ? `${fmt.signed(r.recovery_pct)}%` : "—" },
              ]} />
              <div className="note mt">{d.notes.map((n: string, i: number) => <p key={i} style={{ margin: "0 0 4px" }}>{n}</p>)}</div>
            </Card>
          </>
        )}
      </QueryState>
    </>
  );
}
