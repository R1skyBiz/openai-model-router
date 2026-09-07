import type { ReactNode } from 'react'
import { Area, AreaChart, Bar, BarChart, CartesianGrid, Cell, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts'

const colors = ['var(--chart-blue)', 'var(--chart-indigo)', 'var(--chart-teal)', 'var(--chart-gold)', 'var(--chart-slate)']

interface ChartProps { data: Record<string, unknown>[]; xKey?: string; yKey?: string; valueLabel?: (value: number) => string; children?: ReactNode }

const tooltipStyle = { background: 'var(--surface-raised)', border: '1px solid var(--line)', borderRadius: 10, boxShadow: 'var(--shadow-md)', color: 'var(--text)' }

export function TrendChart({ data, xKey = 'date', yKey = 'value', valueLabel = String }: ChartProps) {
  return <div className="chart" aria-hidden="true"><ResponsiveContainer width="100%" height="100%"><AreaChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}><defs><linearGradient id="quiet-area" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor="var(--chart-blue)" stopOpacity={0.24}/><stop offset="100%" stopColor="var(--chart-blue)" stopOpacity={0}/></linearGradient></defs><CartesianGrid vertical={false} stroke="var(--chart-grid)" /><XAxis dataKey={xKey} tickLine={false} axisLine={false} tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }} minTickGap={28}/><YAxis tickLine={false} axisLine={false} tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }} tickFormatter={(value) => valueLabel(Number(value))}/><Tooltip contentStyle={tooltipStyle} formatter={(value) => valueLabel(Number(value))}/><Area type="monotone" dataKey={yKey} stroke="var(--chart-blue)" strokeWidth={2} fill="url(#quiet-area)" connectNulls={false}/></AreaChart></ResponsiveContainer></div>
}

export function MultiLineChart({ data, lines, xKey = 'date', valueLabel = String }: { data: Record<string, unknown>[]; lines: { key: string; label: string }[]; xKey?: string; valueLabel?: (value: number) => string }) {
  return <div className="chart" aria-hidden="true"><ResponsiveContainer width="100%" height="100%"><LineChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}><CartesianGrid vertical={false} stroke="var(--chart-grid)"/><XAxis dataKey={xKey} tickLine={false} axisLine={false} tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }} minTickGap={28}/><YAxis tickLine={false} axisLine={false} tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }} tickFormatter={(value) => valueLabel(Number(value))}/><Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [valueLabel(Number(value)), lines.find((line) => line.key === name)?.label ?? name]}/>{lines.map((line, index) => <Line key={line.key} type="monotone" dataKey={line.key} name={line.key} stroke={colors[index % colors.length]} strokeWidth={2} dot={false} connectNulls={false}/>)}</LineChart></ResponsiveContainer></div>
}

export function HorizontalBars({ data, valueLabel = String }: { data: { key: string; value: number }[]; valueLabel?: (value: number) => string }) {
  const height = Math.max(180, data.length * 38)
  return <div className="chart chart-bars" style={{ height }} aria-hidden="true"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} layout="vertical" margin={{ top: 0, right: 12, left: 4, bottom: 0 }}><XAxis type="number" hide/><YAxis type="category" dataKey="key" width={98} tickLine={false} axisLine={false} tick={{ fill: 'var(--text-secondary)', fontSize: 12 }}/><Tooltip cursor={{ fill: 'var(--hover)' }} contentStyle={tooltipStyle} formatter={(value) => valueLabel(Number(value))}/><Bar dataKey="value" radius={[0, 5, 5, 0]} maxBarSize={13}>{data.map((_, index) => <Cell key={index} fill={colors[index % colors.length]}/>)}</Bar></BarChart></ResponsiveContainer></div>
}

export function StackedBars({ data, keys, xKey = 'date', valueLabel = String }: { data: Record<string, unknown>[]; keys: { key: string; label: string }[]; xKey?: string; valueLabel?: (value: number) => string }) {
  return <div className="chart" aria-hidden="true"><ResponsiveContainer width="100%" height="100%"><BarChart data={data} margin={{ top: 8, right: 8, left: -18, bottom: 0 }}><CartesianGrid vertical={false} stroke="var(--chart-grid)"/><XAxis dataKey={xKey} tickLine={false} axisLine={false} tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }} minTickGap={28}/><YAxis tickLine={false} axisLine={false} tick={{ fill: 'var(--text-tertiary)', fontSize: 11 }}/><Tooltip contentStyle={tooltipStyle} formatter={(value, name) => [valueLabel(Number(value)), keys.find((key) => key.key === name)?.label ?? name]}/>{keys.map((key, index) => <Bar key={key.key} dataKey={key.key} stackId="stack" fill={colors[index % colors.length]} radius={index === keys.length - 1 ? [4, 4, 0, 0] : undefined}/>)}</BarChart></ResponsiveContainer></div>
}
