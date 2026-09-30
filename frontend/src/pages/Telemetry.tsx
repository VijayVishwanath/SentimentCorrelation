import { CheckCircle2 } from "lucide-react";
import { useNavigate } from "react-router-dom";
import { Any, bandColor, fmt, qsOf, useApi, useFilters } from "../api";
import { TrendChart } from "../components/charts";
import { Card, ChartCard, DataTable, ErrorBox, Kpi, Loading, QueryState, useServerTable } from "../components/ui";

const SMALL = [
  { key: "device_health", title: "Device Health Score", color: "var(--chart-machine)" },
  { key: "boot_duration_sec", title: "Boot duration (s)", color: "var(--chart-machine)" },
  { key: "network_latency_ms", title: "Network latency (ms)", color: "var(--chart-machine)" },
  { key: "app_hang_count", title: "App hangs / device-week", color: "var(--chart-machine)" },
  { key: "hardware_health_score", title: "Hardware health", color: "var(--chart-machine)" },
  { key: "compliance_pct", title: "Policy compliance (%)", color: "var(--chart-machine)" },
];

const YES_NO = ["true", "false"];

function DeviceTable() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const st = useServerTable(5);
  const res = useApi(`/v1/telemetry/devices${qsOf({ ...filters, ...st.params })}`);
  const d: Any = res.data;
  return (
    <Card title="Device fleet" sub="latest-week vitals; risk = 60% telemetry severity + 40% frustration burden. Sort and filter from the headers; click a row for Device 360."
          right={d && <span className="chip">{fmt.i(d.total)} devices</span>}>
      {res.error && !d ? <ErrorBox error={res.error} /> : !d ? <Loading /> : (
        <div className={res.isPlaceholderData ? "stale" : ""}>
          <DataTable rows={d.items} onRow={(r: Any) => nav(`/devices/${r.device_id}`)}
                     server={st.table(d.total, { ...d.options, health_band: ["Healthy", "Degraded", "Poor"] })} columns={[
            { key: "device_id", label: "Device", filter: "text", render: (r: Any) => <b className="mono">{r.device_id}</b> },
            { key: "employee_name", label: "Employee", filter: "text", render: (r: Any) => <span>{r.employee_name}<div className="faint" style={{ fontSize: 11 }}>{r.work_mode}</div></span> },
            { key: "department", label: "Dept", filter: "select" },
            { key: "device_model", label: "Model", filter: "select", render: (r: Any) => <span>{r.device_model}<div className="faint" style={{ fontSize: 11 }}>{r.age_months} months</div></span> },
            { key: "health_band", label: "Band", filter: "select", render: (r: Any) => <span style={{ color: bandColor(r.health_band), fontWeight: 700 }}>{r.health_band}</span> },
            { key: "device_health", label: "Health", num: true, filter: "num", render: (r: Any) => <span style={{ color: bandColor(r.health_band) }}>{fmt.n(r.device_health)}</span> },
            { key: "boot_duration_sec", label: "Boot s", num: true, filter: "num" },
            { key: "network_latency_ms", label: "Latency", num: true, filter: "num" },
            { key: "app_hang_count", label: "Hangs", num: true, filter: "num" },
            { key: "policy_compliant", label: "Policy", filter: "select", options: YES_NO, optionLabels: { true: "Compliant", false: "Non-compliant" },
              render: (r: Any) => r.policy_compliant ? <span className="state-ok">Compliant</span> : <span className="state-critical">Non-compliant</span> },
            { key: "tickets", label: "Tickets", num: true, filter: "num" },
            { key: "risk_score", label: "Risk", num: true, filter: "num" },
            { key: "remediated", label: "Fixed", filter: "select", options: YES_NO, optionLabels: { true: "Fixed", false: "Not fixed" },
              render: (r: Any) => r.remediated ? <CheckCircle2 size={14} className="machine" aria-label="remediated" /> : "" },
          ]} />
        </div>
      )}
    </Card>
  );
}

export default function Telemetry() {
  const { qs } = useFilters();
  const q = useApi(`/v1/telemetry/summary${qs}`);
  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Telemetry Intelligence</div>
          <h2>What the devices are actually doing</h2>
          <p>Boot duration, application hangs, crash events, network latency and loss, VPN stability, policy compliance and
            hardware health — scored into a Device Health Score and a Telemetry Severity Score.</p>
        </div>
      </div>
      <QueryState q={q}>
        {(d: Any) => (
          <>
            <div className="grid g-4">
              <Kpi label="Device Health Score" value={fmt.n(d.kpis.device_health_score)} accent="var(--machine)" deltaLabel="mean over device-weeks" />
              <Kpi label="Telemetry Severity" value={fmt.n(d.kpis.telemetry_severity_score)} unit="/100" accent="var(--human)" deltaLabel="60% worst signal + 40% mean" />
              <Kpi label="Healthy devices" value={fmt.pct(d.kpis.healthy_devices_pct)} accent="var(--machine)" deltaLabel={`latest week · ${d.kpis.devices} devices`} />
              <Kpi label="Policy compliance" value={fmt.pct(d.kpis.compliance_pct)} accent="var(--human)" deltaLabel="share of device-weeks compliant" />
            </div>
            <div className="grid g-4 mt">
              <Kpi label="Avg boot" value={fmt.n(d.kpis.avg_boot_sec)} unit="s" accent="var(--machine)" />
              <Kpi label="Avg latency" value={fmt.n(d.kpis.avg_latency_ms)} unit="ms" accent="var(--machine)" />
              <Kpi label="VPN failure weeks" value={fmt.i(d.kpis.vpn_failure_weeks)} accent="var(--critical)" hint={d.derived_signal_notes.vpn_failure} deltaLabel="derived: packet loss ≥ 1.5%" />
              <Kpi label="Crash events" value={fmt.i(d.kpis.crash_events)} accent="var(--critical)" hint={d.derived_signal_notes.crash_events} deltaLabel="derived: crash tickets" />
            </div>

            <div className="grid g-3 mt">
              {SMALL.map((s) => (
                <ChartCard key={s.key} title={s.title} sub="fleet weekly mean" table={d.weekly} columns={[{ key: "week", label: "Week" }, { key: s.key, label: s.title, num: true }]}>
                  <TrendChart data={d.weekly} series={[{ key: s.key, name: s.title, color: s.color }]} height={160} />
                </ChartCard>
              ))}
            </div>

            <div className="grid g-split mt">
              <Card title="Threshold breaches" sub="device-weeks past warn / critical thresholds">
                <DataTable rows={d.breaches} pageSize={5} sortable columns={[
                  { key: "label", label: "Signal", filter: "text" },
                  { key: "thresholds", label: "Warn / critical", sortable: false, render: (r: Any) => r.thresholds ? <span className="mono faint">{r.thresholds.warn} / {r.thresholds.critical}</span> : <span className="faint">binary</span> },
                  { key: "warn", label: "Warn", num: true, filter: "num", render: (r: Any) => <span className="state-warn">{r.warn}</span> },
                  { key: "critical", label: "Critical", num: true, filter: "num", render: (r: Any) => <span className="state-critical">{r.critical}</span> },
                  { key: "devices_affected", label: "Devices", num: true, filter: "num" },
                ]} />
              </Card>
              <Card title="Fleet health bands" sub="latest week per device">
                {d.health_bands.map((b: Any) => {
                  const total = d.health_bands.reduce((s: number, x: Any) => s + x.devices, 0) || 1;
                  return (
                    <div key={b.band} className="rank-row" style={{ gridTemplateColumns: "80px 1fr 80px" }}>
                      <span style={{ color: bandColor(b.band), fontWeight: 700 }}>{b.band}</span>
                      <div className="bar-track"><div className="bar-fill" style={{ width: `${(100 * b.devices) / total}%`, background: bandColor(b.band) }} /></div>
                      <span className="rc">{b.devices} · {fmt.n((100 * b.devices) / total, 0)}%</span>
                    </div>
                  );
                })}
                <div className="note">Healthy ≥ 80 · Degraded 65–80 · Poor &lt; 65 (Device Health Score)</div>
                <h4 className="card-title mt-lg" style={{ marginBottom: 8 }}>By device model</h4>
                <DataTable rows={d.by_model} pageSize={5} sortable columns={[
                  { key: "device_model", label: "Model", filter: "text" }, { key: "devices", label: "Devices", num: true, filter: "num" },
                  { key: "device_health", label: "Health", num: true, filter: "num" }, { key: "boot", label: "Boot s", num: true, filter: "num" },
                  { key: "tickets", label: "Tickets", num: true, filter: "num" },
                ]} />
              </Card>
            </div>
            <div className="mt"><DeviceTable /></div>
          </>
        )}
      </QueryState>
    </>
  );
}
