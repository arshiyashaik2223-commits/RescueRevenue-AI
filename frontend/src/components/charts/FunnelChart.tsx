import { BarChart, Bar, XAxis, YAxis, ResponsiveContainer, Tooltip } from 'recharts'

interface FunnelChartProps {
  funnel: { detected: number; attempted: number; recovered: number; lost: number }
}

export function FunnelChart({ funnel }: FunnelChartProps) {
  const data = [
    { stage: 'Detected', value: funnel.detected },
    { stage: 'Attempted', value: funnel.attempted },
    { stage: 'Recovered', value: funnel.recovered },
    { stage: 'Lost', value: funnel.lost },
  ]

  return (
    <ResponsiveContainer width="100%" height={220}>
      <BarChart data={data} layout="vertical" margin={{ left: 12, right: 24 }}>
        <XAxis type="number" hide />
        <YAxis
          type="category"
          dataKey="stage"
          width={90}
          tick={{ fill: '#4B5565', fontSize: 13 }}
          axisLine={false}
          tickLine={false}
        />
        <Tooltip cursor={{ fill: '#F7F8FA' }} contentStyle={{ borderRadius: 0, border: '1px solid #E2E5EA', fontSize: 13 }} />
        <Bar dataKey="value" fill="#10151F" radius={0} barSize={22} />
      </BarChart>
    </ResponsiveContainer>
  )
}
