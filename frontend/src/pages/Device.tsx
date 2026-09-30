import { ArrowLeft, Stethoscope } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Any, bandColor, fmt, qsOf, useApi } from "../api";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { TrendChart } from "../components/charts";
import { ExplainButton } from "../components/Explain";
import { FixNowButton } from "../components/FixNow";
import { Card, ChartCard, DataTable, Meter, PrePost, QueryState, SevBadge, ChartTip } from "../components/ui";
import { RISK_COLOR, RiskBadge } from "./Proactive";
import { Vitals } from "./Diagnosis";

const CHARTS = [
  { key: "device_health", title: "Device Health Score" },
  { key: "boot_duration_sec", title: "Boot duration (s)" },
  { key: "network_latency_ms", title: "Network latency (ms)" },
  { key: "app_hang_count", title: "App hangs / week" },
  { key: "hardware_health_score", title: "Hardware health" },
  { key: "experience_burden", title: "Frustration burden", human: true },
];

function DeviceTrend({ data, k, human, remWeeks }: { data: Any[]; k: string; human?: boolean; remWeeks: number[] }) {
  const color = human ? "var(--chart-human)" : "var(--chart-machine)";
  return (
    <ResponsiveContainer width="100%" height={150}>
      <LineChart data={data} margin={{ top: 8, right: 10, left: -4, bottom: 0 }}>
        <CartesianGrid stroke="var(--chart-grid)" vertical={false} />
        <XAxis dataKey="week" stroke="var(--chart-axis)" tick={{ fill: "var(--text-faint)", fontSize: 10.5 }} tickLine={false} tickFormatter={(v) => `W${v}`} />
        <YAxis stroke="var(--chart-axis)" tick={{ fill: "var(--text-faint)", fontSize: 10.5 }} tickLine={false} axisLine={false} width={40} />
        <Tooltip content={<ChartTip title={(l) => `Week ${l}`} />} />
        {remWeeks.map((w) => <ReferenceLine key={w} x={w} stroke="var(--human)" label={{ value: "fix", fill: "var(--human)", fontSize: 10, position: "insideTopLeft" }} />)}
        <Line isAnimationActive={false} type="linear" dataKey={k} stroke={color} strokeWidth={2} dot={{ r: 2.5, fill: color, strokeWidth: 0 }} activeDot={{ r: 5 }} name={k} />
      </LineChart>
    </ResponsiveContainer>
  );
}

function RiskPanel({ id }: { id: string }) {
  const q = useApi(`/v1/forecast/devices/${id}`);
  const r = q.data;
  if (!r?.available || !r.current) return null;
  const c = r.current;
  return (
    <div className="grid g-split mt">
      <Card title={`Next-week risk · W${c.predicts_week}`} sub="probability of a frustrated (High / Critical) ticket next week — predictive model"
            right={<RiskBadge band={c.band} />}>
        <Meter value={c.risk_pct} color={RISK_COLOR[c.band]} label={<b className="mono" style={{ fontSize: 18 }}>{fmt.pct(c.risk_pct, 0)}</b>} />
        <h4 className="card-title mt" style={{ marginBottom: 6 }}>Why</h4>
        {c.drivers.map((x: Any) => <div key={x.group} style={{ fontSize: 13, marginBottom: 4 }}>• {x.text}</div>)}
        {!c.drivers.length && <div className="note">No driver is pushing risk above the fleet baseline.</div>}
        <h4 className="card-title mt" style={{ marginBottom: 6 }}>Proactive fix</h4>
        <div style={{ fontSize: 13 }}>{c.action} <span className="faint mono">({c.kb_id})</span></div>
        {c.expected_outcome && <div className="note mt">Past {c.category} fixes ({c.expected_outcome.based_on_cases} cases): ticket rate
          −{fmt.pct(c.expected_outcome.ticket_rate_reduction_pct, 0)} ({c.expected_outcome.ticket_effect}), repeat contacts −{fmt.pct(c.expected_outcome.repeat_contact_reduction_pct, 0)}.</div>}
        {c.category && (c.fix_applied
          ? <div className="note mt"><span className="chip">fix applied</span> The {c.category} runbook already ran on this device; the
              risk updates once post-fix telemetry arrives.</div>
          : <div className="mt"><FixNowButton label={`Fix ${id} before the call`} target={{ category: c.category, deviceIds: [id] }} /></div>)}
      </Card>
      <ChartCard title="Risk history" sub="backtest weeks are out-of-time predictions; the last point is the live forecast"
                 table={r.history} columns={[{ key: "week", label: "As of week", num: true }, { key: "risk_pct", label: "Risk %", num: true },
                   { key: "actual_frustrated", label: "Frustrated next week?", render: (h: Any) => h.actual_frustrated === null ? "—" : h.actual_frustrated ? "Yes" : "No" },
                   { key: "source", label: "Source" }]}>
        <TrendChart data={r.history} series={[{ key: "risk_pct", name: "Risk %", color: "var(--chart-human)" }]} height={200}
                    yDomain={[0, 100]} yFmt={(v) => `${v.toFixed(0)}%`} xFmt={(v) => `W${v}`} />
      </ChartCard>
    </div>
  );
}

export default function Device() {
  const { id } = useParams();
  const nav = useNavigate();
  const q = useApi(`/v1/devices/${id}`);
  return (
    <QueryState q={q}>
      {(d: Any) => {
        const remWeeks = d.remediations.map((r: Any) => r.week_of_remediation);
        const last = d.tickets[d.tickets.length - 1];
        return (
          <>
            <div className="page-head">
              <div>
                <Link to="/telemetry" className="note"><ArrowLeft size={12} style={{ verticalAlign: -2 }} /> Fleet</Link>
                <div className="eyebrow mt">Device 360</div>
                <h2>{d.device.device_id} · {d.device.employee_name}</h2>
                <p>{d.device.department} · {d.device.work_mode} · {d.device.device_model} · {d.device.age_months} months old</p>
              </div>
              <div className="row">
                <div className="card" style={{ padding: "10px 16px", textAlign: "center" }}>
                  <div className="eyebrow" style={{ margin: 0 }}>DEX Score</div>
                  <div style={{ fontSize: 28, fontWeight: 800, color: bandColor(d.dex.band) }}>{fmt.n(d.dex.dex_score)}</div>
                </div>
                {last && <button className="btn btn-primary" onClick={() => nav(`/diagnosis${qsOf({ ticket: last.ticket_id })}`)}><Stethoscope size={14} />Diagnose latest ticket</button>}
              </div>
            </div>
            <Card title="Latest vitals" sub={`week ${d.history[d.history.length - 1].week}`}><Vitals vitals={d.vitals} /></Card>
            <RiskPanel id={d.device.device_id} />
            <div className="grid g-3 mt">
              {CHARTS.map((c) => (
                <ChartCard key={c.key} title={c.title} sub={remWeeks.length ? "vertical line = remediation week" : "12-week history"}
                           table={d.history} columns={[{ key: "week", label: "Week" }, { key: c.key, label: c.title, num: true }]}>
                  <DeviceTrend data={d.history} k={c.key} human={c.human} remWeeks={remWeeks} />
                </ChartCard>
              ))}
            </div>
            {d.remediations.length > 0 && (
              <Card className="mt" title="Remediations" sub="before vs after for this device">
                <DataTable rows={d.remediations} columns={[
                  { key: "remediation_id", label: "Case" }, { key: "week_of_remediation", label: "Week", num: true },
                  { key: "root_cause_category", label: "Root cause" }, { key: "action_taken", label: "Action" },
                  { key: "f", label: "Frustration", render: (r: Any) => <span><PrePost pre={r.pre_frustration_score} post={r.post_frustration_score} /> <span className="faint mono" style={{ fontSize: 10 }}>(n={r.post_ticket_count})</span></span> },
                  { key: "rr", label: "Repeat %", render: (r: Any) => <PrePost pre={r.pre_repeat_contact_rate_pct} post={r.post_repeat_contact_rate_pct} suffix="%" /> },
                  { key: "dex", label: "DEX", render: (r: Any) => <PrePost pre={r.dex_before} post={r.dex_after} lowerIsBetter={false} /> },
                ]} />
              </Card>
            )}
            <Card className="mt" title="Service-desk history" sub={`${d.tickets.length} ticket(s)`}>
              <DataTable rows={d.tickets} onRow={(r: Any) => nav(`/diagnosis${qsOf({ ticket: r.ticket_id })}`)} columns={[
                { key: "ticket_id", label: "Ticket", render: (r: Any) => <span className="mono">{r.ticket_id}</span> },
                { key: "week", label: "Week", num: true }, { key: "channel", label: "Channel" }, { key: "category", label: "Category" },
                { key: "ticket_text", label: "Text" }, { key: "emotion", label: "Emotion" },
                { key: "severity", label: "Severity", render: (r: Any) => <SevBadge sev={r.severity} /> },
                { key: "frustration_score", label: "Frustration", num: true, render: (r: Any) => (
                  <ExplainButton source={{ ticketId: r.ticket_id }}><b className="mono">{r.frustration_score}</b></ExplainButton>) },
                { key: "outcome_status", label: "Status" },
              ]} />
            </Card>
          </>
        );
      }}
    </QueryState>
  );
}
