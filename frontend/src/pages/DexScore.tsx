import { useEffect, useState } from "react";
import { AnalystOnly, useAnalyst } from "../components/analyst";
import { Any, bandColor, fmt, useApi, useFilters } from "../api";
import { Bars, TrendChart } from "../components/charts";
import { Card, ChartCard, QueryState } from "../components/ui";

const KEYS = ["eei", "dhs", "rss", "tre", "sts"] as const;

function band(s: number) { return s >= 85 ? "Excellent" : s >= 70 ? "Good" : s >= 55 ? "Fair" : "Poor"; }

function WhatIf({ base, weights, labels }: { base: Record<string, number>; weights: Record<string, number>; labels: Record<string, string> }) {
  const [v, setV] = useState(base);
  useEffect(() => setV(base), [base]);
  const score = KEYS.reduce((s, k) => s + weights[k] * v[k], 0);
  const baseScore = KEYS.reduce((s, k) => s + weights[k] * base[k], 0);
  return (
    <Card title="What-if simulator" sub="move a component to see its effect on the DEX Score (client-side, same formula)"
          right={<button className="btn btn-ghost btn-sm" onClick={() => setV(base)}>Reset</button>}>
      <div className="row" style={{ gap: 18, marginBottom: 12 }}>
        <div className="hero-num" style={{ fontSize: 44 }}>{fmt.n(score)}</div>
        <div><span className="band" style={{ color: bandColor(band(score)) }}>{band(score)}</span>
          <div className={score - baseScore >= 0 ? "good" : "crit"} style={{ fontSize: 12.5, marginTop: 6 }}>{fmt.signed(score - baseScore)} pts vs current</div></div>
      </div>
      {KEYS.map((k) => (
        <div key={k} style={{ marginBottom: 10 }}>
          <div className="row between" style={{ fontSize: 12 }}><label htmlFor={`wi-${k}`} className="dim">{labels[k]} <span className="faint mono">×{weights[k]}</span></label><span className="mono">{fmt.n(v[k])}</span></div>
          <input id={`wi-${k}`} type="range" min={0} max={100} step={0.5} value={v[k]} onChange={(e) => setV({ ...v, [k]: +e.target.value })} style={{ width: "100%", accentColor: "var(--machine)" }} />
        </div>
      ))}
    </Card>
  );
}

export default function DexScore() {
  const { qs } = useFilters();
  const q = useApi(`/v1/dex-score${qs}`);
  const [by, setBy] = useState<"by_department" | "by_device_model" | "by_work_mode">("by_department");
  const { on } = useAnalyst();
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">DEX Score framework</div>
          <h2>One outcome number, fully decomposable</h2>
          <p>One number for what employees feel, what devices do, and whether fixes stick.</p>
        </div>
      </div>
      <QueryState q={q}>
        {(d: Any) => {
          const s = d.score;
          return (
            <>
              <div className="grid g-split">
                <Card title="How the score is made" sub={on ? d.formula.expression : "five components, weighted"}>
                  <div className="hero" style={{ marginBottom: 14 }}>
                    <div className="hero-num">{fmt.n(s.dex_score)}</div>
                    <span className="band" style={{ color: bandColor(s.band) }}>{s.band}</span>
                    <span className="note">Excellent ≥ 85 · Good ≥ 70 · Fair ≥ 55 · Poor &lt; 55</span>
                  </div>
                  <table className="t">
                    <thead><tr><th>Component</th><th className="num">Score</th><th className="num">Weight</th><th className="num">Points</th>{on && <th>Definition</th>}</tr></thead>
                    <tbody>
                      {KEYS.map((k) => (
                        <tr key={k}>
                          <td><b>{d.formula.labels[k]}</b>{on && <span className="faint mono"> {k.toUpperCase()}</span>}</td>
                          <td className="num">{fmt.n(s.components[k])}</td>
                          <td className="num">{d.formula.weights[k]}</td>
                          <td className="num">{fmt.n(s.contributions[k])}</td>
                          {on && <td className="dim" style={{ fontSize: 12 }}>{d.formula.definitions[k]}</td>}
                        </tr>
                      ))}
                    </tbody>
                  </table>
                  <AnalystOnly><div className="note mt">Supporting: {s.supporting.devices} devices · {s.supporting.tickets} tickets · repeat-contact rate {fmt.pct(s.supporting.repeat_contact_rate_pct)} ·
                    {" "}burden slope {fmt.signed(s.supporting.burden_slope_per_week, 2)} pts/week</div></AnalystOnly>
                </Card>
                <WhatIf base={s.components} weights={d.formula.weights} labels={d.formula.labels} />
              </div>

              <div className={`grid ${on ? "g-3" : ""} mt`}>
                <ChartCard title="DEX Score" sub="rolling 4-week" table={d.weekly} columns={[{ key: "week", label: "Week" }, ...KEYS.map((k) => ({ key: k, label: k.toUpperCase(), num: true })), { key: "dex_score", label: "DEX", num: true }]}>
                  <TrendChart data={d.weekly} series={[{ key: "dex_score", name: "DEX Score", color: "var(--chart-machine)" }]} height={170} />
                </ChartCard>
                {on && KEYS.map((k) => (
                  <ChartCard key={k} title={d.formula.labels[k]} sub={`${k.toUpperCase()} · rolling 4-week`}>
                    <TrendChart data={d.weekly} series={[{ key: k, name: d.formula.labels[k], color: k === "eei" || k === "sts" ? "var(--chart-human)" : "var(--chart-machine)" }]} height={170} />
                  </ChartCard>
                ))}
              </div>

              <ChartCard className="mt" title="DEX Score by cohort" sub="lowest first"
                         right={<div className="seg">{([["by_department", "Department"], ["by_device_model", "Device model"], ["by_work_mode", "Work mode"]] as const).map(([k, l]) =>
                           <button key={k} className={by === k ? "on" : ""} onClick={() => setBy(k)}>{l}</button>)}</div>}
                         table={d[by]} columns={[{ key: "group", label: "Cohort" }, { key: "dex_score", label: "DEX", num: true }, ...KEYS.map((k) => ({ key: k, label: k.toUpperCase(), num: true })), { key: "devices", label: "Devices", num: true }]}>
                <Bars data={d[by]} x="group" y="dex_score" name="DEX Score" horizontal labels height={Math.max(160, d[by].length * 40)} xWidth={150} emphasize={(_, i) => i === 0} />
              </ChartCard>
            </>
          );
        }}
      </QueryState>
    </>
  );
}
