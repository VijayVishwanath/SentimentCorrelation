import { useEffect, useState } from "react";
import { Bar, CartesianGrid, Cell, ComposedChart, Line, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { Any, fmt, qsOf, useApi, useFilters } from "../api";
import { FixNowButton } from "../components/FixNow";
import { Card, MoneyChip, QueryState } from "../components/ui";

// Priority Score parts, in stack order (palette validated for both themes)
const PARTS: { key: string; label: string; color: string }[] = [
  { key: "productivity", label: "Productivity", color: "var(--chart-machine)" },
  { key: "cost", label: "Cost", color: "var(--chart-blue)" },
  { key: "employee", label: "Employee", color: "var(--chart-human)" },
  { key: "risk", label: "Risk", color: "var(--chart-magenta)" },
];
// KB article -> the telemetry signal its runbook targets (mirrors forecast.SIGNAL_FIX), so "Fix" aims at this sub-cause
const KB_SIGNAL: Record<string, string> = {
  "KB-PERF-001": "boot", "KB-HW-001": "battery", "KB-HW-002": "disk", "KB-NET-001": "latency", "KB-NET-002": "packet_loss",
  "KB-AUTH-001": "noncompliant", "KB-APP-001": "hangs",
};
const MEASURE_ORDER = ["productivity", "employee", "cost", "incidents"];
const AXIS = { stroke: "var(--chart-axis)", tick: { fill: "var(--text-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }, tickLine: false };
const usd = fmt.usdShort;
const unitFmt = (v: number, unit: string) => (unit === "$" ? usd(v) : `${fmt.i(v)} ${unit}`);
const TREND: Record<string, [string, string]> = { rising: ["▲ rising", "var(--serious)"], falling: ["▼ falling", "var(--good-text)"], steady: ["● steady", "var(--text-dim)"] };

function Swatch({ color, line = false }: { color: string; line?: boolean }) {
  return <i style={{ display: "inline-block", width: line ? 14 : 9, height: line ? 2 : 9, borderRadius: 2, background: color, marginRight: 6, verticalAlign: "middle" }} />;
}

function ParetoTip({ active, payload, unit }: { active?: boolean; payload?: { payload: Any }[]; unit: string }) {
  if (!active || !payload?.length) return null;
  const p = payload[0].payload;
  return (
    <div className="tip">
      <div className="tt">{p.label}<div className="faint" style={{ fontWeight: 400 }}>{p.category}</div></div>
      <div className="tr"><span>Impact</span><b>{unitFmt(p.value, unit)}</b></div>
      <div className="tr"><span>Share</span><b>{fmt.pct(p.share_pct)}</b></div>
      <div className="tr"><span>Cumulative</span><b>{fmt.pct(p.cumulative_pct)}</b></div>
      <div className="tr"><span>Group</span><b>{p.critical ? "Critical few" : "Trivial many"}</b></div>
    </div>
  );
}

function useNarrow(q = "(max-width: 700px)") {
  const [narrow, setNarrow] = useState(() => window.matchMedia(q).matches);
  useEffect(() => { const mq = window.matchMedia(q); const on = () => setNarrow(mq.matches); mq.addEventListener("change", on); return () => mq.removeEventListener("change", on); }, [q]);
  return narrow;
}

function ParetoChart({ m }: { m: Any }) {
  const narrow = useNarrow();  // phone width: rank numbers on the axis, names in the tooltip and the table
  const data = m.curve.map((c: Any, i: number) => ({ ...c, n: i + 1 }));
  const short = (n: number) => { const l = data[n - 1]?.label || ""; return narrow ? `#${n}` : l.length > 20 ? `${l.slice(0, 19)}…` : l; };
  return (
    <ResponsiveContainer width="100%" height={300}>
      <ComposedChart data={data} margin={{ top: 14, right: 16, left: narrow ? -8 : 24, bottom: 0 }} barCategoryGap="18%">
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis dataKey="n" {...AXIS} interval={narrow ? "preserveStartEnd" : 0} angle={narrow ? 0 : -28} textAnchor={narrow ? "middle" : "end"}
               height={narrow ? 24 : 78} tickFormatter={short}
               tick={{ ...AXIS.tick, fontFamily: "var(--font-sans)", fontSize: 10.5 }} />
        <YAxis {...AXIS} axisLine={false} domain={[0, 100]} ticks={[0, 20, 40, 60, 80, 100]} tickFormatter={(v) => `${v}%`} width={48} />
        <Tooltip cursor={{ fill: "var(--panel-3)", opacity: 0.5 }} content={<ParetoTip unit={m.unit} />} />
        <ReferenceLine y={80} stroke="var(--text-faint)" strokeDasharray="4 4"
                       label={{ value: "80% line", fill: "var(--text-faint)", fontSize: 10, position: "insideBottomRight" }} />
        <Bar isAnimationActive={false} dataKey="share_pct" name="Share of impact" radius={[4, 4, 0, 0]} maxBarSize={46}>
          {data.map((c: Any) => <Cell key={c.id} fill={c.critical ? "var(--chart-machine)" : "var(--chart-neutral)"} stroke="var(--panel)" strokeWidth={2} />)}
        </Bar>
        <Line isAnimationActive={false} type="monotone" dataKey="cumulative_pct" name="Cumulative" stroke="var(--chart-human)" strokeWidth={2}
              dot={{ r: 4, strokeWidth: 2, stroke: "var(--panel)", fill: "var(--chart-human)" }} activeDot={{ r: 5, stroke: "var(--panel)", strokeWidth: 2 }} />
      </ComposedChart>
    </ResponsiveContainer>
  );
}

function PriorityBar({ p }: { p: Any }) {
  return (
    <div style={{ minWidth: 150 }}>
      <div className="row between" style={{ gap: 6 }}><b style={{ fontSize: 15 }}>{fmt.n(p.score, 0)}</b><span className="faint mono" style={{ fontSize: 10.5 }}>/ 100</span></div>
      <div style={{ display: "flex", height: 8, borderRadius: 4, overflow: "hidden", background: "var(--panel-3)", gap: 2 }} role="img"
           aria-label={PARTS.map((x) => `${x.label} ${p[x.key]}`).join(", ")}>
        {PARTS.map((x) => p[x.key] > 0 && <div key={x.key} title={`${x.label} Impact: ${p[x.key]} / 25`} style={{ width: `${p[x.key]}%`, background: x.color }} />)}
      </div>
      <div className="mono faint" style={{ fontSize: 10, marginTop: 3 }}>{PARTS.map((x) => p[x.key].toFixed(0)).join(" + ")}</div>
    </div>
  );
}

export default function CriticalFew() {
  const { filters } = useFilters();
  const [measure, setMeasure] = useState("productivity");
  const [showAll, setShowAll] = useState(false);
  const q = useApi(`/v1/roi/critical-few${qsOf(filters)}`);

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Critical Few vs Trivial Many · 80/20</div>
          <h2>The few issues behind most of the pain</h2>
          <p>Every ticket is traced to an issue type (root cause → sub-cause). A handful of them drive most of the lost time, frustration,
            cost and incidents. Fix those first: problem, future risk, solution and ROI for each.</p>
        </div>
      </div>
      <QueryState q={q} label="Tracing every ticket to its issue type…">
        {(d: Any) => !d.available ? <Card><div className="note">No tickets in the current filter: {d.reason}.</div></Card> : (
          <>
            <div className="grid g-4">
              {MEASURE_ORDER.map((k) => {
                const s = d.statements.find((x: Any) => x.measure === k); const m = d.measures[k];
                const on = measure === k;
                return (
                  <button key={k} className="card" onClick={() => setMeasure(k)} aria-pressed={on}
                          style={{ textAlign: "left", cursor: "pointer", font: "inherit", color: "inherit",
                                   borderColor: on ? "var(--machine)" : undefined, boxShadow: on ? "inset 0 0 0 1px var(--machine)" : undefined }}>
                    <div className="eyebrow" style={{ margin: 0 }}>{m.label}</div>
                    <div style={{ fontSize: 30, fontWeight: 800, lineHeight: 1.15 }}>
                      {fmt.pct(s.issue_pct, 0)} <span className="faint" style={{ fontSize: 18 }}>→</span> <span className="machine">{fmt.pct(s.value_pct, 0)}</span>
                    </div>
                    <div style={{ fontSize: 12.5 }}>{s.issue_count} of {s.issues} issue types account for {fmt.pct(s.value_pct, 0)} of {m.phrase}</div>
                    <div className="note">Top 20% ({m.top20_count}) alone: {fmt.pct(m.top20_value_pct, 0)} · total {unitFmt(m.total, m.unit)}</div>
                  </button>
                );
              })}
            </div>

            <div className="grid g-main mt">
              <Card title={`Pareto: ${d.measures[measure].label}`} sub="Issue types, largest first. Bars = each one's share; the line adds them up."
                    right={<div className="row" style={{ gap: 12, fontSize: 11.5, color: "var(--text-dim)" }}>
                      <span><Swatch color="var(--chart-machine)" />Critical few</span><span><Swatch color="var(--chart-neutral)" />Trivial many</span>
                      <span><Swatch color="var(--chart-human)" line />Cumulative</span></div>}>
                <ParetoChart m={d.measures[measure]} />
              </Card>
              <Card title="Fix the critical few" sub={`${d.critical_few.count} of ${d.critical_few.of} issue types hold ${fmt.pct(d.critical_few.impact_pct, 0)} of the combined impact`}>
                <div style={{ fontSize: 40, fontWeight: 800, lineHeight: 1.05 }} className="good">{usd(d.critical_few.annual_preventable_usd)}<span className="faint" style={{ fontSize: 15 }}> / year</span></div>
                <div className="note">preventable, of {usd(d.critical_few.annual_impact_usd)} a year these issues cost today<MoneyChip kind="preventable" /></div>
                <div className="grid g-2 mt" style={{ gap: 10 }}>
                  <div className="card-flat"><div className="eyebrow" style={{ margin: 0 }}>Tickets avoided</div><b style={{ fontSize: 20 }}>{fmt.i(d.critical_few.tickets_avoided_per_year)}</b><span className="faint"> / yr</span></div>
                  <div className="card-flat"><div className="eyebrow" style={{ margin: 0 }}>Hours recovered</div><b style={{ fontSize: 20 }}>{fmt.i(d.critical_few.hours_recovered_per_year)}</b><span className="faint"> / yr</span></div>
                  <div className="card-flat"><div className="eyebrow" style={{ margin: 0 }}>Future risk</div><b style={{ fontSize: 20 }}>{fmt.n(d.critical_few.risk_tickets_next_week)}</b><span className="faint"> frustrated tickets next wk</span></div>
                  <div className="card-flat"><div className="eyebrow" style={{ margin: 0 }}>Trivial many</div><b style={{ fontSize: 20 }}>{d.trivial_many.count}</b><span className="faint"> types · {usd(d.trivial_many.annual_impact_usd)}/yr</span></div>
                </div>
                <div className="note mt">Risk source: {d.risk_source}. {d.tickets} tickets over {d.weeks} weeks in scope.</div>
              </Card>
            </div>

            <Card className="mt" title="Priority ranking: problem → future risk → solution → ROI"
                  sub={<span className="mono" style={{ fontSize: 11.5 }}>{d.formula}</span>}
                  right={<div className="row" style={{ gap: 12, fontSize: 11.5, color: "var(--text-dim)" }}>{PARTS.map((x) => <span key={x.key}><Swatch color={x.color} />{x.label}</span>)}</div>}>
              <div className="table-wrap">
                <table className="t">
                  <thead><tr><th>#</th><th>Issue type</th><th>Priority score</th><th>Problem exists</th><th>Future risk</th><th>Solution recommended</th><th style={{ textAlign: "right" }}>ROI / year</th></tr></thead>
                  <tbody>
                    {d.issues.filter((i: Any) => showAll || i.critical_few).map((i: Any) => {
                      const [tl, tc] = TREND[i.trend.direction];
                      return (
                        <tr key={i.id} style={{ opacity: i.critical_few ? 1 : 0.72 }}>
                          <td className="mono">{i.rank}</td>
                          <td style={{ minWidth: 180 }}><b>{i.sub_cause}</b><div className="faint" style={{ fontSize: 11 }}>{i.category}</div>
                            {i.critical_few && <span className="badge" style={{ color: "var(--machine)", borderColor: "var(--machine)", marginTop: 4 }}>Critical few</span>}</td>
                          <td><PriorityBar p={i.priority} /></td>
                          <td style={{ fontSize: 12 }}>{fmt.i(i.incidents)} tickets · {i.employees} people<div className="faint">{fmt.i(i.productivity_hours)} h lost · {usd(i.it_cost_usd)} IT cost</div>
                            <div className="faint">avg frustration {fmt.n(i.avg_frustration, 0)} · {i.high_frustration_tickets} high</div></td>
                          <td style={{ fontSize: 12 }}><b>{fmt.n(i.risk_tickets)}</b> <span className="faint">next wk</span><div style={{ color: tc }}>{tl}</div>
                            <div className="faint" style={{ fontSize: 11 }}>{i.trend.earlier} → {i.trend.later} tickets</div></td>
                          <td style={{ fontSize: 12, maxWidth: 280 }}>{i.solution.fix}<div className="faint mono" style={{ fontSize: 10.5 }}>{i.solution.kb_id}</div>
                            <div className="faint" style={{ fontSize: 11 }}>−{fmt.pct(i.solution.ticket_reduction_pct, 0)} tickets ({i.solution.effect_source === "measured"
                              ? `causal, ${i.solution.evidence_cases} past fixes` : "fleet average"})</div>
                            <div style={{ marginTop: 6 }}><FixNowButton small label="Fix now"
                              target={{ category: i.category, signal: KB_SIGNAL[i.solution.kb_id], department: filters.department }} /></div></td>
                          <td style={{ textAlign: "right", whiteSpace: "nowrap" }}><b className="good" style={{ fontSize: 15 }}>{usd(i.roi.annual_preventable_usd)}</b>
                            <div className="faint" style={{ fontSize: 11 }}>{fmt.i(i.roi.tickets_avoided_per_year)} tickets · {fmt.i(i.roi.hours_recovered_per_year)} h</div></td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              </div>
              {d.trivial_many.count > 0 && (
                <button className="btn btn-ghost btn-sm mt" onClick={() => setShowAll(!showAll)}>
                  {showAll ? "Show the critical few only" : `Show the ${d.trivial_many.count} trivial many`}</button>
              )}
            </Card>

            <Card className="mt" title="How the Priority Score is built">
              <div className="grid g-2" style={{ gap: 8 }}>
                {PARTS.map((x) => (
                  <div key={x.key} style={{ fontSize: 12.5 }}><Swatch color={x.color} /><b>{x.label} Impact</b> <span className="faint">(0–25)</span>
                    <div className="note">{d.definitions[x.key]}</div></div>
                ))}
              </div>
              <div className="note mt">Scaling: {d.definitions.scaling}. Critical few: {d.definitions.critical_few}. ROI: {d.definitions.roi}.</div>
            </Card>
          </>
        )}
      </QueryState>
    </>
  );
}
