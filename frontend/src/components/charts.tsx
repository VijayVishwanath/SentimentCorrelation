import {
  Bar, BarChart, CartesianGrid, Cell, ComposedChart, LabelList, Legend, Line, LineChart, ReferenceLine,
  ResponsiveContainer, Scatter, Tooltip, XAxis, YAxis, ZAxis,
} from "recharts";
import { fmt } from "../api";
import { ChartTip } from "./ui";

const AXIS = { stroke: "var(--chart-axis)", tick: { fill: "var(--text-faint)", fontSize: 11, fontFamily: "var(--font-mono)" }, tickLine: false };
const GRID = <CartesianGrid stroke="var(--chart-grid)" vertical={false} />;
/** Axis ticks: drop trailing ".0" so labels stay short and never clip. */
const tickOf = (f?: (v: number) => string) => (v: number) => (f ? f(v) : String(v)).replace(/\.0(?=\D*$)/, "");

export interface Series { key: string; name: string; color: string }

export function TrendChart({ data, series, x = "week", height = 220, yDomain, xFmt = (v) => `W${v}`, yFmt, refLine }: {
  data: Record<string, unknown>[]; series: Series[]; x?: string; height?: number; yDomain?: [number | "auto", number | "auto"];
  xFmt?: (v: string | number) => string; yFmt?: (v: number) => string; refLine?: { y: number; label: string };
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <LineChart data={data} margin={{ top: 10, right: 16, left: -8, bottom: 0 }}>
        {GRID}
        <XAxis dataKey={x} {...AXIS} tickFormatter={xFmt} />
        <YAxis {...AXIS} axisLine={false} domain={yDomain || ["auto", "auto"]} tickFormatter={tickOf(yFmt)} width={48} />
        <Tooltip cursor={{ stroke: "var(--text-faint)", strokeWidth: 1 }}
                 content={<ChartTip title={(l) => (l !== undefined ? xFmt(l) : "")} fmtValue={(v) => (yFmt ? yFmt(v) : fmt.n(v))} />} />
        {series.length > 1 && <Legend iconType="plainline" wrapperStyle={{ fontSize: 11.5, color: "var(--text-dim)" }} />}
        {refLine && <ReferenceLine y={refLine.y} stroke="var(--text-faint)" label={{ value: refLine.label, fill: "var(--text-faint)", fontSize: 10, position: "insideTopRight" }} />}
        {series.map((s) => (
          <Line isAnimationActive={false} key={s.key} type="monotone" dataKey={s.key} name={s.name} stroke={s.color} strokeWidth={2}
                dot={{ r: 2.5, strokeWidth: 0, fill: s.color }} activeDot={{ r: 5, stroke: "var(--panel)", strokeWidth: 2 }} connectNulls />
        ))}
      </LineChart>
    </ResponsiveContainer>
  );
}

/** Single-series bars; optional emphasis on one bar (others recede) — never a value ramp on nominal categories. */
export function Bars({ data, x, y, name, color = "var(--chart-machine)", height = 220, emphasize, yFmt, horizontal = false, labels = false, xWidth = 110 }: {
  data: Record<string, unknown>[]; x: string; y: string; name: string; color?: string; height?: number;
  emphasize?: (row: Record<string, unknown>, i: number) => boolean; yFmt?: (v: number) => string; horizontal?: boolean; labels?: boolean; xWidth?: number;
}) {
  const f = yFmt || ((v: number) => fmt.n(v));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} layout={horizontal ? "vertical" : "horizontal"} margin={{ top: 16, right: 30, left: horizontal ? 0 : -4, bottom: 0 }} barCategoryGap="22%">
        <CartesianGrid stroke="var(--chart-grid)" vertical={horizontal} horizontal={!horizontal} />
        {horizontal ? (
          <>
            <XAxis type="number" {...AXIS} tickFormatter={tickOf(f)} />
            <YAxis type="category" dataKey={x} {...AXIS} width={xWidth} tick={{ ...AXIS.tick, fontFamily: "var(--font-sans)", fontSize: 11.5 }} />
          </>
        ) : (
          <>
            <XAxis dataKey={x} {...AXIS} interval={0} />
            <YAxis {...AXIS} axisLine={false} tickFormatter={tickOf(f)} width={52} />
          </>
        )}
        <Tooltip cursor={{ fill: "var(--panel-3)", opacity: 0.5 }} content={<ChartTip fmtValue={(v) => f(v)} />} />
        <Bar isAnimationActive={false} dataKey={y} name={name} fill={color} radius={horizontal ? [0, 4, 4, 0] : [4, 4, 0, 0]} maxBarSize={46}>
          {emphasize && data.map((row, i) => <Cell key={i} fill={color} fillOpacity={emphasize(row, i) ? 1 : 0.38} />)}
          {labels && <LabelList dataKey={y} position={horizontal ? "right" : "top"} formatter={(v: number) => f(v)}
                                style={{ fill: "var(--text-dim)", fontSize: 10.5, fontFamily: "var(--font-mono)" }} />}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

/** Frustration-by-telemetry-bucket bars (prototype chart), with n below each bucket. */
export function BucketBars({ buckets, height = 170, color = "var(--chart-human)", yFmt }: {
  buckets: { label: string; value: number; count: number }[]; height?: number; color?: string; yFmt?: (v: number) => string;
}) {
  const max = Math.max(...buckets.map((b) => b.value));
  const data = buckets.map((b) => ({ ...b, tick: `${b.label}\nn=${b.count}` }));
  const f = yFmt || ((v: number) => fmt.n(v));
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 18, right: 6, left: -14, bottom: 8 }} barCategoryGap="20%">
        {GRID}
        <XAxis dataKey="label" {...AXIS} interval={0} height={34}
               tick={(p: { x: number; y: number; payload: { value: string; index: number } }) => (
                 <g transform={`translate(${p.x},${p.y + 10})`}>
                   <text textAnchor="middle" fill="var(--text-dim)" fontSize={10.5} fontFamily="var(--font-mono)">{p.payload.value}</text>
                   <text textAnchor="middle" y={13} fill="var(--text-faint)" fontSize={9.5} fontFamily="var(--font-mono)">n={buckets[p.payload.index]?.count}</text>
                 </g>
               )} />
        <YAxis {...AXIS} axisLine={false} width={40} tickFormatter={tickOf((v) => String(Math.round(v)))} />
        <Tooltip cursor={{ fill: "var(--panel-3)", opacity: 0.5 }} content={<ChartTip fmtValue={(v) => f(v)} />} />
        <Bar isAnimationActive={false} dataKey="value" name="Avg frustration" radius={[4, 4, 0, 0]} maxBarSize={42}>
          {data.map((b, i) => <Cell key={i} fill={color} fillOpacity={b.count === 0 ? 0.15 : b.value === max ? 1 : 0.45} />)}
          <LabelList dataKey="value" position="top" formatter={(v: number) => f(v)} style={{ fill: "var(--text)", fontSize: 10.5, fontFamily: "var(--font-mono)" }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function PrePostBars({ data, height = 240 }: { data: { name: string; pre: number; post: number }[]; height?: number }) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 16, right: 10, left: -8, bottom: 0 }} barGap={2} barCategoryGap="24%">
        {GRID}
        <XAxis dataKey="name" {...AXIS} interval={0} />
        <YAxis {...AXIS} axisLine={false} width={40} domain={[0, 100]} />
        <Tooltip cursor={{ fill: "var(--panel-3)", opacity: 0.5 }} content={<ChartTip />} />
        <Legend wrapperStyle={{ fontSize: 11.5 }} />
        <Bar isAnimationActive={false} dataKey="pre" name="Before remediation" fill="var(--chart-neutral)" radius={[4, 4, 0, 0]} maxBarSize={30} />
        <Bar isAnimationActive={false} dataKey="post" name="After remediation" fill="var(--chart-machine)" radius={[4, 4, 0, 0]} maxBarSize={30}>
          <LabelList dataKey="post" position="top" formatter={(v: number) => fmt.n(v)} style={{ fill: "var(--text-dim)", fontSize: 10.5, fontFamily: "var(--font-mono)" }} />
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}

export function ScatterFit({ points, fit, xLabel, height = 280 }: {
  points: { x: number; y: number; ticket_id: string; category: string }[]; fit: { slope: number; intercept: number } | null;
  xLabel: string; height?: number;
}) {
  const xs = points.map((p) => p.x);
  const x0 = Math.min(...xs), x1 = Math.max(...xs);
  const line = fit ? [{ x: x0, fy: fit.intercept + fit.slope * x0 }, { x: x1, fy: fit.intercept + fit.slope * x1 }] : [];
  return (
    <ResponsiveContainer width="100%" height={height}>
      <ComposedChart margin={{ top: 10, right: 16, left: -8, bottom: 16 }}>
        <CartesianGrid stroke="var(--chart-grid)" />
        <XAxis type="number" dataKey="x" {...AXIS} domain={["auto", "auto"]} name={xLabel}
               label={{ value: xLabel, position: "insideBottom", offset: -8, fill: "var(--text-faint)", fontSize: 11 }} />
        <YAxis type="number" dataKey="y" {...AXIS} axisLine={false} domain={[0, 100]} width={44} name="Frustration" />
        <ZAxis range={[36, 36]} />
        <Tooltip cursor={{ strokeDasharray: undefined, stroke: "var(--text-faint)" }}
                 content={({ active, payload }) => {
                   const p = (payload as unknown as { payload: { ticket_id?: string; category?: string; x: number; y: number } }[] | undefined)?.[0]?.payload;
                   if (!active || !p || !p.ticket_id) return null;
                   return <div className="tip"><div className="tt">{p.ticket_id} · {p.category}</div>
                     <div className="tr"><span>{xLabel}</span><b>{fmt.n(p.x)}</b></div>
                     <div className="tr"><span>Frustration</span><b>{fmt.n(p.y, 0)}</b></div></div>;
                 }} />
        <Scatter isAnimationActive={false} data={points} fill="var(--chart-human)" fillOpacity={0.55} stroke="var(--panel)" strokeWidth={1} />
        {fit && <Line data={line} dataKey="fy" type="linear" stroke="var(--chart-machine)" strokeWidth={2} dot={false} activeDot={false} legendType="none" isAnimationActive={false} />}
      </ComposedChart>
    </ResponsiveContainer>
  );
}
