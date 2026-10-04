'use client';
import { useEffect, useState } from 'react';
import { ResponsiveContainer, AreaChart, Area, LineChart, Line, BarChart, Bar, CartesianGrid, XAxis, YAxis, Tooltip, Legend, Cell, ReferenceLine } from 'recharts';
import type { Curve, Metrics, QValue, Importance, ExperimentGroup } from '@/lib/types';
const ACCENT = 'var(--accent)', SECONDARY = 'var(--chart-secondary)', GRID = 'var(--chart-grid)';
const tooltip = { backgroundColor: 'var(--surface-raised)', color: 'var(--ink)', border: '1px solid var(--line)', borderRadius: 6, fontSize: 13, boxShadow: '0 6px 22px #00000030' };
function Ready({ children, height = 280 }: { children: React.ReactElement; height?: number }) {
  const [ready, setReady] = useState(false); useEffect(() => setReady(true), []);
  return <div className="chart" style={{ height }}>{ready ? <ResponsiveContainer width="100%" height="100%">{children}</ResponsiveContainer> : <div className="chart-placeholder" />}</div>;
}
export function RevenueChart({ series }: { series: Metrics[] }) {
  return <Ready><AreaChart data={series.slice(-30)} margin={{ top: 10, right: 12, bottom: 0, left: 0 }}>
    <defs><linearGradient id="revenueFill" x1="0" y1="0" x2="0" y2="1"><stop offset="0%" stopColor={ACCENT} stopOpacity={.16} /><stop offset="100%" stopColor={ACCENT} stopOpacity={0} /></linearGradient></defs>
    <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="date" tickFormatter={v => String(v).slice(5)} tick={{ fontSize: 11, fill: 'var(--muted)' }} axisLine={false} tickLine={false} minTickGap={35} />
    <YAxis tickFormatter={v => `${(Number(v)/1000).toFixed(0)}k`} tick={{ fontSize: 11, fill: 'var(--muted)' }} axisLine={false} tickLine={false} width={44} />
    <Tooltip contentStyle={tooltip} formatter={(v, name) => [Number(v).toLocaleString('zh-CN', { maximumFractionDigits: 0 }), name]} />
    <Area isAnimationActive={false} type="monotone" dataKey="revenue" name="销售收入（元）" stroke={ACCENT} strokeWidth={2.5} fill="url(#revenueFill)" />
  </AreaChart></Ready>;
}
export function ChannelChart({ series }: { series: { channel: string; revenue: number; advertising_cost: number }[] }) {
  return <Ready><BarChart data={series} margin={{ top: 10, right: 6, bottom: 0, left: 0 }}>
    <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="channel" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={v => `${(Number(v)/1000).toFixed(0)}k`} tick={{ fontSize: 11 }} axisLine={false} tickLine={false} width={40} />
    <Tooltip contentStyle={tooltip} /><Legend iconType="circle" iconSize={7} wrapperStyle={{ fontSize: 11 }} />
    <Bar isAnimationActive={false} dataKey="revenue" name="收入" fill={ACCENT} radius={[4,4,0,0]} maxBarSize={24} />
    <Bar isAnimationActive={false} dataKey="advertising_cost" name="广告投入" fill="var(--chart-secondary)" radius={[4,4,0,0]} maxBarSize={24} />
  </BarChart></Ready>;
}
export function QChart({ values, selected }: { values: QValue[]; selected: number }) {
  return <Ready height={520}><BarChart layout="vertical" data={values} margin={{ top: 0, right: 22, bottom: 0, left: 0 }}>
    <CartesianGrid stroke={GRID} horizontal={false} /><XAxis type="number" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="label" width={190} tick={{ fontSize: 11, fill: 'var(--muted)' }} axisLine={false} tickLine={false} />
    <Tooltip contentStyle={tooltip} formatter={v => [Number(v).toFixed(4), '累计回报 Q']} /><ReferenceLine x={0} stroke="var(--chart-secondary)" />
    <Bar isAnimationActive={false} dataKey="q" barSize={12} radius={[0,3,3,0]}>{values.map(v => <Cell key={v.name} fill={!v.legal ? '#53604d' : v.index===selected ? ACCENT : 'var(--chart-secondary)'} />)}</Bar>
  </BarChart></Ready>;
}
export function TrainingChart({ curves, kind }: { curves: Curve[]; kind: 'reward' | 'loss' }) {
  const data = curves.map((c,i) => ({...c, smoothed: curves.slice(Math.max(0,i-9),i+1).reduce((s,x)=>s+x.average_reward,0)/Math.min(i+1,10)}));
  return <Ready><LineChart data={data} margin={{ top: 10, right: 15, left: 0, bottom: 0 }}>
    <CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="episode" tick={{ fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis tick={{ fontSize: 11 }} width={46} axisLine={false} tickLine={false} tickFormatter={v => Number(v).toFixed(2)} />
    <Tooltip contentStyle={tooltip} formatter={(v,name) => [Number(v).toFixed(4),name]} /><Legend iconSize={7} wrapperStyle={{ fontSize: 11 }} />
    {kind==='reward' ? <><Line isAnimationActive={false} dataKey="average_reward" name="每轮平均 Reward" stroke="var(--chart-secondary)" strokeWidth={1} dot={false} /><Line isAnimationActive={false} dataKey="smoothed" name="10 轮移动均值" stroke={ACCENT} strokeWidth={2.5} dot={false} /></> : <><Line isAnimationActive={false} dataKey="loss" name="Huber Loss" stroke={ACCENT} dot={false} strokeWidth={2} /><Line isAnimationActive={false} dataKey="epsilon" name="Epsilon" stroke={SECONDARY} dot={false} strokeWidth={1.5} /></>}
  </LineChart></Ready>;
}
export function ImportanceChart({ items }: { items: Importance[] }) {
  return <Ready height={310}><BarChart layout="vertical" data={items.filter(x=>x.present).slice(0,10)} margin={{ top: 0, right: 20, left: 0, bottom: 0 }}>
    <CartesianGrid stroke={GRID} horizontal={false} /><XAxis type="number" tick={{ fontSize: 10 }} tickFormatter={v=>Number(v).toFixed(3)} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="name" width={145} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} />
    <Tooltip contentStyle={tooltip} /><ReferenceLine x={0} stroke="var(--chart-secondary)" /><Bar isAnimationActive={false} dataKey="permutation_mean" name="置换后测试 MSE 增加" fill={ACCENT} barSize={13} radius={[0,3,3,0]} />
  </BarChart></Ready>;
}
export function ExperimentChart({ groups, metric = 'average_reward' }: { groups: ExperimentGroup[]; metric?: 'average_reward' | 'profit' | 'cac' }) {
  const data=groups.filter(x=>x.status==='completed' && x.summary).map(x=>({name:x.name.replace('（输入消融）','').replace('结构化外部信号 + ','结构化信号 + '), value:x.summary?.[metric]}));
  return <Ready height={290}><BarChart data={data} layout="vertical" margin={{ top: 10, right: 20, left: 0, bottom: 0 }}>
    <CartesianGrid stroke={GRID} horizontal={false} /><XAxis type="number" tick={{ fontSize: 11 }} tickFormatter={v=>Number(v).toFixed(metric==='average_reward'?2:0)} axisLine={false} tickLine={false} /><YAxis dataKey="name" type="category" width={180} tick={{ fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={tooltip} /><ReferenceLine x={0} stroke="var(--chart-secondary)" /><Bar isAnimationActive={false} dataKey="value" name={metric==='average_reward'?'平均 Reward':metric==='profit'?'日均营销贡献利润':'广告 CAC'} fill={ACCENT} barSize={27} radius={[0,4,4,0]} />
  </BarChart></Ready>;
}
