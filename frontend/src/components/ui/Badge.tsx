interface BadgeProps {
  tier: 'high' | 'medium' | 'low' | string | null
}

const tierStyles: Record<string, string> = {
  high: 'bg-recovered-soft text-recovered',
  medium: 'bg-risk-soft text-risk',
  low: 'bg-lost-soft text-lost',
}

const tierLabels: Record<string, string> = {
  high: 'High recoverability',
  medium: 'Medium recoverability',
  low: 'Low recoverability',
}

export function RiskBadge({ tier }: BadgeProps) {
  if (!tier) {
    return <span className="text-xs text-ink-soft">Not scored yet</span>
  }
  return (
    <span
      className={`inline-flex items-center rounded-sm px-2 py-0.5 text-xs font-medium ${
        tierStyles[tier] ?? 'bg-hairline text-ink-mid'
      }`}
    >
      {tierLabels[tier] ?? tier}
    </span>
  )
}
