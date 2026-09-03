import { Link } from 'react-router-dom'
import type { FailedPaymentListItem } from '../../api/recoveryApi'
import { RiskBadge } from '../ui/Badge'

function formatAmount(amount: number, currency: string) {
  return new Intl.NumberFormat('en-IN', { style: 'currency', currency, maximumFractionDigits: 0 }).format(
    amount / 100,
  )
}

function formatReason(reason: string) {
  return reason.replace(/_/g, ' ')
}

export function RecoveryTable({ items }: { items: FailedPaymentListItem[] }) {
  if (items.length === 0) {
    return (
      <div className="border border-hairline bg-surface p-10 text-center text-sm text-ink-mid">
        No failed payments in this range yet. New cases will appear here as they're detected.
      </div>
    )
  }

  return (
    <table className="w-full border-collapse text-sm">
      <thead>
        <tr className="border-b border-hairline text-left text-xs text-ink-soft">
          <th className="py-3 font-medium">Customer</th>
          <th className="py-3 font-medium">Amount</th>
          <th className="py-3 font-medium">Reason</th>
          <th className="py-3 font-medium">Recoverability</th>
          <th className="py-3 font-medium">Status</th>
          <th className="py-3 font-medium">Detected</th>
        </tr>
      </thead>
      <tbody>
        {items.map((item) => (
          <tr key={item.failed_payment_id} className="border-b border-hairline hover:bg-paper">
            <td className="py-3">
              <Link to={`/cases/${item.failed_payment_id}`} className="font-medium text-ink hover:underline">
                {item.customer.name}
              </Link>
              {item.customer.email && <div className="text-xs text-ink-soft">{item.customer.email}</div>}
            </td>
            <td className="py-3 tabular-nums">{formatAmount(item.amount, item.currency)}</td>
            <td className="py-3 capitalize text-ink-mid">{formatReason(item.failure_reason_category)}</td>
            <td className="py-3">
              <RiskBadge tier={item.risk_tier} />
            </td>
            <td className="py-3 capitalize text-ink-mid">{item.status}</td>
            <td className="py-3 text-ink-soft">{new Date(item.detected_at).toLocaleDateString()}</td>
          </tr>
        ))}
      </tbody>
    </table>
  )
}
