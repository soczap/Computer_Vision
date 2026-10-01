// Chart primitives following the dataviz method: thin marks, recessive grid, one axis,
// hover tooltips, text in ink tokens (never series colour), direct labels where useful.
import type { ReactNode } from "react";
import {
  Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, ResponsiveContainer, Tooltip, XAxis, YAxis,
} from "recharts";
import { cx } from "./ui";

const AXIS = { stroke: "#383835", tick: { fill: "#898781", fontSize: 11 }, tickLine: false } as const;

export function StatTile({ label, value, sub, tone, icon }: {
  label: string; value: ReactNode; sub?: ReactNode; tone?: string; icon?: ReactNode;
}) {
  return (
    <div className="card flex min-w-0 flex-col gap-1 px-4 py-3">
      <div className="flex items-center gap-1.5 text-[11.5px] font-medium text-muted">
        {icon && <span style={{ color: tone }}>{icon}</span>}
        {label}
      </div>
      <div className="text-[24px] font-semibold leading-tight tracking-tight text-ink">{value}</div>
      {sub && <div className="truncate text-[11.5px] text-muted">{sub}</div>}
    </div>
  );
}

function TipBox({ active, payload, label, fmt }: any) {
  if (!active || !payload?.length) return null;
  return (
    <div className="rounded-md border border-line-strong bg-surface-2 px-2.5 py-1.5 text-[12px] shadow-xl">
      {label !== undefined && <div className="mb-0.5 text-muted">{fmt ? fmt(label) : label}</div>}
      {payload.map((p: any) => (
        <div key={p.dataKey ?? p.name} className="flex items-center gap-2">
          <span className="h-2 w-2 rounded-sm" style={{ background: p.color ?? p.payload?.fill }} />
          <span className="text-ink-2">{p.name}</span>
          <span className="tabular ml-auto pl-3 font-medium text-ink">{p.value}</span>
        </div>
      ))}
    </div>
  );
}

/** Single-series area over time. Two measures of different scale -> two of these, never a dual axis. */
export function SeriesChart({ data, dataKey, name, color, height = 150, xFmt }: {
  data: any[]; dataKey: string; name: string; color: string; height?: number; xFmt?: (v: string) => string;
}) {
  const id = `g-${dataKey}-${color.slice(1)}`;
  return (
    <ResponsiveContainer width="100%" height={height}>
      <AreaChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -6 }}>
        <defs>
          <linearGradient id={id} x1="0" x2="0" y1="0" y2="1">
            <stop offset="0%" stopColor={color} stopOpacity={0.28} />
            <stop offset="100%" stopColor={color} stopOpacity={0.02} />
          </linearGradient>
        </defs>
        <CartesianGrid stroke="#2c2c2a" vertical={false} />
        <XAxis dataKey="bucket" {...AXIS} tickFormatter={xFmt} minTickGap={24} />
        <YAxis {...AXIS} axisLine={false} allowDecimals={false} width={44} />
        <Tooltip content={<TipBox fmt={xFmt} />} cursor={{ stroke: "#898781", strokeDasharray: "3 3" }} />
        <Area type="monotone" dataKey={dataKey} name={name} stroke={color} strokeWidth={2} fill={`url(#${id})`}
          dot={false} activeDot={{ r: 4, stroke: "#1a1a19", strokeWidth: 2 }} isAnimationActive={false} />
      </AreaChart>
    </ResponsiveContainer>
  );
}

/** Horizontal bars with direct value labels (magnitude by category). */
export function BarList({ items, color, empty, onClick }: {
  items: { key: string; label: ReactNode; value: number; color?: string }[];
  color?: string; empty?: ReactNode; onClick?: (key: string) => void;
}) {
  const max = Math.max(1, ...items.map((i) => i.value));
  if (!items.length) return <>{empty}</>;
  return (
    <div className="flex flex-col gap-1.5">
      {items.map((i) => (
        <button
          key={i.key}
          type="button"
          disabled={!onClick}
          onClick={() => onClick?.(i.key)}
          className={cx("group grid grid-cols-[minmax(0,150px)_1fr_42px] items-center gap-3 text-left", onClick && "cursor-pointer")}
          title={`${i.value}`}
        >
          <span className="truncate text-[12px] text-ink-2 group-hover:text-ink">{i.label}</span>
          <span className="h-2.5 rounded-r bg-surface-2">
            <span className="block h-full rounded-r" style={{ width: `${(i.value / max) * 100}%`, background: i.color ?? color ?? "#3987e5", minWidth: 2 }} />
          </span>
          <span className="tabular text-right text-[12px] text-ink">{i.value}</span>
        </button>
      ))}
    </div>
  );
}

/** Vertical histogram (ordered bins), single series. */
export function Histogram({ data, color = "#3987e5", height = 160, name = "Count" }: {
  data: { bin: string; count: number }[]; color?: string; height?: number; name?: string;
}) {
  return (
    <ResponsiveContainer width="100%" height={height}>
      <BarChart data={data} margin={{ top: 6, right: 8, bottom: 0, left: -6 }} barCategoryGap={2}>
        <CartesianGrid stroke="#2c2c2a" vertical={false} />
        <XAxis dataKey="bin" {...AXIS} interval={0} />
        <YAxis {...AXIS} axisLine={false} allowDecimals={false} width={44} />
        <Tooltip content={<TipBox />} cursor={{ fill: "rgba(255,255,255,0.04)" }} />
        <Bar dataKey="count" name={name} fill={color} radius={[4, 4, 0, 0]} isAnimationActive={false}>
          {data.map((_, i) => <Cell key={i} fill={color} />)}
        </Bar>
      </BarChart>
    </ResponsiveContainer>
  );
}
