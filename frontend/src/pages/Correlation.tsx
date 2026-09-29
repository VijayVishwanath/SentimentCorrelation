import { useState } from "react";
import { Any, SIGNAL_LABEL, fmt, qsOf, useApi, useFilters } from "../api";
import { Bars, BucketBars, ScatterFit } from "../components/charts";
import { Card, ChartCard, CorrMatrix, DataTable, Heatmap, QueryState } from "../components/ui";

const LIFT_ORDER = ["boot", "latency", "hangs", "hw_health", "policy"];

function Heatmaps() {
  const { filters } = useFilters();
  const [by, setBy] = useState("department");
  const [metric, setMetric] = useState<"risk_index" | "breach_rate_pct" | "avg_frustration_when_breached">("risk_index");
  const q = useApi(`/v1/correlation/heatmap${qsOf({ ...filters, by })}`);
  return (
    <QueryState q={q}>
      {(d: Any) => {
        const cell = (r: string, c: string) => d.risk.cells.find((x: Any) => x.cohort === r && x.signal === c);
        const tcell = (r: string, w: string) => d.trend.cells.find((x: Any) => x.cohort === r && String(x.week) === w);
        return (
          <div className="grid g-2">
            <Card title="Risk heatmap" sub="cohort × telemetry signal — risk = breach rate × frustration when breached (indexed to 100)"
                  right={
                    <div className="row">
                      <select value={by} onChange={(e) => setBy(e.target.value)} aria-label="Group by">
                        <option value="department">Department</option><option value="device_model">Device model</option><option value="work_mode">Work mode</option>
                      </select>
                      <select value={metric} onChange={(e) => setMetric(e.target.value as typeof metric)} aria-label="Metric">
                        <option value="risk_index">Risk index</option><option value="breach_rate_pct">Breach rate %</option><option value="avg_frustration_when_breached">Frustration when breached</option>
                      </select>
                    </div>}>
              <Heatmap rows={d.risk.cohorts} cols={d.risk.signals} value={(r, c) => cell(r, c)?.[metric] ?? null}
                       label={(v) => (v === null || v === undefined ? "—" : fmt.n(v, 0))}
                       tooltip={(r, c) => { const x = cell(r, c); return x ? `${r} · ${SIGNAL_LABEL[c]}: breach ${x.breach_rate_pct}% of device-weeks, ${x.devices_affected} devices, ${x.tickets_when_breached} tickets, frustration ${x.avg_frustration_when_breached ?? "—"}` : ""; }} />
            </Card>
            <Card title="Frustration heatmap" sub="average frustration by cohort and week (blank = no tickets)">
              <Heatmap rows={d.trend.cohorts} cols={d.trend.weeks.map((w: number) => ({ key: String(w), label: `W${w}` }))}
                       value={(r, w) => tcell(r, w)?.avg_frustration ?? null} max={100} minCol={26}
                       label={(v) => (v === null || v === undefined ? "" : fmt.n(v, 0))}
                       tooltip={(r, w) => { const x = tcell(r, w); return x ? `${r} · W${w}: ${x.tickets} tickets, avg frustration ${x.avg_frustration ?? "—"}` : ""; }} />
            </Card>
          </div>
        );
      }}
    </QueryState>
  );
}

function Scatter() {
  const { filters } = useFilters();
  const [signal, setSignal] = useState("severity");
  const q = useApi(`/v1/correlation/scatter${qsOf({ ...filters, signal })}`);
  return (
    <Card title="Ticket frustration vs telemetry at the time" sub="each dot is a ticket, joined to its device's telemetry in the same week; line = least-squares fit"
          right={<select value={signal} onChange={(e) => setSignal(e.target.value)} aria-label="Telemetry signal">
            {["severity", "boot", "latency", "packet_loss", "hangs", "hw_health", "battery", "disk"].map((s) => <option key={s} value={s}>{SIGNAL_LABEL[s]}</option>)}
          </select>}>
      <QueryState q={q}>
        {(d: Any) => (
          <>
            <ScatterFit points={d.points} fit={d.fit} xLabel={d.label} />
            <div className="note">Pearson r = <b className="mono">{fmt.n(d.correlation.pearson, 3)}</b> · Spearman = <b className="mono">{fmt.n(d.correlation.spearman, 3)}</b> · p {d.correlation.p_value === null ? "= —" : d.correlation.p_value < 0.001 ? "< 0.001" : `= ${d.correlation.p_value.toFixed(3)}`} · n = {d.correlation.n}</div>
          </>
        )}
      </QueryState>
    </Card>
  );
}

export default function Correlation() {
  const { filters } = useFilters();
  const [score, setScore] = useState("text");
  const q = useApi(`/v1/correlation/analysis${qsOf({ ...filters, score })}`);
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Module 3 · Correlation Engine</div>
          <h2>What's actually driving frustration</h2>
          <p>Subjective experience signals correlated with objective telemetry. Continuous signals use severity lift (worst vs best bucket);
            binary policy compliance uses incidence lift. Computed live from the dataset — not hardcoded.</p>
        </div>
        <div className="seg" role="group" aria-label="Score basis">
          <button className={score === "frustration" ? "on" : ""} onClick={() => setScore("frustration")}>Frustration (text + behaviour)</button>
          <button className={score === "text" ? "on" : ""} onClick={() => setScore("text")}>Text lexicon only (validated)</button>
        </div>
      </div>
      <QueryState q={q}>
        {(d: Any) => (
          <>
            <div className="grid g-main">
              <Card title="Correlation score" sub="Pearson r · frustration vs composite telemetry severity">
                <div className="hero">
                  <div><div className="hero-num">{fmt.n(d.headline.score, 2)}</div><span className="band" style={{ color: "var(--human)" }}>{d.headline.strength}</span></div>
                  <dl className="kv">
                    <dt>Ticket level</dt><dd className="mono">Pearson r = {fmt.n(d.headline.ticket_level.pearson, 3)} · Spearman {fmt.n(d.headline.ticket_level.spearman, 3)} · n = {d.headline.ticket_level.n}</dd>
                    <dt>Device-week</dt><dd className="mono">Pearson r = {fmt.n(d.headline.device_week_level.pearson, 3)} · n = {d.headline.device_week_level.n}</dd>
                    <dt>Reading</dt><dd className="dim" style={{ fontSize: 12.5 }}>When the device is struggling, employees say so — and more angrily. Correlation supports, it does not prove, a root cause.</dd>
                  </dl>
                </div>
              </Card>
              <Card title="Where text agrees with telemetry" sub="share of tickets in each category raised while that category's signal was breached">
                {d.category_evidence.map((c: Any) => (
                  <div key={c.category} className="rank-row" style={{ gridTemplateColumns: "140px 1fr 60px" }}>
                    <span style={{ fontWeight: 600 }}>{c.category}</span>
                    <div className="bar-track"><div className="bar-fill" style={{ width: `${c.breach_share_pct}%` }} /></div>
                    <span className="rc">{fmt.n(c.breach_share_pct, 0)}%</span>
                  </div>
                ))}
              </Card>
            </div>

            <div className="grid g-5 mt">
              {LIFT_ORDER.map((k) => {
                const l = d.lift[k];
                return (
                  <div key={k} className="card kpi" style={{ ["--accent" as string]: k === "policy" ? "var(--critical)" : "var(--human)" }}>
                    <div className="k">{l.metric}</div>
                    <div className="v">{k === "policy" && l.infinite ? "∞" : fmt.x(l.lift)}<small>lift</small></div>
                    <div className="d" style={{ lineHeight: 1.45, fontSize: 11.5 }}>{l.description}</div>
                  </div>
                );
              })}
            </div>

            <Card className="mt" title="Frustration by telemetry severity bucket" sub="average frustration per bucket (worst bucket emphasised), ticket count below each bar">
              <div className="grid g-4">
                {["boot", "latency", "hangs", "hw_health"].map((k) => (
                  <div key={k}>
                    <div className="card-sub" style={{ marginBottom: 4 }}>{SIGNAL_LABEL[k]}{k === "hw_health" ? " (higher = healthier)" : ""}</div>
                    <BucketBars buckets={d.lift[k].buckets} />
                  </div>
                ))}
              </div>
            </Card>

            <div className="grid mt" style={{ gridTemplateColumns: "minmax(0,0.75fr) minmax(0,1.25fr)" }}>
              <ChartCard title="Policy compliance → Login/Auth ticket incidence" sub="share of device-weeks that produced a Login/Auth ticket" table={d.lift.policy.buckets}
                         columns={[{ key: "label", label: "State" }, { key: "value", label: "Incidence %", num: true }, { key: "count", label: "Device-weeks", num: true }]}>
                <Bars data={d.lift.policy.buckets} x="label" y="value" name="Incidence %" color="var(--chart-human)" height={200} labels yFmt={(v) => `${fmt.n(v)}%`} emphasize={(_, i) => i === 1} />
              </ChartCard>
              <Card title="Impact ranking" sub="telemetry drivers ranked by experience cost">
                <DataTable rows={d.impact_ranking} columns={[
                  { key: "rank", label: "#", num: true },
                  { key: "label", label: "Driver", render: (r: Any) => <b>{r.label}</b> },
                  { key: "excess_tickets", label: "Excess tkts", num: true, render: (r: Any) => fmt.n(r.excess_tickets, 0) },
                  { key: "ticket_rate_when_breached", label: "Tkts/wk breach · ok", num: true, render: (r: Any) => `${fmt.n(r.ticket_rate_when_breached, 2)} · ${fmt.n(r.ticket_rate_when_healthy, 2)}` },
                  { key: "avg_frustration", label: "Frustr.", num: true },
                  { key: "pearson_r", label: "r", num: true, render: (r: Any) => fmt.n(r.pearson_r, 2) },
                  { key: "impact_score", label: "Impact", num: true, render: (r: Any) => fmt.n(r.impact_score, 1) },
                ]} />
              </Card>
            </div>

            <Card className="mt" title="Correlation matrix" sub={`experience signals × telemetry signals — Pearson r with significance. ${d.matrix.note}`}>
              <CorrMatrix matrix={d.matrix} />
            </Card>

            <div className="mt"><Heatmaps /></div>
            <div className="mt"><Scatter /></div>
          </>
        )}
      </QueryState>
    </>
  );
}
