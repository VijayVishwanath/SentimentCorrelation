import { ArrowLeft, Stethoscope } from "lucide-react";
import { Link, useNavigate, useParams } from "react-router-dom";
import { Any, bandColor, fmt, qsOf, useApi } from "../api";
import {
  CartesianGrid, Line, LineChart, ReferenceLine, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { Card, ChartCard, DataTable, PrePost, QueryState, SevBadge, ChartTip } from "../components/ui";
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
                { key: "frustration_score", label: "Frustration", num: true }, { key: "outcome_status", label: "Status" },
              ]} />
            </Card>
          </>
        );
      }}
    </QueryState>
  );
}
