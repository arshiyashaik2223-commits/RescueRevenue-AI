import { LineChart, Line, XAxis, YAxis, ResponsiveContainer, Tooltip, CartesianGrid } from 'recharts'

interface TrendChartProps {
  series: { bucket_start: string; total_failures: number }[]
}

export function TrendChart({ series }: TrendChartProps) {
  return (
    <ResponsiveContainer width="100%" height={220}>
      <LineChart data={series} margin={{ left: 0, right: 12 }}>
        <CartesianGrid stroke="#E2E5EA" vertical={false} />
        <XAxis dataKey="bucket_start" tick={{ fill: '#8A93A3', fontSize: 12 }} axisLine={false} tickLine={false} />
        <YAxis tick={{ fill: '#8A93A3', fontSize: 12 }} axisLine={false} tickLine={false} width={32} />
        <Tooltip contentStyle={{ borderRadius: 0, border: '1px solid #E2E5EA', fontSize: 13 }} />
        <Line type="monotone" dataKey="total_failures" stroke="#B45309" strokeWidth={2} dot={false} />
      </LineChart>
    </ResponsiveContainer>
  )
}
