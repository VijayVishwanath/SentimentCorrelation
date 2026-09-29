import { CheckCircle2 } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { Any, bandColor, fmt, qsOf, useApi, useFilters } from "../api";
import { TrendChart } from "../components/charts";
import { Card, ChartCard, DataTable, Kpi, QueryState } from "../components/ui";

const SMALL = [
  { key: "device_health", title: "Device Health Score", color: "var(--chart-machine)" },
  { key: "boot_duration_sec", title: "Boot duration (s)", color: "var(--chart-machine)" },
  { key: "network_latency_ms", title: "Network latency (ms)", color: "var(--chart-machine)" },
  { key: "app_hang_count", title: "App hangs / device-week", color: "var(--chart-machine)" },
  { key: "hardware_health_score", title: "Hardware health", color: "var(--chart-machine)" },
  { key: "compliance_pct", title: "Policy compliance (%)", color: "var(--chart-machine)" },
];

function DeviceTable() {
  const { filters } = useFilters();
  const nav = useNavigate();
  const [q, setQ] = useState("");
  const [band, setBand] = useState("");
  const [sort, setSort] = useState("risk");
  const [page, setPage] = useState(0);
  const limit = 15;
  const res = useApi(`/v1/telemetry/devices${qsOf({ ...filters, q, band, sort, limit, offset: page * limit })}`);
  return (
    <Card title="Device fleet" sub="latest-week vitals; risk = 60% telemetry severity + 40% frustration burden. Click a row for Device 360.">
      <div className="row" style={{ marginBottom: 12 }}>
        <input type="search" placeholder="Search device or employee…" value={q} onChange={(e) => { setQ(e.target.value); setPage(0); }} aria-label="Search devices" />
        <select value={band} onChange={(e) => { setBand(e.target.value); setPage(0); }} aria-label="Health band"><option value="">All health bands</option><option>Healthy</option><option>Degraded</option><option>Poor</option></select>
        <div className="seg" role="group" aria-label="Sort">
          {[["risk", "Risk"], ["health", "Worst health"], ["tickets", "Tickets"], ["device_id", "ID"]].map(([k, l]) => (
            <button key={k} className={sort === k ? "on" : ""} onClick={() => setSort(k)}>{l}</button>
          ))}
        </div>
        {res.data && <span className="chip">{res.data.total} devices</span>}
      </div>
      <QueryState q={res}>
        {(d: Any) => (
          <>
            <DataTable rows={d.items} onRow={(r: Any) => nav(`/devices/${r.device_id}`)} columns={[
              { key: "device_id", label: "Device", render: (r: Any) => <b className="mono">{r.device_id}</b> },
              { key: "employee_name", label: "Employee", render: (r: Any) => <span>{r.employee_name}<div className="faint" style={{ fontSize: 11 }}>{r.department} · {r.work_mode}</div></span> },
              { key: "device_model", label: "Model", render: (r: Any) => <span>{r.device_model}<div className="faint" style={{ fontSize: 11 }}>{r.age_months} months</div></span> },
              { key: "device_health", label: "Health", num: true, render: (r: Any) => <span style={{ color: bandColor(r.health_band) }}>{fmt.n(r.device_health)}</span> },
              { key: "boot_duration_sec", label: "Boot s", num: true },
              { key: "network_latency_ms", label: "Latency", num: true },
              { key: "app_hang_count", label: "Hangs", num: true },
              { key: "policy_compliant", label: "Policy", render: (r: Any) => r.policy_compliant ? <span className="state-ok">Compliant</span> : <span className="state-critical">Non-compliant</span> },
              { key: "tickets", label: "Tickets", num: true },
              { key: "risk_score", label: "Risk", num: true },
              { key: "remediated", label: "Fixed", render: (r: Any) => r.remediated ? <CheckCircle2 size={14} className="machine" aria-label="remediated" /> : "" },
            ]} />
            <div className="row mt between">
              <span className="note">Showing {d.total ? page * limit + 1 : 0}–{Math.min(d.total, (page + 1) * limit)} of {d.total}</span>
              <div className="row">
                <button className="btn btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}>Previous</button>
                <button className="btn btn-ghost btn-sm" disabled={(page + 1) * limit >= d.total} onClick={() => setPage(page + 1)}>Next</button>
              </div>
            </div>
          </>
        )}
      </QueryState>
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
          <div className="eyebrow">Module 2 · Telemetry Intelligence</div>
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
                <DataTable rows={d.breaches} columns={[
                  { key: "label", label: "Signal" },
                  { key: "thresholds", label: "Warn / critical", render: (r: Any) => r.thresholds ? <span className="mono faint">{r.thresholds.warn} / {r.thresholds.critical}</span> : <span className="faint">binary</span> },
                  { key: "warn", label: "Warn", num: true, render: (r: Any) => <span className="state-warn">{r.warn}</span> },
                  { key: "critical", label: "Critical", num: true, render: (r: Any) => <span className="state-critical">{r.critical}</span> },
                  { key: "devices_affected", label: "Devices", num: true },
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
                <DataTable rows={d.by_model} columns={[
                  { key: "device_model", label: "Model" }, { key: "devices", label: "Devices", num: true },
                  { key: "device_health", label: "Health", num: true }, { key: "boot", label: "Boot s", num: true },
                  { key: "tickets", label: "Tickets", num: true },
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
