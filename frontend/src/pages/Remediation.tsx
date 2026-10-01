import { useQueryClient } from "@tanstack/react-query";
import { AnalystOnly } from "../components/analyst";
import { Inbox, Play, RefreshCw, ScrollText, ShieldAlert, ShieldCheck, ShieldX, Wrench } from "lucide-react";
import { ReactNode, useEffect, useState } from "react";
import { Any, api, fmt, qsOf, useApi } from "../api";
import { Card, DataTable, ErrorBox, Kpi, QueryState, STATUS_COLOR, StatusBadge as Badge } from "../components/ui";

const URGENCY_COLOR: Record<string, string> = { critical: "var(--critical)", high: "var(--serious)", medium: "var(--human)", low: "var(--machine)" };

const enc = (id: string) => encodeURIComponent(id);

/** Per-device list whose step commands can be expanded. */
function DeviceSteps({ devices }: { devices: Any[] }) {
  const [open, setOpen] = useState<string | null>(null);
  return (
    <DataTable rows={devices} max={50} onRow={(r: Any) => setOpen(open === r.device_id ? null : r.device_id)} columns={[
      { key: "device_id", label: "Device", render: (r: Any) => <b className="mono">{r.device_id}</b> },
      { key: "status", label: "Result", render: (r: Any) => <Badge s={r.status} /> },
      { key: "installations", label: "Installs", num: true, render: (r: Any) => r.installations.length },
      { key: "detail", label: "Detail (click a row for commands)", render: (r: Any) => (
        <div style={{ fontSize: 12, lineHeight: 1.5 }}>
          {r.error && <div className="crit">{r.error}</div>}
          {(r.blockers || []).map((b: string) => <div key={b} className="crit">{b}</div>)}
          {r.warnings.map((w: string) => <div key={w} className="faint">{w}</div>)}
          {open === r.device_id && (
            <ol className="mono" style={{ fontSize: 11, margin: "6px 0 0", paddingLeft: 18 }}>
              {r.steps.map((s: Any, i: number) => (
                <li key={i} style={{ marginBottom: 3 }}>
                  <span className="faint">{s.step}</span> {s.command}
                  {s.result && <span className={s.result === "ok" ? "good" : "crit"}> [{s.result}]</span>}
                </li>
              ))}
            </ol>
          )}
        </div>) },
    ]} />
  );
}

function Field({ k, children }: { k: string; children: ReactNode }) {
  return <><dt>{k}</dt><dd>{children ?? <span className="faint">—</span>}</dd></>;
}

export default function Remediation() {
  const qc = useQueryClient();
  const emails = useApi("/v1/remediation/emails");
  const runs = useApi("/v1/remediation/runs");
  const auditQ = useApi("/v1/remediation/audit?limit=15");
  const [sel, setSel] = useState<string | null>(null);
  const [ack, setAck] = useState(false);
  const [approver, setApprover] = useState("");
  const [plan, setPlan] = useState<Any>(null);
  const [exec, setExec] = useState<Any>(null);
  const [outcome, setOutcome] = useState<Any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);

  const items: Any[] = emails.data?.items || [];
  useEffect(() => { if (!sel && items.length) setSel((items.find((m) => m.status === "pending") || items[0]).message_id); }, [items, sel]);
  useEffect(() => { setPlan(null); setExec(null); setOutcome(null); setErr(null); setAck(false); }, [sel]);

  const req = useApi(sel ? `/v1/remediation/emails/${enc(sel)}/request` : null);
  const r: Any = req.data;
  const target = r?.software_name && r?.software_version
    ? { software_name: r.software_name, version: r.software_version, devices: r.scope === "fleet" ? "" : r.device_ids.join(",") } : null;
  const matchQ = useApi(target && r?.valid ? `/v1/remediation/match${qsOf(target)}` : null);
  const safetyQ = useApi(target && r?.valid ? `/v1/remediation/safety${qsOf({ ...target, acknowledge_dependencies: ack || "" })}` : null);
  const email = items.find((m) => m.message_id === sel);
  const actionable = !!r?.valid && email?.status === "pending";

  const refresh = () => qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("/v1/remediation") });
  const act = async (name: string, fn: () => Promise<void>) => {
    setBusy(name); setErr(null);
    try { await fn(); } catch (e) { setErr(e); } finally { setBusy(null); refresh(); }
  };
  const body = { message_id: sel, acknowledge_dependencies: ack };
  const makePlan = () => act("plan", async () => { setPlan(await api("/v1/remediation/runs", { method: "POST", body: JSON.stringify(body) })); setExec(null); setOutcome(null); });
  const execute = () => act("exec", async () => {
    const tok = await api("/v1/remediation/token", { method: "POST" });
    setExec(await api("/v1/remediation/runs", { method: "POST", body: JSON.stringify({ ...body, dry_run: false, approved_by: approver.trim(), token_id: tok.token_id, plan_hash: plan?.plan_hash }) }));
  });
  const report = () => act("outcome", async () => { setOutcome(await api(`/v1/remediation/runs/${exec.run_id}/outcome`, { method: "POST" })); });
  const poll = () => act("poll", async () => { await api("/v1/remediation/emails/poll", { method: "POST" }); });

  const executed = (runs.data?.items || []).filter((x: Any) => !x.dry_run);
  const integrity = auditQ.data?.integrity;

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Security automation · MCP</div>
          <h2>Software Remediation</h2>
          <p>A security email asks for a software version to be removed: find it, check it is safe, and remove it after a named person approves.</p>
        </div>
        {emails.data?.imap_configured && (
          <button className="btn btn-ghost btn-sm" onClick={poll} disabled={busy === "poll"}><RefreshCw size={13} />Poll mailbox</button>
        )}
      </div>
      <div className="error-box" role="note" style={{ marginBottom: 14, color: "var(--text-dim)", borderColor: "var(--hairline)" }}>
        Simulated fleet: removal changes the simulated software inventory only. Commands shown are what an endpoint agent would run; nothing runs on this machine.
      </div>

      <div className="grid g-4">
        <Kpi label="Pending requests" icon={<Inbox size={12} />} value={fmt.i(items.filter((m) => m.status === "pending").length)} accent="var(--human)"
             deltaLabel={`${items.length} emails in the inbox`} />
        <Kpi label="Rejected senders" icon={<ShieldX size={12} />} value={fmt.i(items.filter((m) => m.status === "rejected").length)} accent="var(--critical)"
             deltaLabel="not on the authorized list" />
        <Kpi label="Devices remediated" icon={<Wrench size={12} />} value={fmt.i(executed.reduce((s: number, x: Any) => s + (x.removed || 0), 0))}
             accent="var(--machine)" deltaLabel={`${executed.length} executed runs · ${executed.reduce((s: number, x: Any) => s + (x.rolled_back || 0), 0)} rolled back`} />
        <Kpi label="Audit chain" icon={<ScrollText size={12} />} value={integrity ? (integrity.intact ? "Intact" : "Broken") : "—"}
             accent={integrity?.intact === false ? "var(--critical)" : "var(--machine)"} deltaLabel={integrity ? `${integrity.entries_checked} entries verified` : ""} />
      </div>

      <div className="grid g-split mt">
        <Card title="Inbox" sub={`Authorized senders: ${(emails.data?.authorized_senders || []).join(", ")}`}>
          <QueryState q={emails}>
            {() => (
              <DataTable rows={items} onRow={(m: Any) => setSel(m.message_id)} columns={[
                { key: "status", label: "Status", render: (m: Any) => <Badge s={m.status} /> },
                { key: "subject", label: "Request", render: (m: Any) => (
                  <span style={{ fontWeight: m.message_id === sel ? 700 : 400 }}>{m.subject}
                    <div className="faint mono" style={{ fontSize: 10.5 }}>{m.sender} · {m.source}</div></span>) },
              ]} />
            )}
          </QueryState>
        </Card>

        <Card title="Parsed request" sub={sel ? <span className="mono">{sel}</span> : "select an email"}>
          <QueryState q={req}>
            {(d: Any) => (
              <>
                <dl className="kv">
                  <Field k="Software">{d.software_name}</Field>
                  <Field k="Version">{d.software_version && <b className="mono">{d.software_version}</b>}</Field>
                  <Field k="Type">{d.request_type?.replace(/_/g, " ")}</Field>
                  <Field k="Urgency"><Badge s={d.urgency} color={URGENCY_COLOR[d.urgency]} /></Field>
                  <Field k="Targets">{d.scope === "fleet" ? "Entire fleet" : `${d.device_ids.length} listed device(s)`}</Field>
                  <Field k="Reason">{d.removal_reason}</Field>
                  <Field k="Replace with">{d.replacement}</Field>
                  <Field k="Sender">{d.sender_authorized ? <span className="good">{d.sender} (authorized)</span> : <span className="crit">{d.sender}</span>}</Field>
                </dl>
                {d.errors.length > 0 && (
                  <div className="error-box mt" role="alert"><b>Not actionable</b>{d.errors.map((e: string) => <div key={e}>{e}</div>)}</div>
                )}
                {email?.status === "processed" && <div className="note mt">Already processed: {email.note}</div>}
              </>
            )}
          </QueryState>
        </Card>
      </div>

      {r?.valid && (
        <Card className="mt" title="Targets & safety checks"
              sub="Only the exact version is removed. System-critical software and applications that depend on it block a device."
              right={<label className="row" style={{ fontSize: 12 }}><input type="checkbox" checked={ack} onChange={(e) => setAck(e.target.checked)} />Acknowledge dependencies</label>}>
          <QueryState q={matchQ}>
            {(m: Any) => (
              <div className="row" style={{ gap: 18, marginBottom: 10, fontSize: 13 }}>
                <span><b>{fmt.i(m.matching_installations)}</b> installation(s) of {m.target_version} on <b>{fmt.i(m.matching_devices)}</b> device(s)</span>
                {Object.keys(m.other_versions_left_untouched).length > 0 && (
                  <span className="faint">Left untouched: {Object.entries(m.other_versions_left_untouched).map(([v, n]) => `${v} (${n})`).join(", ")}</span>)}
                {m.listed_devices_without_target_version.length > 0 && (
                  <span className="faint">Listed but not carrying it: {m.listed_devices_without_target_version.join(", ")}</span>)}
                {m.unknown_device_ids.length > 0 && <span className="crit">Unknown: {m.unknown_device_ids.join(", ")}</span>}
              </div>
            )}
          </QueryState>
          <QueryState q={safetyQ}>
            {(s: Any) => (
              <>
                <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                  <Badge s={`${s.safe} safe`} color={STATUS_COLOR.safe} /><Badge s={`${s.warning} warning`} color={STATUS_COLOR.warning} />
                  <Badge s={`${s.blocked} blocked`} color={STATUS_COLOR.blocked} />
                </div>
                <DataTable rows={s.devices} max={25} columns={[
                  { key: "device_id", label: "Device", render: (x: Any) => <b className="mono">{x.device_id}</b> },
                  { key: "status", label: "Safety", render: (x: Any) => <Badge s={x.status} /> },
                  { key: "installations", label: "Installs", num: true },
                  { key: "why", label: "Findings", render: (x: Any) => (
                    <div style={{ fontSize: 12, lineHeight: 1.5 }}>
                      {x.blockers.map((b: string) => <div key={b} className="crit">{b}</div>)}
                      {x.dependencies.map((dep: Any) => <div key={dep.dependent_software} className="faint">{dep.dependent_software} {dep.dependent_version} needs {dep.requires}</div>)}
                      {x.warnings.map((w: string) => <div key={w} className="faint">{w}</div>)}
                      {!x.blockers.length && !x.warnings.length && <span className="good">No issues</span>}
                    </div>) },
                ]} />
                {s.devices.length > 25 && <div className="note">Showing 25 of {s.devices.length} devices.</div>}
              </>
            )}
          </QueryState>
        </Card>
      )}

      {r?.valid && (
        <Card className="mt" title="Plan, approve & execute"
              sub="1. Create the dry-run plan and review it. 2. Enter the approver's name. 3. Execute: a short-lived service-account token is issued for the run."
              right={<div className="row">
                <button className="btn btn-ghost btn-sm" onClick={makePlan} disabled={!actionable || !!busy}><ShieldAlert size={13} />{busy === "plan" ? "Planning…" : "Create dry-run plan"}</button>
                <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Approver name" aria-label="Approver name" style={{ width: 170 }} />
                <button className="btn btn-primary btn-sm" onClick={execute} disabled={!actionable || !plan || !approver.trim() || !!busy}
                        title={!plan ? "Create the dry-run plan first" : !approver.trim() ? "Enter who approved this removal" : ""}>
                  <Play size={13} />{busy === "exec" ? "Executing…" : "Approve & execute"}</button>
              </div>}>
          {err ? <ErrorBox error={err} /> : null}
          {!actionable && <div className="note">This request is already processed, so it can't be executed again.</div>}
          {plan && !exec && (
            <>
              <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                <span className="mono">{plan.run_id}</span><Badge s={plan.status} />
                <span className="faint" style={{ fontSize: 12 }}>{plan.planned} device(s) planned · {plan.skipped_blocked} skipped by safety checks</span>
              </div>
              <DeviceSteps devices={plan.devices} />
            </>
          )}
          {exec && (
            <>
              <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                <span className="mono">{exec.run_id}</span><Badge s={exec.status} />
                <span style={{ fontSize: 12 }}>{exec.removed} removed · {exec.rolled_back} rolled back · {exec.skipped_blocked} skipped · approved by {exec.approved_by}</span>
                <div className="spacer" />
                {!outcome && <button className="btn btn-ghost btn-sm" onClick={report} disabled={!!busy}><ShieldCheck size={13} />{busy === "outcome" ? "Reporting…" : "Report outcome"}</button>}
              </div>
              <DeviceSteps devices={exec.devices} />
            </>
          )}
          {!plan && !exec && actionable && <div className="empty">No plan yet</div>}
        </Card>
      )}

      {outcome && (
        <Card className="mt" title="Outcome" sub={outcome.note}>
          <div className="grid g-3">
            <Kpi label="Devices removed" value={fmt.i(outcome.devices_removed)} accent="var(--machine)"
                 deltaLabel={`${outcome.devices_rolled_back} rolled back · ${outcome.devices_skipped_blocked} skipped`} />
            <Kpi label="Avg boot before" value={fmt.n(outcome.avg_boot_before_sec)} unit="s" accent="var(--text-dim)" />
            <Kpi label="Avg boot after (projected)" value={fmt.n(outcome.avg_boot_after_projected_sec)} unit="s" accent="var(--machine)"
                 delta={outcome.avg_boot_before_sec && outcome.avg_boot_after_projected_sec ? outcome.avg_boot_after_projected_sec - outcome.avg_boot_before_sec : null}
                 goodWhen="down" deltaLabel="startup footprint of the removed package" />
          </div>
          <p className="mt" style={{ fontSize: 13 }}><b>Security team:</b> {outcome.security_team_summary}</p>
          {outcome.escalations.length > 0 && (
            <div className="error-box" role="alert"><b>Escalate to a human:</b>{outcome.escalations.map((e: Any) => <div key={e.device_id}>{e.device_id}: {e.error}</div>)}</div>
          )}
          <DataTable rows={outcome.devices} max={20} columns={[
            { key: "device_id", label: "Device", render: (x: Any) => <b className="mono">{x.device_id}</b> },
            { key: "employee_name", label: "Employee" },
            { key: "boot", label: "Boot (s)", render: (x: Any) => <span className="mono">{fmt.n(x.before.boot_duration_sec)} → {fmt.n(x.after_projected.boot_duration_sec)}</span> },
            { key: "user_notification", label: "Message sent to the employee", render: (x: Any) => <span style={{ fontSize: 12 }}>{x.user_notification}</span> },
          ]} />
        </Card>
      )}

      <AnalystOnly>
      <div className="grid g-2 mt">
        <Card title="Recent runs">
          <QueryState q={runs}>
            {(d: Any) => (
              <DataTable rows={d.items} max={10} columns={[
                { key: "run_id", label: "Run", render: (x: Any) => <span className="mono" style={{ fontSize: 12 }}>{x.run_id}</span> },
                { key: "software_name", label: "Software", render: (x: Any) => <span>{x.software_name} <span className="mono faint">{x.version}</span></span> },
                { key: "status", label: "Status", render: (x: Any) => <Badge s={x.dry_run ? "planned" : x.status} /> },
                { key: "removed", label: "Removed", num: true, render: (x: Any) => (x.dry_run ? "—" : x.removed) },
                { key: "approved_by", label: "Approved by", render: (x: Any) => x.approved_by || <span className="faint">dry run</span> },
              ]} />
            )}
          </QueryState>
        </Card>
        <Card title="Audit trail" sub="append-only, hash-chained: editing any entry breaks the chain"
              right={integrity && <span className="chip" style={{ color: integrity.intact ? "var(--machine)" : "var(--critical)" }}>
                {integrity.intact ? <ShieldCheck size={12} /> : <ShieldX size={12} />}{integrity.intact ? "chain intact" : `broken at #${integrity.first_broken_id}`}</span>}>
          <QueryState q={auditQ}>
            {(d: Any) => (
              <DataTable rows={d.items} columns={[
                { key: "created_at", label: "Time", render: (x: Any) => <span className="mono faint" style={{ fontSize: 11 }}>{String(x.created_at).slice(5, 19).replace("T", " ")}</span> },
                { key: "event", label: "Event", render: (x: Any) => x.event.replace(/_/g, " ") },
                { key: "run_id", label: "Run", render: (x: Any) => <span className="mono" style={{ fontSize: 11 }}>{x.run_id || "—"}</span> },
                { key: "actor", label: "Actor", render: (x: Any) => x.actor || <span className="faint">—</span> },
              ]} />
            )}
          </QueryState>
        </Card>
      </div>
      </AnalystOnly>
      <AnalystOnly><footer className="foot">Parsing, matching, safety checks, execution and the audit trail are the same code the MCP server uses
        (<span className="mono">backend/app/remediation</span>). See docs/REMEDIATION_MCP.md.</footer></AnalystOnly>
    </>
  );
}
