import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Play, ShieldAlert, ShieldCheck, Wrench, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { Link } from "react-router-dom";
import { Any, api, fmt, qsOf, useApi } from "../api";
import { DataTable, ErrorBox, Kpi, Loading, StatusBadge as Badge } from "./ui";

const usd = fmt.usdShort;

export interface FixTarget { category: string; signal?: string; deviceIds?: string[]; department?: string }

/** Runbook drawer: targets -> dry-run plan -> (auto-)approve -> execute -> verified result and projected outcome. */
function FixDrawer({ target, onClose }: { target: FixTarget; onClose: () => void }) {
  const qc = useQueryClient();
  const single = !!target.deviceIds?.length;
  const [size, setSize] = useState(single ? 1 : 25);
  const [approver, setApprover] = useState("");
  const [plan, setPlan] = useState<Any>(null);
  const [result, setResult] = useState<Any>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const t = useApi(`/v1/remediation/runbooks/targets${qsOf({ category: target.category, signal: target.signal,
    devices: target.deviceIds?.join(","), department: target.department, limit: 8 })}`);
  const rb: Any = t.data?.runbook;
  const high = rb?.risk === "high";
  const body = { category: target.category, signal: target.signal, device_ids: target.deviceIds, department: target.department, max_devices: size };

  const act = async (name: string, fn: () => Promise<void>) => {
    setBusy(name); setErr(null);
    try { await fn(); } catch (e) { setErr(e); } finally {
      setBusy(null);
      qc.invalidateQueries({ predicate: (q) => String(q.queryKey[0]).startsWith("/v1/remediation") });
    }
  };
  const doPlan = () => act("plan", async () => { setResult(null); setPlan(await api("/v1/remediation/runbooks/runs", { method: "POST", body: JSON.stringify(body) })); });
  const doRun = () => act("run", async () => {
    const extra: Any = { dry_run: false };
    if (high) {  // single-use token + the fingerprint of the plan the approver just reviewed
      extra.approved_by = approver.trim();
      extra.token_id = (await api("/v1/remediation/token", { method: "POST" })).token_id;
      extra.plan_hash = plan?.plan_hash;
    }
    setResult(await api("/v1/remediation/runbooks/runs", { method: "POST", body: JSON.stringify({ ...body, ...extra }) }));
  });

  const view = result || plan;
  const titleRef = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    // capture phase: the portal wrapper stops key events from bubbling past React's root
    const onKey = (e: KeyboardEvent) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey, true);
    return () => window.removeEventListener("keydown", onKey, true);
  }, [onClose]);
  useEffect(() => { titleRef.current?.focus(); }, [rb]);
  const deviceLink = (r: Any) => <Link className="mono" to={`/devices/${r.device_id}`} onClick={onClose}><b>{r.device_id}</b></Link>;
  return (
    <>
      <div className="drawer-bg" onClick={onClose} />
      <aside className="drawer" role="dialog" aria-modal="true" aria-labelledby="fix-title">
        <div className="row between">
          <div className="eyebrow" style={{ margin: 0 }}>Fix now · {target.category}{target.department ? ` · ${target.department}` : ""}</div>
          <button className="btn btn-ghost btn-sm" onClick={onClose} aria-label="Close"><X size={13} /></button>
        </div>
        {t.isLoading || !rb ? (t.error ? <ErrorBox error={t.error} /> : <Loading />) : (
          <>
            <h3 id="fix-title" ref={titleRef} tabIndex={-1} style={{ margin: "6px 0 4px", fontSize: 18, outline: "none" }}><Wrench size={16} style={{ verticalAlign: -2, marginRight: 6 }} />{rb.title}</h3>
            <div className="row" style={{ gap: 8, marginBottom: 12 }}>
              <span className="badge" style={{ color: high ? "var(--serious)" : "var(--machine)", borderColor: high ? "var(--serious)" : "var(--machine)" }}>
                {high ? <ShieldAlert size={11} /> : <ShieldCheck size={11} />}{high ? "High risk · approval required" : "Low risk · auto-approved"}</span>
              <span className="chip">{rb.runbook_id} · {rb.kb_id}</span>
            </div>

            <div className="grid g-3">
              <Kpi label="Devices to fix" value={fmt.i(t.data.pending)} accent="var(--human)" deltaLabel={`${fmt.i(t.data.already_fixed)} already fixed`} />
              <Kpi label="Tickets avoided / yr" value={view ? fmt.i(view.projected.tickets_avoided_per_year) : "—"} accent="var(--machine)"
                   deltaLabel={view ? `−${fmt.n(view.projected.ticket_reduction_pct, 0)}% caused by ${view.projected.based_on_cases} past fixes (vs matched)` : "create a plan"} />
              <Kpi label="Saved / yr" value={view ? usd(view.projected.savings_per_year_usd) : "—"} accent="var(--machine)" deltaLabel="projected for this batch" />
            </div>

            {!result && (
              <>
                <div className="field mt">Steps on each device</div>
                <ol className="mono" style={{ fontSize: 11.5, paddingLeft: 18, margin: "4px 0 10px", lineHeight: 1.6 }}>
                  {rb.steps.map((s: Any, i: number) => <li key={i}><span className="faint">{s.step}</span> {s.command}</li>)}
                </ol>
                {!single && (
                  <div className="row" style={{ marginBottom: 10 }}>
                    <span className="note">Batch size</span>
                    <div className="seg" role="group" aria-label="Batch size">
                      {[10, 25, 100].map((n) => <button key={n} className={size === n ? "on" : ""} onClick={() => { setSize(n); setPlan(null); }}>{n}</button>)}
                    </div>
                    <span className="note">of {fmt.i(t.data.pending)} pending, most recent breaches first</span>
                  </div>
                )}
                <DataTable rows={t.data.devices} columns={[
                  { key: "device_id", label: "Device", render: deviceLink },
                  { key: "employee_name", label: "Employee", render: (r: Any) => <span>{r.employee_name}<div className="faint" style={{ fontSize: 11 }}>{r.department}</div></span> },
                  { key: "evidence", label: "Why", render: (r: Any) => <span style={{ fontSize: 12 }}>{r.already_fixed ? <span className="good">already fixed</span> : r.evidence}</span> },
                ]} />
              </>
            )}

            {err ? <div className="mt"><ErrorBox error={err} /></div> : null}

            {!result && (
              <div className="row mt">
                <button className="btn btn-ghost" onClick={doPlan} disabled={!!busy || !t.data.pending}>{busy === "plan" ? "Planning…" : "1 · Dry-run plan"}</button>
                {high && <input value={approver} onChange={(e) => setApprover(e.target.value)} placeholder="Approver name" aria-label="Approver name" style={{ width: 180 }} />}
                <button className="btn btn-primary" onClick={doRun} disabled={!!busy || !plan || (high && !approver.trim())}
                        title={!plan ? "Create the dry-run plan first" : high && !approver.trim() ? "High-risk runbook: enter who approved it" : ""}>
                  <Play size={14} />{busy === "run" ? "Running…" : high ? "2 · Approve & run" : "2 · Run now"}</button>
                {plan && <span className="note">{plan.planned} device(s) planned · plan <span className="mono">{plan.plan_hash?.slice(0, 8)}</span></span>}
              </div>
            )}

            {result && (
              <div className="mt">
                <div className="row" style={{ gap: 8, marginBottom: 8 }}>
                  <CheckCircle2 size={16} className={result.status === "completed" ? "good" : "crit"} />
                  <b>{fmt.i(result.fixed)} fixed</b>{result.rolled_back > 0 && <span className="crit">· {result.rolled_back} rolled back & escalated</span>}
                  <Badge s={result.status} /><span className="mono faint" style={{ fontSize: 11 }}>{result.run_id} · approved by {result.approved_by}</span>
                </div>
                <DataTable rows={result.devices} max={50} columns={[
                  { key: "device_id", label: "Device", render: deviceLink },
                  { key: "status", label: "Result", render: (r: Any) => <Badge s={r.status} /> },
                  { key: "detail", label: "Detail", render: (r: Any) => <span style={{ fontSize: 12 }}>{r.error || `${r.steps.length} steps ok · verified`}</span> },
                ]} />
                <div className="row mt">
                  <Link className="btn btn-primary btn-sm" to={`/value?category=${encodeURIComponent(target.category)}`} onClick={onClose}>
                    See the proven outcome for {target.category} fixes →</Link>
                  <Link className="btn btn-ghost btn-sm" to="/remediation" onClick={onClose}>Audit trail</Link>
                  {!single && result.devices_pending_total > result.devices_targeted &&
                    <button className="btn btn-ghost btn-sm" onClick={() => { setResult(null); setPlan(null); t.refetch(); }}>Fix the next batch</button>}
                </div>
              </div>
            )}
            <p className="note mt">Simulated execution: steps are what an endpoint agent (Intune / ConfigMgr) would run. High-risk runs need a named
              human approver, a single-use token and the exact plan that was reviewed; every run is hash-chain audited and failed devices are rolled back.</p>
          </>
        )}
      </aside>
    </>
  );
}

export function FixNowButton({ target, label = "Fix now", small = false }: { target: FixTarget; label?: string; small?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button className="btn btn-primary btn-sm" style={small ? { padding: "3px 9px", fontSize: 11.5 } : undefined}
              onClick={(e) => { e.stopPropagation(); setOpen(true); }} onKeyDown={(e) => e.stopPropagation()}>
        <Wrench size={small ? 11 : 13} />{label}
      </button>
      {open && createPortal(
        // React bubbles portal events through the component tree: keep drawer clicks away from clickable table rows
        <div onClick={(e) => e.stopPropagation()} onKeyDown={(e) => e.stopPropagation()}>
          <FixDrawer target={target} onClose={() => setOpen(false)} />
        </div>, document.body)}
    </>
  );
}
