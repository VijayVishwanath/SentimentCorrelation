import { Download } from "lucide-react";
import { AnalystOnly } from "../components/analyst";
import { Link, useSearchParams } from "react-router-dom";
import { Any, downloadFile, fmt, qsOf, useApi } from "../api";
import { PrePostBars } from "../components/charts";
import { Card, ChartCard, DataTable, Kpi, PrePost, QueryState } from "../components/ui";


function downloadCsv(category: string) {
  return downloadFile(`/v1/outcomes/export.csv${qsOf({ category })}`, "dex_sentinel_outcomes.csv");
}

/** Naive before/after split into what similar never-fixed devices did anyway and what the fix caused. */
function Split({ x, d = 2 }: { x: Any; d?: number }) {
  const naive = Math.abs(x.naive_change), cause = Math.max(0, -x.uplift), anyway = Math.max(0, naive - cause);
  const total = Math.max(naive, cause) || 1;
  return (
    <div>
      <div style={{ display: "flex", height: 14, borderRadius: 4, overflow: "hidden", background: "var(--panel-3)", gap: 2 }} role="img"
           aria-label={`naive ${fmt.n(x.naive_change, d)}; would have happened anyway ${fmt.n(-anyway, d)}; caused by the fix ${fmt.n(x.uplift, d)}`}>
        <div style={{ width: `${(100 * cause) / total}%`, background: "var(--chart-machine)" }} />
        <div style={{ width: `${(100 * anyway) / total}%`, background: "var(--chart-neutral)" }} />
      </div>
      <div className="row between mono" style={{ fontSize: 11, marginTop: 4 }}>
        <span><b className="machine">{fmt.n(x.uplift, d)}</b> caused by the fix <span className="faint">[{fmt.n(x.ci95[0], d)}, {fmt.n(x.ci95[1], d)}]</span></span>
        <span className="faint">{fmt.n(x.control_change, d)} would have happened anyway</span>
      </div>
    </div>
  );
}

function CausalCard({ category }: { category: string }) {
  const q = useApi(`/v1/outcomes/uplift${qsOf({ category })}`);
  const u: Any = q.data;
  if (!u) return null;
  if (!u.available) return <Card className="mt" title="Causal uplift"><div className="note">{u.reason}</div></Card>;
  const o = u.overall;
  return (
    <Card className="mt" title="Did the fix cause it? Naive before/after vs causal uplift"
          sub={`${o.cases} fixed devices, each against its ${u.controls_per_case} closest never-fixed look-alikes (${fmt.i(u.control_pool)} in the pool)`}
          right={<span className="badge" style={{ color: "var(--machine)", borderColor: "var(--machine)" }}>difference-in-differences</span>}>
      <div className="grid g-2">
        {(["tickets", "frustration"] as const).map((k) => (
          <div key={k}>
            <div className="row between" style={{ marginBottom: 6 }}>
              <b style={{ fontSize: 13 }}>{k === "tickets" ? "Tickets per device-week" : "Frustration burden per device-week"}</b>
              <span className="note">naive {fmt.n(o[k].naive_change, 2)} · {fmt.pct(o[k].causal_share_pct, 0)} is causal</span>
            </div>
            <Split x={o[k]} d={k === "tickets" ? 2 : 1} />
          </div>
        ))}
      </div>
      <div className="row mt" style={{ gap: 14, fontSize: 11.5, color: "var(--text-dim)" }}>
        <span><i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: "var(--chart-machine)", marginRight: 6 }} />Caused by the fix</span>
        <span><i style={{ display: "inline-block", width: 9, height: 9, borderRadius: 2, background: "var(--chart-neutral)", marginRight: 6 }} />Would have happened anyway (matched unfixed devices)</span>
      </div>
      <AnalystOnly>
      <DataTable rows={u.by_category.map((c: Any) => ({ category: c.category, cases: c.cases, t_naive: c.tickets.naive_change, t_uplift: c.tickets.uplift,
        t_ci: `${fmt.n(c.tickets.ci95[0], 2)} to ${fmt.n(c.tickets.ci95[1], 2)}`, f_uplift: c.frustration.uplift, sig: c.tickets.significant && c.frustration.significant }))} columns={[
        { key: "category", label: "Root cause", render: (r: Any) => <b>{r.category}</b> },
        { key: "cases", label: "Fixes", num: true },
        { key: "t_naive", label: "Tickets naive", num: true, render: (r: Any) => fmt.n(r.t_naive, 2) },
        { key: "t_uplift", label: "Tickets causal", num: true, render: (r: Any) => <b className="machine">{fmt.n(r.t_uplift, 2)}</b> },
        { key: "t_ci", label: "95% interval" },
        { key: "f_uplift", label: "Frustration causal", num: true, render: (r: Any) => fmt.n(r.f_uplift, 1) },
        { key: "sig", label: "Significant", render: (r: Any) => (r.sig ? "yes" : "not yet") },
      ]} />
      <div className="note mt">{u.method} Pre-fix ticket rate: fixed {fmt.n(o.balance.pre_tickets_treated, 2)} vs matched {fmt.n(o.balance.pre_tickets_control, 2)} per week.
        Annual Benefits counts only the causal tickets.</div>
      </AnalystOnly>
    </Card>
  );
}

export default function Outcomes() {
  const [params, setParams] = useSearchParams();  // ?category= so "Fix now" can deep-link to the proof for that fix type
  const category = params.get("category") || "";
  const setCategory = (c: string) => { const p = new URLSearchParams(params); if (c) p.set("category", c); else p.delete("category"); setParams(p, { replace: true }); };
  const all = useApi("/v1/outcomes");
  const q = useApi(`/v1/outcomes${qsOf({ category })}`);
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Outcome Reporting</div>
          <h2>Did the fix actually improve the experience?</h2>
          <p>Before vs after every fix, and how much of the change the fix itself caused.</p>
        </div>
        <div className="row">
          <select value={category} onChange={(e) => setCategory(e.target.value)} aria-label="Root cause">
            <option value="">All root causes</option>{(all.data?.by_category || []).map((c: Any) => <option key={c.category}>{c.category}</option>)}
          </select>
          <button className="btn btn-ghost" onClick={() => downloadCsv(category)}><Download size={14} />Export CSV</button>
        </div>
      </div>
      <QueryState q={q} label="Measuring before vs after for every fix…">
        {(d: Any) => !d.cases ? <div className="empty">No remediation cases</div> : (
          <>
            <div className="grid g-2">
              <Kpi label="Experience Recovery %" value={fmt.signed(d.dex.experience_recovery_pct)} unit="%" accent="var(--machine)"
                   deltaLabel={`DEX ${fmt.n(d.dex.before.dex_score)} → ${fmt.n(d.dex.after.dex_score)} (remediated cohort)`} delta={d.dex.experience_recovery_pct} />
              <Kpi label="Cases improved" value={`${d.improved_cases}/${d.cases}`} accent="var(--machine)" deltaLabel="repeat rate and ticket rate both down or flat" />
            </div>
            <div className="grid g-4 mt">
              {([["frustration", "Avg frustration score", 1, ""], ["repeat_rate", "Repeat-contact rate", 1, "%"], ["ticket_rate", "Tickets / week", 2, ""], ["boot", "Avg boot (s)", 1, ""]] as const).map(([key, label, dd, suf]) => {
                const a = d.aggregate[key];
                return <Kpi key={key} label={label} value={<PrePost pre={a.pre} post={a.post} d={dd} suffix={suf} />} accent="var(--human)"
                            deltaLabel={`${a.improved ? "improved" : "worsened"} ${fmt.n(a.change_pct, 0)}%`} delta={-a.change} goodWhen="up" />;
              })}
            </div>
            <CausalCard category={category} />

            <div className="mt"><ChartCard title="DEX Score before vs after, by root cause" sub="same devices, pre-fix weeks vs post-fix weeks"
                         table={all.data?.by_category || []} columns={[{ key: "category", label: "Root cause" }, { key: "cases", label: "Cases", num: true }, { key: "dex_before", label: "DEX before", num: true }, { key: "dex_after", label: "DEX after", num: true }, { key: "recovery_pct", label: "Recovery %", num: true }]}>
                {all.data && <PrePostBars data={all.data.by_category.map((c: Any) => ({ name: c.category, pre: c.dex_before, post: c.dex_after }))} />}
              </ChartCard></div>
            <div className="note mt">Dollar value of these outcomes (causal share only) is on <Link to="/value?tab=benefits">Annual Benefits</Link>.</div>

            <Card className="mt" title="By root cause" sub="aggregate across cases — the statistically meaningful read">
              <DataTable rows={d.by_category} pageSize={5} sortable columns={[
                { key: "category", label: "Root cause", filter: "select", render: (r: Any) => <b>{r.category}</b> },
                { key: "cases", label: "Cases", num: true, filter: "num" },
                { key: "action", label: "Action taken", filter: "text" },
                { key: "frustration", label: "Frustration", value: (r: Any) => r.frustration.change_pct, render: (r: Any) => <PrePost pre={r.frustration.pre} post={r.frustration.post} /> },
                { key: "repeat_rate", label: "Repeat %", value: (r: Any) => r.repeat_rate.change_pct, render: (r: Any) => <PrePost pre={r.repeat_rate.pre} post={r.repeat_rate.post} suffix="%" /> },
                { key: "ticket_rate", label: "Tickets/wk", value: (r: Any) => r.ticket_rate.change_pct, render: (r: Any) => <PrePost pre={r.ticket_rate.pre} post={r.ticket_rate.post} d={2} /> },
                { key: "dex", label: "DEX", value: (r: Any) => r.dex_after, render: (r: Any) => <PrePost pre={r.dex_before} post={r.dex_after} lowerIsBetter={false} /> },
                { key: "recovery_pct", label: "Recovery", num: true, filter: "num", render: (r: Any) => <span className="good">{fmt.signed(r.recovery_pct)}%</span> },
              ]} />
            </Card>

            <AnalystOnly>
            <Card className="mt" title="Remediation case register" sub={`${d.cases} cases · n = post-fix tickets behind each post-fix average`}>
              <DataTable rows={d.rows} pageSize={5} sortable columns={[
                { key: "device_id", label: "Device", filter: "text", value: (r: Any) => `${r.device_id} ${r.employee_name}`,
                  render: (r: Any) => <span><Link to={`/devices/${r.device_id}`} onClick={(e) => e.stopPropagation()}><b>{r.device_id}</b></Link><div className="faint" style={{ fontSize: 11 }}>{r.employee_name}</div></span> },
                { key: "root_cause_category", label: "Cause", filter: "select" },
                { key: "department", label: "Dept", filter: "select" },
                { key: "week_of_remediation", label: "Week", num: true, filter: "num", render: (r: Any) => `W${r.week_of_remediation}` },
                { key: "action_taken", label: "Action taken", filter: "text", render: (r: Any) => <span className="dim" style={{ fontSize: 12 }}>{r.action_taken}</span> },
                { key: "f", label: "Frustration", value: (r: Any) => r.frustration_post, filter: "num",
                  render: (r: Any) => <span><PrePost pre={r.frustration_pre} post={r.frustration_post} /> <span className="faint mono" style={{ fontSize: 10 }}>(n={r.post_ticket_count})</span></span> },
                { key: "r", label: "Repeat %", value: (r: Any) => r.repeat_rate_post, render: (r: Any) => <PrePost pre={r.repeat_rate_pre} post={r.repeat_rate_post} suffix="%" /> },
                { key: "t", label: "Tickets/wk", value: (r: Any) => r.ticket_rate_post, render: (r: Any) => <PrePost pre={r.ticket_rate_pre} post={r.ticket_rate_post} d={2} /> },
                { key: "dex", label: "DEX", value: (r: Any) => r.dex_after, filter: "num", render: (r: Any) => r.dex_before !== null ? <PrePost pre={r.dex_before} post={r.dex_after} lowerIsBetter={false} /> : "—" },
                { key: "recovery_pct", label: "Recovery", num: true, filter: "num", render: (r: Any) => r.recovery_pct !== null ? `${fmt.signed(r.recovery_pct)}%` : "—" },
              ]} />
              <div className="note mt">{d.notes.map((n: string, i: number) => <p key={i} style={{ margin: "0 0 4px" }}>{n}</p>)}</div>
            </Card>
            </AnalystOnly>
          </>
        )}
      </QueryState>
    </>
  );
}
