import { useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, Loader2, PlugZap, RefreshCw } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Any, api, fmt, useApi } from "../api";
import { Card, DataTable, ErrorBox } from "./ui";

const INTERVALS = [0, 5, 15, 60];

function ago(iso?: string | null) {
  if (!iso) return "—";
  const s = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (s < 60) return `${s}s ago`;
  if (s < 3600) return `${Math.round(s / 60)} min ago`;
  if (s < 86400) return `${Math.round(s / 3600)} h ago`;
  return new Date(iso).toLocaleString();
}

function until(iso?: string | null) {
  if (!iso) return null;
  const m = Math.round((new Date(iso).getTime() - Date.now()) / 60000);
  return m <= 0 ? "any moment" : `in ${m} min`;
}

const STATUS: Record<string, string> = {
  succeeded: "state-ok", no_changes: "dim", running: "state-warn", failed: "state-critical", skipped: "dim",
};

/** One-click ServiceNow incident sync with an optional schedule. Hands the analysis job to the page's stepper. */
export default function ServiceNowSync({ onJob, busy }: { onJob: (job: Any) => void; busy: boolean }) {
  const qc = useQueryClient();
  const status = useApi("/v1/integrations/servicenow/status");
  const runs = useApi("/v1/integrations/servicenow/runs");
  const [starting, setStarting] = useState(false);
  const [note, setNote] = useState<string | null>(null);
  const [err, setErr] = useState<unknown>(null);
  const lastSeen = useRef<number | null>(null);
  const s = status.data;

  // pick up scheduled syncs without a reload
  useEffect(() => {
    const t = setInterval(() => {
      qc.invalidateQueries({ queryKey: ["/v1/integrations/servicenow/status"] });
      qc.invalidateQueries({ queryKey: ["/v1/integrations/servicenow/runs"] });
    }, 30_000);
    return () => clearInterval(t);
  }, [qc]);
  useEffect(() => {
    const run = s?.last_run;
    if (!run) return;
    if (lastSeen.current !== null && lastSeen.current !== run.id && run.trigger === "scheduled" && run.job_id && !busy) {
      api(`/v1/datasets/jobs/${run.job_id}`).then(onJob).catch(() => undefined);
    }
    lastSeen.current = run.id;
  }, [s?.last_run, busy, onJob]);

  const refresh = () => {
    qc.invalidateQueries({ queryKey: ["/v1/integrations/servicenow/status"] });
    qc.invalidateQueries({ queryKey: ["/v1/integrations/servicenow/runs"] });
  };

  const syncNow = async () => {
    setErr(null); setNote(null); setStarting(true);
    try {
      const r = await api("/v1/integrations/servicenow/sync", { method: "POST" });
      lastSeen.current = r.run.id;
      if (r.job) {
        onJob(r.job);
        setNote(`${fmt.i(r.run.fetched)} incident(s) fetched · ${fmt.i(r.run.created)} new · ${fmt.i(r.run.updated)} updated`
          + (r.run.skipped ? ` · ${fmt.i(r.run.skipped)} skipped` : ""));
      } else setNote("Already up to date: no incidents changed since the last sync.");
    } catch (e) { setErr(e); } finally { setStarting(false); refresh(); }
  };

  const test = async () => {
    setErr(null); setNote(null);
    try {
      const r = await api("/v1/integrations/servicenow/test", { method: "POST" });
      setNote(`Connected to ${r.instance}${r.sample ? ` · latest record ${r.sample}` : ""}`);
    } catch (e) { setErr(e); }
  };

  const save = async (body: Any) => {
    setErr(null);
    try { await api("/v1/integrations/servicenow/settings", { method: "PUT", body: JSON.stringify(body) }); refresh(); }
    catch (e) { setErr(e); }
  };

  const live = s?.mode === "live";
  const last = s?.last_run;
  return (
    <Card title={<span className="row" style={{ gap: 8 }}><RefreshCw size={16} className="machine" />Sync with ServiceNow</span>}
          sub="pulls incidents changed since the last sync and analyses them, with no export or upload"
          right={s && <span className="chip" title={live ? "Reading the live ServiceNow Table API" : "Built-in demo instance: set DEX_SERVICENOW_* in .env for a real instance"}>
            <PlugZap size={12} />{live ? `Live · ${s.instance}` : "Demo instance"}</span>}>
      <div className="grid g-split">
        <div>
          <div className="row" style={{ gap: 10, flexWrap: "wrap" }}>
            <button className="btn btn-primary" onClick={syncNow} disabled={starting || busy || !s}>
              {starting || busy ? <Loader2 size={14} className="spin" /> : <RefreshCw size={14} />}Sync with ServiceNow
            </button>
            <button className="btn btn-ghost btn-sm" onClick={test} disabled={starting}>Test connection</button>
          </div>
          <dl className="kv mt">
            <dt>Last sync</dt>
            <dd>{last ? <>{ago(last.started_at)} · <span className={STATUS[last.status] || ""}>{last.status.replace("_", " ")}</span>
              {last.status === "succeeded" && <> · {fmt.i(last.created)} new, {fmt.i(last.updated)} updated</>}
              <span className="faint"> · {last.trigger}</span></> : "never"}</dd>
            <dt>Window</dt><dd>{last ? <>changes after <span className="mono">{last.since} UTC</span></> : `first sync reaches back ${s?.lookback_days ?? 90} days`}</dd>
            {last?.status === "failed" && <><dt>Error</dt><dd className="crit">{last.error}</dd></>}
          </dl>
          {note && <div className="note mt"><CheckCircle2 size={12} className="machine" style={{ verticalAlign: -2 }} /> {note}</div>}
          {err ? <div className="mt"><ErrorBox error={err} /></div> : null}
        </div>
        <div>
          <div className="field">Auto-sync</div>
          <div className="seg" role="radiogroup" aria-label="Auto-sync interval">
            {INTERVALS.map((m) => (
              <button key={m} role="radio" aria-checked={s?.auto_sync_minutes === m} className={s?.auto_sync_minutes === m ? "on" : ""}
                      onClick={() => save({ auto_sync_minutes: m })} disabled={!s}>{m === 0 ? "Off" : m === 60 ? "Hourly" : `${m} min`}</button>
            ))}
          </div>
          <div className="note mt"><Clock size={12} style={{ verticalAlign: -2 }} />{" "}
            {s?.auto_sync_minutes ? <>Next sync {until(s.next_run_at)}. New and updated incidents flow into every dashboard on their own.</>
              : "Off. Turn it on to keep the platform current without clicking."}</div>
          <div className="field mt">Source</div>
          <div className="seg" role="radiogroup" aria-label="ServiceNow source">
            {[["auto", "Auto"], ["live", "Live instance"], ["mock", "Demo instance"]].map(([k, l]) => (
              <button key={k} role="radio" aria-checked={s?.mode_setting === k} className={s?.mode_setting === k ? "on" : ""}
                      onClick={() => save({ mode: k })} disabled={!s || (k === "live" && !s.live_configured)}
                      title={k === "live" && !s?.live_configured ? "Set DEX_SERVICENOW_INSTANCE, USERNAME and PASSWORD in .env" : undefined}>{l}</button>
            ))}
          </div>
          <div className="note mt">{s?.live_configured ? <>Configured instance: <span className="mono">{s.configured_instance}</span></>
            : "No instance configured: Auto uses the demo instance, which serves realistic incidents for this fleet."}</div>
        </div>
      </div>
      {runs.data?.items?.length > 0 && (
        <details className="mt">
          <summary className="field" style={{ cursor: "pointer" }}>Sync history ({runs.data.items.length})</summary>
          <DataTable rows={runs.data.items} columns={[
            { key: "started_at", label: "Started", render: (r: Any) => new Date(r.started_at).toLocaleString() },
            { key: "trigger", label: "Trigger" },
            { key: "instance", label: "Source" },
            { key: "status", label: "Result", render: (r: Any) => <span className={STATUS[r.status] || ""} title={r.error || undefined}>{r.status.replace("_", " ")}</span> },
            { key: "fetched", label: "Fetched", num: true },
            { key: "created", label: "New", num: true },
            { key: "updated", label: "Updated", num: true },
            { key: "unmatched_devices", label: "Unknown CIs", num: true },
          ]} />
        </details>
      )}
    </Card>
  );
}
