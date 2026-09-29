import { useQueryClient } from "@tanstack/react-query";
import {
  AlertTriangle, ArrowRight, CheckCircle2, CircleDashed, Download, FileSpreadsheet, FileText, Loader2,
  RotateCcw, UploadCloud, X, XCircle,
} from "lucide-react";
import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { Any, api, ApiError, downloadFile, fmt, getApiKey, useApi } from "../api";
import { Card, DataTable, ErrorBox, QueryState } from "../components/ui";

const MAX_MB = 200;
const ALLOWED = [".xlsx", ".csv"];

interface Picked { file: File; error?: string }

function sizeLabel(b: number) {
  return b >= 1024 * 1024 ? `${(b / 1024 / 1024).toFixed(1)} MB` : `${Math.max(1, Math.round(b / 1024))} KB`;
}

function checkFile(f: File, maxMb: number): string | undefined {
  const ext = f.name.slice(f.name.lastIndexOf(".")).toLowerCase();
  if (!ALLOWED.includes(ext)) return "Only .xlsx and .csv files are allowed";
  if (f.size === 0) return "File is empty";
  if (f.size > maxMb * 1024 * 1024) return `Exceeds the ${maxMb} MB limit (${sizeLabel(f.size)})`;
  return undefined;
}

/** multipart upload with progress (fetch has no upload-progress events) */
function uploadWithProgress(files: File[], mode: string, onProgress: (pct: number) => void): Promise<Any> {
  return new Promise((resolve, reject) => {
    const fd = new FormData();
    files.forEach((f) => fd.append("files", f, f.name));
    fd.append("mode", mode);
    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/v1/datasets/analyze");
    const key = getApiKey();
    if (key) xhr.setRequestHeader("X-API-Key", key);
    xhr.upload.onprogress = (e) => { if (e.lengthComputable) onProgress(Math.round((100 * e.loaded) / e.total)); };
    xhr.onload = () => {
      let body: Any = null;
      try { body = JSON.parse(xhr.responseText); } catch { /* non-JSON */ }
      if (xhr.status >= 200 && xhr.status < 300) resolve(body);
      else reject(new ApiError(xhr.status, typeof body?.error === "string" ? body.error : body?.error?.message || xhr.statusText || "Upload failed"));
    };
    xhr.onerror = () => reject(new ApiError(0, "Network error while uploading"));
    xhr.send(fd);
  });
}

const COMPARE: [string, string, number, string?, boolean?][] = [
  ["devices", "Devices", 0], ["tickets", "Tickets", 0], ["device_weeks", "Device-weeks", 0], ["remediations", "Remediation cases", 0],
  ["dex_score", "DEX Score", 1, "", true], ["eei", "Employee Experience Index", 1, "", true], ["dhs", "Device Health Score", 1, "", true],
  ["correlation_score", "Correlation score (r)", 2, "", true], ["avg_frustration", "Avg frustration", 1, "", false],
  ["repeat_contact_rate_pct", "Repeat-contact rate", 1, "%", false], ["experience_recovery_pct", "Experience Recovery", 1, "%", true],
  ["annual_savings_usd", "Annualised value", 0, "$", true],
];

function Stepper({ job }: { job: Any }) {
  const idx = job.stages.findIndex((s: Any) => s.key === job.stage);
  return (
    <div className="grid" style={{ gap: 6 }}>
      {job.stages.map((s: Any, i: number) => {
        const done = i < idx || job.state === "succeeded";
        const active = i === idx && job.state === "running";
        const failed = i === idx && job.state === "failed";
        const msg = [...job.log].reverse().find((l: Any) => l.stage === s.key)?.message;
        return (
          <div key={s.key} className="row" style={{ gap: 10, alignItems: "flex-start", opacity: i > idx && job.state !== "succeeded" ? 0.45 : 1 }}>
            {failed ? <XCircle size={16} className="crit" /> : done ? <CheckCircle2 size={16} className="machine" />
              : active ? <Loader2 size={16} className="human spin" /> : <CircleDashed size={16} className="faint" />}
            <div style={{ flex: 1 }}>
              <div style={{ fontWeight: 600, fontSize: 13 }}>{s.label}</div>
              {msg && msg !== s.label && <div className="note">{msg}</div>}
            </div>
          </div>
        );
      })}
    </div>
  );
}

function Result({ job }: { job: Any }) {
  const r = job.result;
  const before = r.before || {};
  const after = r.after || {};
  const mapped: string[] = r.report.derived.filter((d: string) => d.includes("' mapped to '"));
  const derived: string[] = r.report.derived.filter((d: string) => !d.includes("' mapped to '"));
  const rows = COMPARE.map(([k, label, d, unit, higherBetter]) => {
    const b = before[k], a = after[k];
    const f = (v: number | null | undefined) => (v === null || v === undefined ? "—" : unit === "$" ? fmt.usd(v) : `${d === 0 ? fmt.i(v) : fmt.n(v, d)}${unit || ""}`);
    const delta = typeof a === "number" && typeof b === "number" ? a - b : null;
    const good = delta === null || higherBetter === undefined ? null : higherBetter ? delta >= 0 : delta <= 0;
    return { metric: label, before: f(b), after: f(a), change: delta === null ? "—" : `${delta > 0 ? "+" : ""}${d === 0 ? fmt.i(delta) : fmt.n(delta, d)}`, good };
  });
  return (
    <Card title={<span className="row" style={{ gap: 8 }}><CheckCircle2 size={16} className="machine" />Analysis complete — every module now reflects this dataset</span>}
          sub={`${job.files.map((f: Any) => f.name).join(", ")} · ${job.mode} · ${job.duration_sec}s`}>
      <div className="grid g-split">
        <div>
          <div className="field">Before vs after this upload</div>
          <DataTable rows={rows} columns={[
            { key: "metric", label: "Metric" }, { key: "before", label: "Before", num: true },
            { key: "after", label: "After", num: true, render: (x: Any) => <b>{x.after}</b> },
            { key: "change", label: "Change", num: true, render: (x: Any) => <span className={x.good === null ? "dim" : x.good ? "good" : "crit"}>{x.change}</span> },
          ]} />
          <div className="note mt">Top telemetry driver: <b>{after.top_driver || "—"}</b> · correlation {after.correlation_strength}
            {after.weeks && <> · weeks {after.weeks[0]}–{after.weeks[1]}</>}</div>
        </div>
        <div>
          <div className="field">Explore the results</div>
          <div className="grid" style={{ gap: 6 }}>
            {[["/", "Executive Dashboard"], ["/correlation", "Correlation Engine"], ["/experience", "Experience Analytics"],
              ["/telemetry", "Telemetry Intelligence"], ["/diagnosis", "Diagnosis Assist"], ["/outcomes", "Outcome Reporting"], ["/dex-score", "DEX Score"]].map(([to, l]) => (
              <Link key={to} to={to} className="card-flat row between" style={{ textDecoration: "none" }}><span>{l}</span><ArrowRight size={14} /></Link>
            ))}
          </div>
          {derived.length > 0 && (
            <details className="mt" open>
              <summary className="field" style={{ cursor: "pointer" }}>What the system derived ({derived.length})</summary>
              <ul className="note" style={{ margin: "4px 0 0 16px", padding: 0 }}>{derived.map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
            </details>
          )}
          {mapped.length > 0 && (
            <details className="mt">
              <summary className="field" style={{ cursor: "pointer" }}>Column mapping ({mapped.length} columns recognised by alias)</summary>
              <ul className="note" style={{ margin: "4px 0 0 16px", padding: 0 }}>{mapped.map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
            </details>
          )}
          {r.report.warnings.length > 0 && (
            <details className="mt">
              <summary className="field" style={{ cursor: "pointer", color: "var(--human)" }}>Warnings ({r.report.warnings.length})</summary>
              <ul className="note" style={{ margin: "4px 0 0 16px", padding: 0 }}>{r.report.warnings.map((d: string, i: number) => <li key={i}>{d}</li>)}</ul>
            </details>
          )}
          {r.report.missing_signals.length > 0 && (
            <div className="note mt"><AlertTriangle size={12} className="human" style={{ verticalAlign: -2 }} /> Not in this dataset (analysis skips them): {r.report.missing_signals.join(", ")}</div>
          )}
        </div>
      </div>
    </Card>
  );
}

function ColumnGuide() {
  const q = useApi("/v1/datasets/schema");
  const [tab, setTab] = useState("telemetry");
  return (
    <Card title="Column guide" sub="column names are matched case-insensitively; common alternatives are recognised automatically">
      <QueryState q={q}>
        {(d: Any) => {
          const t = d.tables.find((x: Any) => x.table === tab);
          return (
            <>
              <div className="tabs">
                {["telemetry", "tickets", "devices", "remediations"].map((k) => (
                  <button key={k} className={tab === k ? "on" : ""} onClick={() => setTab(k)}>{k}</button>
                ))}
              </div>
              <div className="row between" style={{ marginBottom: 10 }}>
                <p className="note" style={{ margin: 0, maxWidth: 720 }}>{t.help}</p>
                <button className="btn btn-ghost btn-sm" onClick={() => downloadFile(`/v1/datasets/templates/${tab}.csv`, `dex_${tab}_template.csv`)}><Download size={13} />{tab}.csv template</button>
              </div>
              <DataTable rows={t.columns} columns={[
                { key: "name", label: "Column", render: (c: Any) => <span className="mono">{c.name}</span> },
                { key: "type", label: "Type", render: (c: Any) => <span className="faint mono">{c.type}</span> },
                { key: "required", label: "Required", render: (c: Any) => c.required ? <span><span className="badge sev-High">required</span>{c.note && <span className="note"> {c.note}</span>}</span> : <span className="faint">optional</span> },
                { key: "aliases", label: "Also accepted as", render: (c: Any) => <span className="note">{c.aliases.join(", ") || "—"}</span> },
              ]} />
            </>
          );
        }}
      </QueryState>
    </Card>
  );
}

export default function UploadPage() {
  const qc = useQueryClient();
  const active = useApi("/v1/datasets/active");
  const jobs = useApi("/v1/datasets/jobs");
  const [picked, setPicked] = useState<Picked[]>([]);
  const [mode, setMode] = useState<"replace" | "append">("replace");
  const [uploadPct, setUploadPct] = useState<number | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<Any>(null);
  const [err, setErr] = useState<unknown>(null);
  const [drag, setDrag] = useState(false);
  const input = useRef<HTMLInputElement>(null);
  const maxMb = active.data?.limits?.max_file_mb ?? MAX_MB;

  // resume a job already running (e.g. started in another tab)
  useEffect(() => {
    const running = jobs.data?.items?.find((j: Any) => j.state === "running" || j.state === "queued");
    if (running && !jobId) setJobId(running.id);
  }, [jobs.data, jobId]);

  // poll the job until it finishes, then refresh every screen
  useEffect(() => {
    if (!jobId) return;
    let stop = false;
    const tick = async () => {
      try {
        const j = await api(`/v1/datasets/jobs/${jobId}`);
        if (stop) return;
        setJob(j);
        if (j.state === "succeeded" || j.state === "failed") {
          if (j.state === "succeeded") { await qc.invalidateQueries(); setPicked([]); }
          else qc.invalidateQueries({ queryKey: ["/v1/datasets/jobs"] });
          return;
        }
      } catch (e) { if (!stop) setErr(e); }
      if (!stop) setTimeout(tick, 700);
    };
    tick();
    return () => { stop = true; };
  }, [jobId, qc]);

  const add = (list: FileList | null) => {
    if (!list) return;
    const next = [...picked];
    Array.from(list).forEach((f) => { if (!next.some((p) => p.file.name === f.name && p.file.size === f.size)) next.push({ file: f, error: checkFile(f, maxMb) }); });
    setPicked(next.slice(0, 10));
    setErr(null);
  };
  const valid = picked.filter((p) => !p.error);
  const running = job && (job.state === "running" || job.state === "queued");
  const busy = uploadPct !== null || running;

  const submit = async () => {
    setErr(null); setJob(null); setJobId(null); setUploadPct(0);
    try {
      const j = await uploadWithProgress(valid.map((p) => p.file), mode, setUploadPct);
      setJob(j); setJobId(j.id);
    } catch (e) { setErr(e); } finally { setUploadPct(null); }
  };
  const restore = async () => {
    setErr(null); setJob(null);
    try { const j = await api("/v1/datasets/restore-sample", { method: "POST" }); setJob(j); setJobId(j.id); } catch (e) { setErr(e); }
  };

  return (
    <>
      <div className="page-head">
        <div>
          <div className="eyebrow">Module 8 · Upload Dataset</div>
          <h2>Analyse new real-time data</h2>
          <p>Upload fresh service-desk and endpoint-telemetry exports. DEX Sentinel validates and normalises them, re-runs
            sentiment scoring, telemetry correlation, diagnosis and outcome analytics, and refreshes every dashboard.</p>
        </div>
      </div>

      {active.data?.limits?.storage_mode === "ephemeral" && (
        <div className="callout" role="note" style={{ marginBottom: 14 }}>
          <div className="rk">Demo instance</div>
          Uploaded data is analysed and shown everywhere, but it resets to the sample dataset when the service restarts
          or is redeployed. Keep your source files to re-upload.
        </div>
      )}
      <div className="grid g-split">
        <Card title="Upload new data" sub={`.xlsx workbook (one sheet per table) or .csv files (one per table) · up to ${maxMb} MB each · max 10 files`}>
          <div className="row" style={{ marginBottom: 12 }}>
            <span className="field" style={{ margin: 0 }}>Mode</span>
            <div className="seg" role="radiogroup" aria-label="Upload mode">
              <button role="radio" aria-checked={mode === "replace"} className={mode === "replace" ? "on" : ""} onClick={() => setMode("replace")} disabled={!!busy}>Replace current dataset</button>
              <button role="radio" aria-checked={mode === "append"} className={mode === "append" ? "on" : ""} onClick={() => setMode("append")} disabled={!!busy}>Append to current dataset</button>
            </div>
          </div>
          <p className="note" style={{ marginTop: 0 }}>{mode === "replace"
            ? "Replace: the upload becomes the dataset. Needs telemetry and tickets; devices and remediations are optional."
            : "Append: new rows are merged into the current dataset by key (device + week, ticket id…); matching rows are updated. Ideal for weekly real-time feeds."}</p>

          <div className="dropzone" role="button" tabIndex={0} aria-label="Choose files to upload"
               style={{ borderColor: drag ? "var(--machine)" : undefined, background: drag ? "var(--panel-2)" : undefined, cursor: "pointer" }}
               onClick={() => !busy && input.current?.click()} onKeyDown={(e) => (e.key === "Enter" || e.key === " ") && !busy && input.current?.click()}
               onDragOver={(e) => { e.preventDefault(); setDrag(true); }} onDragLeave={() => setDrag(false)}
               onDrop={(e) => { e.preventDefault(); setDrag(false); if (!busy) add(e.dataTransfer.files); }}>
            <UploadCloud size={26} className="machine" />
            <div style={{ marginTop: 8, fontWeight: 600 }}>Drop files here or click to browse</div>
            <div className="note">Allowed: .xlsx, .csv · maximum {maxMb} MB per file</div>
            <input ref={input} type="file" accept=".xlsx,.csv" multiple hidden onChange={(e) => { add(e.target.files); e.target.value = ""; }} />
          </div>

          {picked.length > 0 && (
            <div className="grid mt" style={{ gap: 6 }}>
              {picked.map((p, i) => (
                <div key={p.file.name + i} className="card-flat row between" style={{ borderColor: p.error ? "var(--critical-dim)" : undefined }}>
                  <span className="row" style={{ gap: 8 }}>
                    {p.file.name.toLowerCase().endsWith(".csv") ? <FileText size={15} className="dim" /> : <FileSpreadsheet size={15} className="machine" />}
                    <span><b>{p.file.name}</b> <span className="faint mono" style={{ fontSize: 11 }}>{sizeLabel(p.file.size)}</span>
                      {p.error && <div className="crit" style={{ fontSize: 12 }}>{p.error}</div>}</span>
                  </span>
                  <button className="btn btn-ghost btn-sm" onClick={() => setPicked(picked.filter((_, j) => j !== i))} disabled={!!busy} aria-label={`Remove ${p.file.name}`}><X size={12} /></button>
                </div>
              ))}
            </div>
          )}

          <div className="row mt">
            <button className="btn btn-primary" onClick={submit} disabled={!valid.length || !!busy || picked.some((p) => p.error)}>
              {busy ? <Loader2 size={14} className="spin" /> : <UploadCloud size={14} />}Submit for Analysis
            </button>
            {picked.length > 0 && !busy && <button className="btn btn-ghost" onClick={() => setPicked([])}>Clear</button>}
            {picked.some((p) => p.error) && <span className="note crit">Remove the invalid file(s) to continue</span>}
          </div>
          {uploadPct !== null && (
            <div className="mt">
              <div className="row between note"><span>Uploading…</span><span className="mono">{uploadPct}%</span></div>
              <div className="bar-track"><div className="bar-fill" style={{ width: `${uploadPct}%` }} /></div>
            </div>
          )}
          {err ? <div className="mt"><ErrorBox error={err} /></div> : null}
        </Card>

        <Card title="Active dataset" sub="what every module is currently analysing">
          <QueryState q={active}>
            {(a: Any) => (
              <>
                <dl className="kv">
                  <dt>Source</dt><dd>{a.dataset?.source}</dd>
                  <dt>Loaded</dt><dd>{a.dataset?.loaded_at ? new Date(a.dataset.loaded_at + (a.dataset.loaded_at.endsWith("Z") || a.dataset.loaded_at.includes("+") ? "" : "Z")).toLocaleString() : "—"} <span className="faint">· version {a.dataset?.id}</span></dd>
                  <dt>Rows</dt><dd className="mono">{fmt.i(a.metrics.devices)} devices · {fmt.i(a.metrics.device_weeks)} device-weeks · {fmt.i(a.metrics.tickets)} tickets · {fmt.i(a.metrics.remediations)} remediations</dd>
                  <dt>Window</dt><dd className="mono">W{a.coverage.weeks[0]}–W{a.coverage.weeks[1]} · {a.coverage.week_dates[0]} → {a.coverage.week_dates[1]}</dd>
                  <dt>DEX Score</dt><dd><b>{fmt.n(a.metrics.dex_score)}</b> ({a.metrics.band}) · correlation r = {fmt.n(a.metrics.correlation_score, 2)}</dd>
                  <dt>Signals</dt><dd>{a.coverage.signals_present.map((s: string) => <span key={s} className="chip" style={{ margin: "0 4px 4px 0" }}>{s}</span>)}
                    {a.coverage.signals_missing.map((s: string) => <span key={s} className="chip faint" style={{ margin: "0 4px 4px 0", textDecoration: "line-through" }}>{s}</span>)}</dd>
                </dl>
                <div className="row mt">
                  <button className="btn btn-ghost btn-sm" onClick={() => downloadFile("/v1/datasets/sample.xlsx", "DEX_Sentinel_Simulated_Dataset.xlsx")}><Download size={13} />Sample workbook</button>
                  <button className="btn btn-ghost btn-sm" onClick={restore} disabled={!!busy}><RotateCcw size={13} />Restore sample dataset</button>
                </div>
              </>
            )}
          </QueryState>
        </Card>
      </div>

      {job && (
        <div className="grid g-split mt">
          <Card title="Analysis progress" sub={`job ${job.id} · ${job.state}${job.duration_sec ? ` · ${job.duration_sec}s` : ""}`}
                right={<span className="mono" style={{ fontWeight: 700 }}>{job.progress}%</span>}>
            <div className="bar-track" style={{ marginBottom: 14 }}><div className="bar-fill" style={{ width: `${job.progress}%`, background: job.state === "failed" ? "var(--critical)" : undefined }} /></div>
            <Stepper job={job} />
          </Card>
          {job.state === "failed" && (
            <Card title={<span className="row" style={{ gap: 8 }}><XCircle size={16} className="crit" />Analysis failed — the live dataset was not changed</span>}>
              <div className="error-box">{job.error}</div>
              {job.issues?.length > 0 && <ul style={{ margin: "10px 0 0 16px", padding: 0, fontSize: 13, lineHeight: 1.6 }}>{job.issues.map((i: string, k: number) => <li key={k}>{i}</li>)}</ul>}
              <div className="note mt">Check the column guide below, or download a CSV template for the expected layout.</div>
            </Card>
          )}
          {job.state === "running" && (
            <Card title="While you wait">
              <p className="note">The new dataset is built off to the side and swapped in only when analysis succeeds — dashboards keep
                serving the current data until then. Large files (hundreds of MB) typically take a minute or two.</p>
            </Card>
          )}
        </div>
      )}
      {job?.state === "succeeded" && job.result && <div className="mt"><Result job={job} /></div>}

      <div className="mt"><ColumnGuide /></div>

      <Card className="mt" title="Upload history" sub="recent analysis jobs this session">
        <QueryState q={jobs}>
          {(d: Any) => d.items.length ? (
            <DataTable rows={d.items} columns={[
              { key: "created_at", label: "Started", render: (j: Any) => new Date(j.created_at).toLocaleString() },
              { key: "files", label: "Files", render: (j: Any) => j.files.map((f: Any) => f.name).join(", ") },
              { key: "mode", label: "Mode" },
              { key: "state", label: "Result", render: (j: Any) => j.state === "succeeded" ? <span className="state-ok">succeeded</span> : j.state === "failed" ? <span className="state-critical">failed</span> : <span className="state-warn">{j.state}</span> },
              { key: "rows", label: "Rows", render: (j: Any) => j.result ? `${fmt.i(j.result.rows.tickets)} tickets · ${fmt.i(j.result.rows.telemetry)} telemetry` : "—" },
              { key: "duration_sec", label: "Time", num: true, render: (j: Any) => j.duration_sec ? `${j.duration_sec}s` : "—" },
            ]} />
          ) : <div className="empty">No uploads yet in this session</div>}
        </QueryState>
      </Card>
    </>
  );
}
