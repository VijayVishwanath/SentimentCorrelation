import { BellRing, Radar, Target, Wallet } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Any, fmt, qsOf, useApi, useMeta } from "../api";
import { Bars, TrendChart } from "../components/charts";
import { Card, ChartCard, DataTable, Kpi, Meter, QueryState } from "../components/ui";

export const RISK_COLOR: Record<string, string> = {
  High: "var(--critical)", Elevated: "var(--serious)", Watch: "var(--human)", Low: "var(--machine)",
};

export function RiskBadge({ band }: { band: string }) {
  return <span className="badge" style={{ color: RISK_COLOR[band], borderColor: RISK_COLOR[band] }}>{band}</span>;
}

function ModelVsRules({ m }: { m: Any }) {
  const bt = m.backtest;
  const rows = [
    { name: "Share of next-week frustrated tickets caught", ml: bt.ml.recall_pct, rules: bt.rules.recall_pct, max: 100, f: (v: number) => fmt.pct(v) },
    { name: "Precision of the flagged devices", ml: bt.ml.precision_pct, rules: bt.rules.precision_pct, max: 100, f: (v: number) => fmt.pct(v) },
    { name: "PR-AUC (ranking quality, rare events)", ml: bt.ml.pr_auc, rules: bt.rules.pr_auc, max: 1, f: (v: number) => fmt.n(v, 3) },
    { name: "ROC-AUC", ml: bt.ml.roc_auc, rules: bt.rules.roc_auc, max: 1, f: (v: number) => fmt.n(v, 3) },
  ];
  return (
    <Card title="Model vs rules — out-of-time backtest" sub={bt.method}>
      {rows.map((r) => (
        <div key={r.name} style={{ marginBottom: 14 }}>
          <div className="note" style={{ marginBottom: 4 }}>{r.name}</div>
          <Meter value={r.ml ?? 0} max={r.max} color="var(--chart-machine)" label={<span className="mono" style={{ fontSize: 12, minWidth: 110 }}>ML {r.f(r.ml)}</span>} />
          <Meter value={r.rules ?? 0} max={r.max} color="var(--text-faint)" label={<span className="mono faint" style={{ fontSize: 12, minWidth: 110 }}>Rules {r.f(r.rules)}</span>} />
        </div>
      ))}
      <div className="note">
        Test weeks {bt.test_weeks[0]}–{bt.test_weeks[bt.test_weeks.length - 1]} · {fmt.i(bt.rows)} device-weeks · {fmt.i(bt.positives)} frustrated
        tickets · base rate {fmt.pct(m.base_rate_pct, 2)}. "Rules" = the existing at-risk score (60% telemetry severity + 40%
        frustration burden, 4-week mean). A plain threshold rule (any signal past warn) flags {fmt.pct(bt.rules_threshold.flagged_share_pct)} of
        devices at {fmt.pct(bt.rules_threshold.precision_pct)} precision.
      </div>
    </Card>
  );
}

export default function Proactive() {
  const nav = useNavigate();
  const meta = useMeta();
  const [department, setDepartment] = useState("");
  const [top, setTop] = useState(50);
  const q = useApi(`/v1/forecast/watchlist${qsOf({ top, department })}`);
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Predictive DEX · Machine learning</div>
          <h2>Fix it before they call</h2>
          <p>A gradient-boosted model reads telemetry trends, recent experience and device context to predict which employees will
            raise a frustrated (High / Critical) ticket next week — explains why for each device, recommends the runbook fix,
            and prices the tickets a proactive fix avoids.</p>
        </div>
        <div className="row">
          <select aria-label="Department" value={department} onChange={(e) => setDepartment(e.target.value)}>
            <option value="">All departments</option>
            {meta.data?.dimensions?.departments?.map((d: string) => <option key={d}>{d}</option>)}
          </select>
          <div className="seg" role="group" aria-label="Watchlist size">
            {[25, 50, 100].map((n) => <button key={n} className={top === n ? "on" : ""} onClick={() => setTop(n)}>Top {n}</button>)}
          </div>
        </div>
      </div>
      <QueryState q={q}>
        {(d: Any) => !d.available ? (
          <Card title="Predictive model not available for this dataset">
            <p>{d.reason}</p>
            <p className="note">Upload more history on the Upload Dataset page, or generate a large simulated fleet with
              <span className="mono"> python -m app.data.simulator --devices 5000 --weeks 26</span> (run in <span className="mono">backend/</span>) and upload the four CSVs.</p>
          </Card>
        ) : (
          <>
            {d.metrics.low_sample && (
              <div className="error-box" role="note" style={{ marginBottom: 14 }}>
                Low sample: the backtest has only {d.metrics.backtest.positives} frustrated tickets to score, so treat these metrics as
                indicative. Upload a larger dataset for a statistically meaningful evaluation.
              </div>
            )}
            <div className="grid g-4">
              <Kpi label="Devices at elevated risk" icon={<BellRing size={12} />} value={fmt.i(d.summary.flagged)} accent="var(--critical)"
                   deltaLabel={`${d.summary.high} high · of ${fmt.i(d.summary.devices_scored)} scored`} hint="calibrated risk ≥ 25% of a frustrated ticket next week" />
              <Kpi label={`Expected frustrated tickets · W${d.predicts_week}`} icon={<Radar size={12} />} value={fmt.n(d.summary.expected_frustrated_tickets, 0)}
                   accent="var(--human)" deltaLabel="sum of calibrated risk across the fleet" />
              <Kpi label="Caught a week early" icon={<Target size={12} />} value={fmt.pct(d.metrics.backtest.ml.recall_pct, 0)} accent="var(--machine)"
                   deltaLabel={`vs ${fmt.pct(d.metrics.backtest.rules.recall_pct, 0)} for rules · top 5% of devices`} />
              <Kpi label={`Avoidable value · top ${d.summary.top_n}`} icon={<Wallet size={12} />} value={fmt.usd(d.summary.value_per_week_usd)} unit="/wk"
                   accent="var(--machine)" deltaLabel={`~${fmt.n(d.summary.avoidable_tickets_top_n)} tickets · ${fmt.usd(d.summary.value_annualised_usd)}/yr if sustained`}
                   hint={`risk × historical ticket-rate reduction of the recommended fix × ${fmt.usd(d.summary.cost_per_ticket_usd)} per ticket (support + lost productivity)`} />
            </div>

            <div className="grid g-split mt">
              <ModelVsRules m={d.metrics} />
              <ChartCard title="What drives the predictions" sub="share of mean |contribution| across the fleet this week"
                         table={d.metrics.drivers} columns={[{ key: "label", label: "Driver" }, { key: "share_pct", label: "Share %", num: true }]}>
                <Bars data={d.metrics.drivers} x="label" y="share_pct" name="Share of model attribution" horizontal labels xWidth={150}
                      height={Math.max(220, 30 * d.metrics.drivers.length)} yFmt={(v) => `${v.toFixed(0)}%`} />
              </ChartCard>
            </div>

            <Card className="mt" title={`Proactive watchlist · week ${d.predicts_week}`}
                  sub={`as of week ${d.as_of_week}${d.as_of_week_start ? ` (${d.as_of_week_start})` : ""}; ranked by calibrated risk. Click a row for Device 360.`}>
              <DataTable rows={d.items} onRow={(r: Any) => nav(`/devices/${r.device_id}`)} columns={[
                { key: "device_id", label: "Device", render: (r: Any) => <b className="mono">{r.device_id}</b> },
                { key: "employee_name", label: "Employee", render: (r: Any) => <span>{r.employee_name}<div className="faint" style={{ fontSize: 11 }}>{r.department} · {r.work_mode}</div></span> },
                { key: "risk_pct", label: "Risk", width: "150px", render: (r: Any) => (
                  <Meter value={r.risk_pct} color={RISK_COLOR[r.band]} label={<span className="mono" style={{ fontSize: 12 }}>{fmt.pct(r.risk_pct, 0)}</span>} />) },
                { key: "band", label: "Band", render: (r: Any) => <RiskBadge band={r.band} /> },
                { key: "drivers", label: "Why", render: (r: Any) => (
                  <div style={{ fontSize: 12, lineHeight: 1.45 }}>{r.drivers.slice(0, 2).map((x: Any) => <div key={x.group}>{x.text}</div>)}</div>) },
                { key: "category", label: "Likely cause", render: (r: Any) => r.category || <span className="faint">Experience</span> },
                { key: "action", label: "Proactive fix", render: (r: Any) => <span style={{ fontSize: 12 }}>{r.action}<div className="faint mono" style={{ fontSize: 10.5 }}>{r.kb_id}</div></span> },
                { key: "avoidable_tickets", label: "Avoidable", num: true, render: (r: Any) => fmt.n(r.avoidable_tickets, 2) },
              ]} />
            </Card>

            {d.metrics.calibration.length > 0 && (
              <ChartCard className="mt" title="Calibration — is 30% risk really 30%?" sub="backtest predictions grouped into deciles: predicted vs observed rate"
                         table={d.metrics.calibration} columns={[{ key: "decile", label: "Decile", num: true }, { key: "predicted_pct", label: "Predicted %", num: true },
                           { key: "observed_pct", label: "Observed %", num: true }, { key: "n", label: "n", num: true }]}>
                <TrendChart data={d.metrics.calibration} x="decile" xFmt={(v) => `D${v}`} yFmt={(v) => `${v.toFixed(0)}%`} height={200}
                            series={[{ key: "predicted_pct", name: "Predicted", color: "var(--chart-machine)" }, { key: "observed_pct", name: "Observed", color: "var(--chart-human)" }]} />
              </ChartCard>
            )}
            <footer className="foot">Target: {d.metrics.target}. LightGBM on {fmt.i(d.metrics.n_rows)} labelled device-weeks; risk calibrated on
              out-of-time predictions (isotonic). Correlation-based prediction, not proof of cause — the Diagnosis Assist confirms the fix.</footer>
          </>
        )}
      </QueryState>
    </>
  );
}
