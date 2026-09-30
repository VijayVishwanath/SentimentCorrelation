import { AlertTriangle, Loader2, ArrowDown, ArrowDownRight, ArrowUp, ArrowUpDown, ArrowUpRight, BarChart3, CheckCircle2, ChevronLeft,
  ChevronRight, ChevronsLeft, ChevronsRight, CircleAlert, Info, Table2 } from "lucide-react";
import { ReactNode, useEffect, useMemo, useState } from "react";
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

export interface Column<T> {
  key: string; label: string; num?: boolean; render?: (row: T) => ReactNode; width?: string;
  /** Header sorting (on by default when the table is sortable; false for action / composite columns). */
  sortable?: boolean;
  /** Value used for client-side sorting and filtering when the cell is rendered (defaults to row[key]). */
  value?: (row: T) => unknown;
  /** Header filter: text = contains, select = equals, num = ">=60", "<=40", "=3" (a bare number means >=). */
  filter?: "text" | "select" | "num";
  options?: string[];
  optionLabels?: Record<string, string>;
}

export type SortState = { key: string; dir: "asc" | "desc" } | null;

/** Server-paged mode: the parent owns sort / filters / page and fetches the current page from the API. */
export interface ServerTable {
  total: number; page: number; setPage: (p: number) => void;
  sort: SortState; setSort: (s: SortState) => void;
  filters: Record<string, string>; setFilter: (key: string, value: string) => void;
  options?: Record<string, string[]>;
}

/** State for a server-paged DataTable: returns the API query params and the `server` prop for the table. */
export function useServerTable(pageSize = 5) {
  const [page, setPage] = useState(0);
  const [sort, setSortState] = useState<SortState>(null);
  const [filters, setFilters] = useState<Record<string, string>>({});
  const params: Record<string, string | number | undefined> = {
    limit: pageSize, offset: page * pageSize, sort_by: sort?.key, order: sort?.dir,
    ...Object.fromEntries(Object.entries(filters).filter(([, v]) => v).map(([k, v]) => [`f_${k}`, v])),
  };
  const table = (total: number, options?: Record<string, string[]>): ServerTable => ({
    total, page, setPage, options, filters, sort,
    setSort: (s) => { setSortState(s); setPage(0); },
    setFilter: (k, v) => { setFilters((f) => ({ ...f, [k]: v })); setPage(0); },
  });
  return { params, table, reset: () => setPage(0) };
}

function numMatch(v: unknown, raw: string): boolean {
  const op = [">=", "<=", ">", "<", "="].find((o) => raw.startsWith(o)) || ">=";
  const x = parseFloat(raw.startsWith(op) ? raw.slice(op.length) : raw);
  const n = typeof v === "number" ? v : parseFloat(String(v));
  if (Number.isNaN(x)) return true;
  if (Number.isNaN(n)) return false;
  return op === ">=" ? n >= x : op === "<=" ? n <= x : op === ">" ? n > x : op === "<" ? n < x : n === x;
}

function cmp(a: unknown, b: unknown): number {
  const empty = (v: unknown) => v === null || v === undefined || v === "" || (typeof v === "number" && Number.isNaN(v));
  if (empty(a) || empty(b)) return empty(a) === empty(b) ? 0 : empty(a) ? 1 : -1;  // blanks last
  if (typeof a === "number" && typeof b === "number") return a - b;
  if (typeof a === "boolean" && typeof b === "boolean") return Number(a) - Number(b);
  return String(a).localeCompare(String(b), undefined, { numeric: true, sensitivity: "base" });
}

/** Text filter input that waits for typing to pause before applying (avoids one request per keystroke). */
function FilterInput({ value, onChange, placeholder, label }: { value: string; onChange: (v: string) => void; placeholder: string; label: string }) {
  const [v, setV] = useState(value);
  useEffect(() => setV(value), [value]);
  useEffect(() => {
    if (v === value) return;
    const t = setTimeout(() => onChange(v), 300);
    return () => clearTimeout(t);
  }, [v]);  // eslint-disable-line react-hooks/exhaustive-deps
  return <input value={v} onChange={(e) => setV(e.target.value)} placeholder={placeholder} aria-label={`Filter ${label}`} />;
}

export function Pager({ page, pageSize, total, setPage }: { page: number; pageSize: number; total: number; setPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  if (total <= pageSize) return total ? <div className="pager"><span className="note">{total} row{total === 1 ? "" : "s"}</span></div> : null;
  return (
    <div className="pager">
      <span className="note">Showing {page * pageSize + 1}–{Math.min(total, (page + 1) * pageSize)} of {total.toLocaleString()}</span>
      <div className="row" style={{ gap: 6 }}>
        <button className="btn btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage(0)} aria-label="First page"><ChevronsLeft size={13} /></button>
        <button className="btn btn-ghost btn-sm" disabled={page === 0} onClick={() => setPage(page - 1)}><ChevronLeft size={13} />Prev {pageSize}</button>
        <span className="mono" style={{ fontSize: 12 }}>Page {page + 1} / {pages.toLocaleString()}</span>
        <button className="btn btn-ghost btn-sm" disabled={page >= pages - 1} onClick={() => setPage(page + 1)}>Next {pageSize}<ChevronRight size={13} /></button>
        <button className="btn btn-ghost btn-sm" disabled={page >= pages - 1} onClick={() => setPage(pages - 1)} aria-label="Last page"><ChevronsRight size={13} /></button>
      </div>
    </div>
  );
}

export function DataTable<T extends Record<string, unknown>>({ rows, columns, onRow, max, pageSize, sortable, server }: {
  rows: T[]; columns: Column<T>[]; onRow?: (r: T) => void; max?: number;
  /** Show this many rows per page with Prev / Next paging. */
  pageSize?: number;
  /** Clickable column headers (client-side unless `server` is given). */
  sortable?: boolean;
  server?: ServerTable;
}) {
  const [cSort, setCSort] = useState<SortState>(null);
  const [cFilters, setCFilters] = useState<Record<string, string>>({});
  const [cPage, setCPage] = useState(0);
  const sort = server ? server.sort : cSort;
  const flt = server ? server.filters : cFilters;
  const page = server ? server.page : cPage;
  const canSort = !!(sortable || server);
  const hasFilters = columns.some((c) => c.filter);
  const val = (c: Column<T>, r: T) => (c.value ? c.value(r) : r[c.key]);

  const view = useMemo(() => {
    if (server) return rows;
    let out = rows;
    for (const c of columns) {
      const raw = (cFilters[c.key] || "").trim();
      if (!raw || !c.filter) continue;
      out = out.filter((r) => {
        const v = val(c, r);
        if (c.filter === "num") return numMatch(v, raw);
        if (c.filter === "select") return String(v ?? "") === raw;
        return String(v ?? "").toLowerCase().includes(raw.toLowerCase());
      });
    }
    if (cSort) {
      const c = columns.find((x) => x.key === cSort.key);
      if (c) out = [...out].sort((a, b) => cmp(val(c, a), val(c, b)) * (cSort.dir === "asc" ? 1 : -1));
    }
    return out;
  }, [rows, columns, cFilters, cSort, server]);  // eslint-disable-line react-hooks/exhaustive-deps

  const total = server ? server.total : view.length;
  const size = pageSize || 0;
  const shown = server ? view : size ? view.slice(page * size, page * size + size) : max ? view.slice(0, max) : view;
  const setPage = server ? server.setPage : setCPage;
  const setSort = (key: string) => {
    const next: SortState = sort?.key !== key ? { key, dir: "asc" } : sort.dir === "asc" ? { key, dir: "desc" } : null;
    if (server) server.setSort(next); else { setCSort(next); setCPage(0); }
  };
  const setFilter = (key: string, v: string) => {
    if (server) server.setFilter(key, v); else { setCFilters((f) => ({ ...f, [key]: v })); setCPage(0); }
  };
  const optionsFor = (c: Column<T>) => c.options || server?.options?.[c.key]
    || [...new Set(rows.map((r) => String(val(c, r) ?? "")).filter(Boolean))].sort();
  const activeFilters = Object.values(flt).filter((v) => v && v.trim()).length;

  if (!rows.length && !hasFilters && !activeFilters) return <div className="empty">No rows</div>;
  return (
    <div>
      <div className="table-wrap">
        <table className="t">
          <thead>
            <tr>{columns.map((c) => {
              const on = canSort && c.sortable !== false && !!c.label;
              const dir = sort?.key === c.key ? sort.dir : null;
              return (
                <th key={c.key} className={c.num ? "num" : ""} style={{ width: c.width }}
                    aria-sort={dir ? (dir === "asc" ? "ascending" : "descending") : undefined}>
                  {on ? (
                    <button className="th-sort" onClick={() => setSort(c.key)} title="Sort">
                      {c.label}{dir === "asc" ? <ArrowUp size={11} /> : dir === "desc" ? <ArrowDown size={11} /> : <ArrowUpDown size={11} className="faint" />}
                    </button>
                  ) : c.label}
                </th>
              );
            })}</tr>
            {hasFilters && (
              <tr className="filters">{columns.map((c) => (
                <th key={c.key}>
                  {c.filter === "select" ? (
                    <select value={flt[c.key] || ""} onChange={(e) => setFilter(c.key, e.target.value)} aria-label={`Filter ${c.label}`}>
                      <option value="">All</option>
                      {optionsFor(c).map((o) => <option key={o} value={o}>{c.optionLabels?.[o] ?? o}</option>)}
                    </select>
                  ) : c.filter ? (
                    <FilterInput value={flt[c.key] || ""} onChange={(v) => setFilter(c.key, v)} label={c.label}
                                 placeholder={c.filter === "num" ? "≥ value" : "contains…"} />
                  ) : null}
                </th>
              ))}</tr>
            )}
          </thead>
          <tbody>
            {shown.map((r, i) => (
              <tr key={i} className={onRow ? "click" : ""} onClick={onRow ? () => onRow(r) : undefined}
                  tabIndex={onRow ? 0 : undefined} onKeyDown={onRow ? (e) => e.key === "Enter" && onRow(r) : undefined}>
                {columns.map((c) => <td key={c.key} className={c.num ? "num" : ""}>{c.render ? c.render(r) : String(r[c.key] ?? "—")}</td>)}
              </tr>
            ))}
            {!shown.length && <tr><td colSpan={columns.length} className="empty">No rows match these filters</td></tr>}
          </tbody>
        </table>
      </div>
      {(size > 0 || server) && (
        <div className="row between" style={{ marginTop: 8 }}>
          <Pager page={page} pageSize={size || 5} total={total} setPage={setPage} />
          {activeFilters > 0 && (
            <button className="btn btn-ghost btn-sm" onClick={() => columns.forEach((c) => flt[c.key] && setFilter(c.key, ""))}>
              Clear filters ({activeFilters})</button>
          )}
        </div>
      )}
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

export function Kpi({ label, value, unit, delta, deltaLabel, goodWhen = "up", accent, icon, hint, tag }: {
  label: string; value: ReactNode; unit?: string; delta?: number | null; deltaLabel?: string;
  goodWhen?: "up" | "down"; accent?: string; icon?: ReactNode; hint?: string; tag?: ReactNode;
}) {
  let cls = "";
  if (delta !== undefined && delta !== null && delta !== 0) {
    const good = goodWhen === "up" ? delta > 0 : delta < 0;
    cls = good ? "up" : "down";
  }
  return (
    <div className="card kpi" style={{ ["--accent" as string]: accent }} title={hint}>
      <div className="k">{icon}{label}{tag}</div>
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

export function Loading({ label = "Loading…" }: { label?: string }) {
  return <div className="loading" role="status"><Loader2 size={14} className="spin" style={{ verticalAlign: -2, marginRight: 8 }} />{label}</div>;
}

export function ErrorBox({ error }: { error: unknown }) {
  const msg = error instanceof ApiError ? `${error.message} (HTTP ${error.status})` : String((error as Error)?.message || error);
  return <div className="error-box" role="alert"><AlertTriangle size={14} style={{ verticalAlign: -2, marginRight: 6 }} />{msg}</div>;
}

/** label: what is being computed, for views that take a few seconds (shown with a spinner). */
export function QueryState({ q, children, label }: { q: { isLoading: boolean; error: unknown; data: unknown; isPlaceholderData?: boolean }; children: (d: never) => ReactNode; label?: string }) {
  if (q.isLoading || (!q.data && !q.error)) return <Loading label={label} />;
  if (q.error && !q.data) return <ErrorBox error={q.error} />;
  return (
    <div className={q.isPlaceholderData ? "stale-wrap" : ""} aria-busy={q.isPlaceholderData || undefined}>
      {q.isPlaceholderData && <div className="updating" role="status"><Loader2 size={12} className="spin" />Updating…</div>}
      <div className={q.isPlaceholderData ? "stale" : ""}>{children(q.data as never)}</div>
    </div>
  );
}

/** Every dollar figure says which kind it is, so the pages never seem to disagree. */
export const MONEY_KIND: Record<string, [string, string]> = {
  realised: ["Realised", "Value of fixes already made, counting only what they caused (vs matched never-fixed devices)"],
  planned: ["Planned", "Projected yearly value of the recommended fixes, if they are carried out"],
  preventable: ["Preventable", "Yearly cost of these issues × the ticket reduction past fixes of the same kind achieved"],
  proactive: ["Proactive", "Next week's forecast risk × the effect of the recommended fix, for the watchlist"],
  naive: ["Naive", "Before vs after with no control group: overstates what the fix caused"],
};
export function MoneyChip({ kind }: { kind: keyof typeof MONEY_KIND }) {
  const [label, tip] = MONEY_KIND[kind];
  return <span className="chip money-chip" title={tip} aria-label={`${label}: ${tip}`}>{label}</span>;
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
