import { ArrowRight, BellRing, Flame, Gauge, Target, Wallet } from "lucide-react";
import { Link, useNavigate } from "react-router-dom";
import { Any, bandColor, fmt, useApi, useFilters } from "../api";
import { TrendChart } from "../components/charts";
import { Card, ChartCard, DataTable, Kpi, MoneyChip, QueryState } from "../components/ui";
import { FixNowButton } from "../components/FixNow";
import { RiskBadge } from "./Proactive";

const usdShort = fmt.usdShort;

/** Where DEX is today and where the top fixes take it, on one 0–100 scale. */
function Roadmap({ from, to }: { from: number; to: number }) {
  return (
    <div style={{ position: "relative", height: 14, borderRadius: 7, background: "var(--panel-3)", margin: "18px 0 8px" }}
         role="img" aria-label={`DEX ${from} today, ${to} projected`}>
      <div style={{ position: "absolute", inset: 0, width: `${from}%`, borderRadius: 7, background: "var(--chart-machine)" }} />
      <div style={{ position: "absolute", top: 0, bottom: 0, left: `${from}%`, width: `${Math.max(0, to - from)}%`,
                    background: "repeating-linear-gradient(45deg, var(--chart-machine) 0 4px, transparent 4px 8px)", opacity: 0.7 }} />
    </div>
  );
}

function ActionCard({ a, rank, department }: { a: Any; rank: number; department?: string }) {
  return (
    <div className="card" style={{ display: "flex", flexDirection: "column", gap: 10, borderTop: `3px solid ${rank === 1 ? "var(--critical)" : "var(--human)"}` }}>
      <div className="row between">
        <span className="eyebrow" style={{ margin: 0 }}>#{rank} · {a.category}</span>
        <span className="chip" title="projected fleet DEX gain">+{fmt.n(a.dex_gain_pts)} DEX</span>
      </div>
      <div>
        <div style={{ fontSize: 15, fontWeight: 800 }}>{a.problem}</div>
        <div className="faint" style={{ fontSize: 12 }}>{fmt.i(a.devices_affected)} devices · {fmt.i(a.excess_tickets)} extra tickets · frustration {fmt.n(a.avg_frustration, 0)}</div>
      </div>
      <div style={{ fontSize: 13 }}><b>Fix:</b> {a.action}</div>
      <div className="row" style={{ gap: 16 }}>
        <div><div style={{ fontSize: 20, fontWeight: 800 }} className="good">{usdShort(a.savings_per_year_usd)}</div><div className="faint" style={{ fontSize: 11 }}>saved / year<MoneyChip kind="planned" /></div></div>
        <div><div style={{ fontSize: 20, fontWeight: 800 }}>{fmt.i(a.tickets_avoided_per_year)}</div><div className="faint" style={{ fontSize: 11 }}>tickets avoided / yr</div></div>
        <div><div style={{ fontSize: 20, fontWeight: 800 }}>−{fmt.n(a.ticket_reduction_pct, 0)}%</div>
          <div className="faint" style={{ fontSize: 11 }} title={`caused by ${a.evidence_cases} past fixes of this type, beyond what matched unfixed devices did anyway`}>tickets, causal</div></div>
      </div>
      <div style={{ marginTop: "auto" }}>
        <FixNowButton target={{ category: a.category, signal: a.signal, department }} label={`Fix now · ${fmt.i(a.devices_affected)} devices`} />
      </div>
    </div>
  );
}

export default function CommandCenter() {
  const { qs, filters } = useFilters();
  const q = useApi(`/v1/dashboard/command-center${qs}`);
  const nav = useNavigate();
  return (
    <QueryState q={q} label="Building the command center…">
      {(d: Any) => {
        const h = d.headline;
        const top = h.top_problem;
        return (
          <>
            <div className="page-head">
              <div>
                <div className="eyebrow">Command Center</div>
                {/* the value in one sentence, from live numbers */}
                <h2>{h.predicted.available && d.roadmap.levers
                  ? <>{fmt.i(h.predicted.frustrated_tickets)} frustrated tickets are coming next week. Fixing {d.roadmap.levers} things
                      saves <span className="good">{usdShort(d.roadmap.savings_per_year_usd)}</span> a year.</>
                  : "Employee experience: where we are, and what to fix next"}</h2>
                <p>Where the experience is, and what to fix next · {fmt.i(d.scope.devices)} devices · {fmt.i(d.scope.tickets)} tickets ·
                  weeks {d.scope.weeks[0]}–{d.scope.weeks[d.scope.weeks.length - 1]}</p>
              </div>
            </div>

            <div className="grid g-4">
              <Link to={`/evidence?tab=dex-score${qs.replace("?", "&")}`} style={{ color: "inherit", textDecoration: "none" }} title="Open the DEX Score breakdown by component and cohort">
                <Kpi label="DEX Score" icon={<Gauge size={12} />} value={fmt.n(h.dex_score)} unit="/100" accent={bandColor(h.dex_band)}
                     delta={h.dex_delta} deltaLabel={`${h.dex_band} · ${fmt.signed(h.dex_delta)} pts · by department →`}
                     hint="0.35·Experience + 0.25·Device health + 0.20·Remediation success + 0.10·Resolution + 0.10·Sentiment trend" />
              </Link>
              <Kpi label={h.predicted.available ? `Predicted · week ${h.predicted.week}` : "Predicted next week"} icon={<BellRing size={12} />}
                   value={h.predicted.available ? fmt.n(h.predicted.frustrated_tickets, 0) : "—"} accent="var(--human)"
                   deltaLabel={h.predicted.available ? "frustrated tickets expected" : "needs more history"}
                   hint="LightGBM forecast of High/Critical frustration tickets next week" />
              <Link to={`/value?tab=benefits${qs.replace("?", "&")}`} style={{ color: "inherit", textDecoration: "none" }} title="Open the Annual Benefits breakdown">
                <Kpi label="Annual benefits" tag={<MoneyChip kind="realised" />} icon={<Wallet size={12} />} value={usdShort(h.benefits.total_usd)} unit="/yr" accent="var(--machine)"
                     deltaLabel={`tickets ${usdShort(h.benefits.components[0].value_usd)} · productivity ${usdShort(h.benefits.components[1].value_usd)} · details →`}
                     hint="Ticket cost + productivity recovery + license + hardware refresh savings (Annual Benefits page)" />
              </Link>
              <Kpi label="#1 problem" icon={<Flame size={12} />} value={top ? top.problem : "—"} accent="var(--critical)"
                   deltaLabel={top ? `${fmt.i(top.devices_affected)} devices · ${fmt.i(top.excess_tickets)} extra tickets` : ""} />
            </div>

            <div className="grid g-split mt">
              <ChartCard title="Experience trend" sub="DEX Score vs ticket frustration, weekly" table={d.trend}
                         columns={[{ key: "week", label: "Week" }, { key: "dex_score", label: "DEX", num: true }, { key: "avg_frustration", label: "Frustration", num: true }]}>
                <TrendChart data={d.trend} height={200} yDomain={[0, 100]}
                            series={[{ key: "dex_score", name: "DEX Score", color: "var(--chart-machine)" }, { key: "avg_frustration", name: "Avg frustration", color: "var(--chart-human)" }]} />
              </ChartCard>
              <Card title="The plan" sub={`if the top ${d.roadmap.levers} fixes below are rolled out`}>
                <div className="row" style={{ alignItems: "baseline", gap: 12 }}>
                  <span style={{ fontSize: 44, fontWeight: 800, lineHeight: 1 }}>{fmt.n(d.roadmap.from)}</span>
                  <Target size={20} className="faint" />
                  <span style={{ fontSize: 44, fontWeight: 800, lineHeight: 1 }} className="good">{fmt.n(d.roadmap.to)}</span>
                  <span className="faint">DEX</span>
                </div>
                <Roadmap from={d.roadmap.from} to={d.roadmap.to} />
                <div className="row" style={{ gap: 22, marginTop: 10 }}>
                  <div><div style={{ fontSize: 22, fontWeight: 800 }} className="good">{usdShort(d.roadmap.savings_per_year_usd)}</div><div className="faint" style={{ fontSize: 11 }}>saved per year<MoneyChip kind="planned" /></div></div>
                  <div><div style={{ fontSize: 22, fontWeight: 800 }}>{fmt.i(d.roadmap.tickets_avoided_per_year)}</div><div className="faint" style={{ fontSize: 11 }}>tickets avoided per year</div></div>
                </div>
                <div className="note mt" title={`Per fix: causal ticket reduction of past remediations of that type (difference-in-differences vs matched never-fixed devices) × extra tickets it causes today; $${d.cost_per_ticket_usd} per ticket incl. lost productivity. DEX gain = observed before/after DEX change × share of fleet affected.`}>
                  Projected from past fixes of the same type · hover for method</div>
              </Card>
            </div>

            <h3 className="mt-lg" style={{ fontSize: 15, margin: "22px 0 10px" }}>Top 3 actions to raise DEX</h3>
            <div className="grid g-3">
              {d.actions.slice(0, 3).map((a: Any, i: number) => <ActionCard key={a.category} a={a} rank={i + 1} department={filters.department} />)}
            </div>

            <div className="mt">
              <Card title="Who is at risk next week" sub="highest predicted risk · click for Device 360"
                    right={<Link to="/proactive" className="btn btn-ghost btn-sm">Full watchlist <ArrowRight size={12} /></Link>}>
                <DataTable rows={d.watchlist} onRow={(r: Any) => nav(`/devices/${r.device_id}`)} columns={[
                  { key: "employee_name", label: "Employee", render: (r: Any) => <span><b>{r.employee_name}</b><div className="faint mono" style={{ fontSize: 11 }}>{r.device_id} · {r.department}</div></span> },
                  { key: "band", label: "Risk", render: (r: Any) => <span className="row" style={{ gap: 6 }}><RiskBadge band={r.band} /><span className="mono" style={{ fontSize: 12 }}>{fmt.pct(r.risk_pct, 0)}</span></span> },
                  { key: "action", label: "Recommended fix", render: (r: Any) => <span style={{ fontSize: 12 }}>{r.action}</span> },
                  { key: "fix", label: "", render: (r: Any) => r.fix_applied ? <span className="chip" title="The runbook ran; the model updates once post-fix telemetry arrives">fix applied</span> : r.category
                    ? <FixNowButton small label="Fix" target={{ category: r.category, deviceIds: [r.device_id] }} /> : null },
                ]} />
              </Card>
            </div>
            <footer className="foot">Simulated dataset · every number traces to the analysis pages under Evidence</footer>
          </>
        );
      }}
    </QueryState>
  );
}
