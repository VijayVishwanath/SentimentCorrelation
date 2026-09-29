import { AlertTriangle, ArrowDownRight, ArrowUpRight, CheckCircle2, CircleAlert, Info, Table2, BarChart3 } from "lucide-react";
import { ReactNode, useState } from "react";
import { ApiError, fmt } from "../api";

export function Card({ title, sub, right, children, className = "", style }: {
  title?: ReactNode; sub?: ReactNode; right?: ReactNode; children: ReactNode; className?: string; style?: React.CSSProperties;
}) {
  return (
    <section className={`card ${className}`} style={style}>
      {(title || right) && (
        <div className="card-head">
          <div>{title && <h3 className="card-title">{title}</h3>}{sub && <div className="card-sub">{sub}</div>}</div>
          {right}
        </div>
      )}
      {children}
    </section>
  );
}

export interface Column<T> { key: string; label: string; num?: boolean; render?: (row: T) => ReactNode; width?: string }

export function DataTable<T extends Record<string, unknown>>({ rows, columns, onRow, max }: {
  rows: T[]; columns: Column<T>[]; onRow?: (r: T) => void; max?: number;
}) {
  const shown = max ? rows.slice(0, max) : rows;
  if (!rows.length) return <div className="empty">No rows</div>;
  return (
    <div className="table-wrap">
      <table className="t">
        <thead><tr>{columns.map((c) => <th key={c.key} className={c.num ? "num" : ""} style={{ width: c.width }}>{c.label}</th>)}</tr></thead>
        <tbody>
          {shown.map((r, i) => (
            <tr key={i} className={onRow ? "click" : ""} onClick={onRow ? () => onRow(r) : undefined}
                tabIndex={onRow ? 0 : undefined} onKeyDown={onRow ? (e) => e.key === "Enter" && onRow(r) : undefined}>
              {columns.map((c) => <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(r) : String(r[c.key] ?? "—")}</td>)}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** Chart container with a table-view twin (accessibility: every value is readable without hover). */
export function ChartCard<T extends Record<string, unknown>>({ title, sub, table, columns, children, right, className = "" }: {
  title: ReactNode; sub?: ReactNode; table?: T[]; columns?: Column<T>[]; children: ReactNode; right?: ReactNode; className?: string;
}) {
  const [asTable, setAsTable] = useState(false);
  const toggle = table && columns ? (
    <button className="btn btn-ghost btn-sm" onClick={() => setAsTable(!asTable)} aria-pressed={asTable}
            title={asTable ? "Show chart" : "Show data table"}>
      {asTable ? <BarChart3 size={13} /> : <Table2 size={13} />}{asTable ? "Chart" : "Table"}
    </button>
  ) : null;
  return (
    <Card title={title} sub={sub} className={className} right={<div className="row">{right}{toggle}</div>}>
      {asTable && table && columns ? <DataTable rows={table} columns={columns} /> : children}
    </Card>
  );
}

export function Kpi({ label, value, unit, delta, deltaLabel, goodWhen = "up", accent, icon, hint }: {
  label: string; value: ReactNode; unit?: string; delta?: number | null; deltaLabel?: string;
  goodWhen?: "up" | "down"; accent?: string; icon?: ReactNode; hint?: string;
}) {
  let cls = "";
  if (delta !== undefined && delta !== null && delta !== 0) {
    const good = goodWhen === "up" ? delta > 0 : delta < 0;
    cls = good ? "up" : "down";
  }
  return (
    <div className="card kpi" style={{ ["--accent" as string]: accent }} title={hint}>
      <div className="k">{icon}{label}</div>
      <div className="v">{value}{unit && value !== "—" && <small>{unit}</small>}</div>
      {(deltaLabel || delta !== undefined) && (
        <div className={`d ${cls}`}>
          {delta !== undefined && delta !== null && delta !== 0 && (delta > 0 ? <ArrowUpRight size={13} /> : <ArrowDownRight size={13} />)}
          {deltaLabel}
        </div>
      )}
    </div>
  );
}

export function Loading({ label = "Loading…" }: { label?: string }) { return <div className="loading">{label}</div>; }

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof ApiError ? `${error.message} (HTTP ${error.status})` : String((error as Error)?.message || error);
  return <div className="error-box" role="alert"><AlertTriangle size={14} style={{ verticalAlign: -2, marginRight: 6 }} />{msg}</div>;
}

export function QueryState({ q, children }: { q: { isLoading: boolean; error: unknown; data: unknown; isPlaceholderData?: boolean }; children: (d: never) => ReactNode }) {
  if (q.isLoading) return <Loading />;
  if (q.error && !q.data) return <ErrorBox error={q.error} />;
  if (!q.data) return <Loading />;
  return <div className={q.isPlaceholderData ? "stale" : ""}>{children(q.data as never)}</div>;
}

export function SevBadge({ sev }: { sev: string }) {
  const Icon = sev === "Critical" ? CircleAlert : sev === "High" ? AlertTriangle : sev === "Medium" ? Info : CheckCircle2;
  return <span className={`badge sev-${sev}`}><Icon size={11} />{sev}</span>;
}

export function StateText({ state, children }: { state: string; children: ReactNode }) {
  const Icon = state === "critical" ? CircleAlert : state === "warn" ? AlertTriangle : CheckCircle2;
  return <span className={`state-${state}`}><Icon size={12} style={{ verticalAlign: -1, marginRight: 4 }} />{children}</span>;
}

export function Meter({ value, max = 100, color = "var(--chart-machine)", label }: { value: number; max?: number; color?: string; label?: ReactNode }) {
  return (
    <div className="meter">
      <div className="bar-track" role="meter" aria-valuenow={value} aria-valuemin={0} aria-valuemax={max}>
        <div className="bar-fill" style={{ width: `${Math.max(0, Math.min(100, (100 * value) / max))}%`, background: color }} />
      </div>
      {label}
    </div>
  );
}

export function PrePost({ pre, post, lowerIsBetter = true, d = 1, suffix = "" }: { pre: number; post: number; lowerIsBetter?: boolean; d?: number; suffix?: string }) {
  const improved = lowerIsBetter ? post <= pre : post >= pre;
  return (
    <span className="pair">
      {fmt.n(pre, d)}{suffix}<span className="arrow">→</span>
      <span className={improved ? "good" : "crit"}>{fmt.n(post, d)}{suffix}</span>
    </span>
  );
}

// ---------------------------------------------------------------- heatmaps (sequential: one hue, light->dark)
const SEQ = ["var(--seq-0)", "var(--seq-1)", "var(--seq-2)", "var(--seq-3)", "var(--seq-4)", "var(--seq-5)"];
export function seqColor(v: number | null | undefined, max: number): string {
  if (v === null || v === undefined || max <= 0) return "var(--panel-2)";
  const i = Math.min(SEQ.length - 1, Math.floor((v / max) * (SEQ.length - 1) + 0.0001));
  return SEQ[i];
}
function seqInk(v: number | null | undefined, max: number): string {
  if (v === null || v === undefined || max <= 0) return "var(--text-faint)";
  return v / max > 0.55 ? "#ffffff" : "var(--text)";
}

export function Heatmap({ rows, cols, value, label, tooltip, max, minCol = 44 }: {
  rows: string[]; cols: { key: string; label: string }[]; value: (r: string, c: string) => number | null | undefined;
  label?: (v: number | null | undefined) => string; tooltip?: (r: string, c: string) => string; max?: number; minCol?: number;
}) {
  const all = rows.flatMap((r) => cols.map((c) => value(r, c.key) ?? 0));
  const m = max ?? Math.max(1, ...all);
  return (
    <div>
      <div className="heat" style={{ gridTemplateColumns: `minmax(80px, auto) repeat(${cols.length}, minmax(${minCol}px, 1fr))` }}>
        <div />
        {cols.map((c) => <div key={c.key} className="hdr">{c.label}</div>)}
        {rows.map((r) => (
          <FragmentRow key={r} r={r} cols={cols} value={value} m={m} label={label} tooltip={tooltip} />
        ))}
      </div>
      <SeqLegend max={m} format={label} />
    </div>
  );
}
function FragmentRow({ r, cols, value, m, label, tooltip }: { r: string; cols: { key: string; label: string }[]; value: (r: string, c: string) => number | null | undefined; m: number; label?: (v: number | null | undefined) => string; tooltip?: (r: string, c: string) => string }) {
  return (
    <>
      <div className="rowh">{r}</div>
      {cols.map((c) => {
        const v = value(r, c.key);
        return (
          <div key={c.key} className="cell" style={{ background: seqColor(v, m), color: seqInk(v, m) }}
               title={tooltip ? tooltip(r, c.key) : undefined} tabIndex={0} aria-label={tooltip ? tooltip(r, c.key) : `${r} ${c.label}: ${v}`}>
            {label ? label(v) : v ?? "—"}
          </div>
        );
      })}
    </>
  );
}
export function SeqLegend({ max, format }: { max: number; format?: (v: number) => string }) {
  return (
    <div className="row mt" style={{ gap: 6, fontSize: 11, color: "var(--text-faint)" }}>
      <span>{format ? format(0) : 0}</span>
      {SEQ.map((c, i) => <span key={i} style={{ width: 22, height: 8, background: c, borderRadius: 2 }} />)}
      <span>{format ? format(max) : Math.round(max)}</span>
    </div>
  );
}

// ---------------------------------------------------------------- diverging correlation matrix (blue <-> gray <-> red)
export function divColor(r: number | null | undefined): string {
  if (r === null || r === undefined) return "var(--panel-2)";
  const a = Math.min(1, Math.abs(r) / 0.8);
  const pole = r >= 0 ? "var(--div-pos)" : "var(--div-neg)";
  return `color-mix(in oklab, ${pole} ${Math.round(a * 100)}%, var(--div-mid))`;
}

export function CorrMatrix({ matrix }: { matrix: { columns: { key: string; label: string }[]; rows: { signal: string; label: string; grain: string; cells: { telemetry: string; pearson: number | null; p_value: number | null; n: number }[] }[] } }) {
  return (
    <div>
      <div className="heat" style={{ gridTemplateColumns: `minmax(170px, auto) repeat(${matrix.columns.length}, minmax(52px, 1fr))` }}>
        <div className="hdr" style={{ placeItems: "end start" }}>experience ↓ / telemetry →</div>
        {matrix.columns.map((c) => <div key={c.key} className="hdr">{c.label}</div>)}
        {matrix.rows.map((row) => (
          <FragmentMatrixRow key={row.signal + row.grain} row={row} />
        ))}
      </div>
      <div className="row mt" style={{ gap: 6, fontSize: 11, color: "var(--text-faint)" }}>
        <span>r = −0.8</span>
        {[-0.8, -0.4, 0, 0.4, 0.8].map((v) => <span key={v} style={{ width: 26, height: 8, background: divColor(v), borderRadius: 2 }} />)}
        <span>+0.8</span>
        <span style={{ marginLeft: 12 }}>· = not significant (p ≥ 0.05)</span>
      </div>
    </div>
  );
}
function FragmentMatrixRow({ row }: { row: { signal: string; label: string; grain: string; cells: { telemetry: string; pearson: number | null; p_value: number | null; n: number }[] } }) {
  return (
    <>
      <div className="rowh">{row.label}<span className="faint mono" style={{ fontSize: 10, marginLeft: 6 }}>{row.grain}</span></div>
      {row.cells.map((c) => {
        const sig = c.p_value !== null && c.p_value < 0.05;
        const strong = c.pearson !== null && Math.abs(c.pearson) > 0.45;
        return (
          <div key={c.telemetry} className="cell" style={{ background: divColor(c.pearson), color: strong ? "#fff" : "var(--text)" }}
               title={`${row.label} × ${c.telemetry}: r = ${c.pearson ?? "n/a"}, p = ${c.p_value ?? "n/a"}, n = ${c.n}`} tabIndex={0}>
            {c.pearson === null ? "—" : `${c.pearson.toFixed(2)}${sig ? "" : "·"}`}
          </div>
        );
      })}
    </>
  );
}

export function ChartTip({ active, payload, label, title, fmtValue }: {
  active?: boolean; payload?: { name: string; value: number; color?: string; dataKey?: string }[]; label?: string | number;
  title?: (l: string | number | undefined) => string; fmtValue?: (v: number, key?: string) => string;
}) {
  if (!active || !payload?.length) return null;
  return (
    <div className="tip">
      <div className="tt">{title ? title(label) : label}</div>
      {payload.map((p) => (
        <div className="tr" key={p.dataKey || p.name}>
          <span><i style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: p.color, marginRight: 6 }} />{p.name}</span>
          <b>{fmtValue ? fmtValue(p.value, p.dataKey) : typeof p.value === "number" ? fmt.n(p.value) : String(p.value)}</b>
        </div>
      ))}
    </div>
  );
}
