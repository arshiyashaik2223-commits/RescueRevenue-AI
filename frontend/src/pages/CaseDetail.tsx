import { useEffect, useState } from 'react'
import { useParams } from 'react-router-dom'
import { recoveryApi, type RecoveryRecommendation } from '../api/recoveryApi'
import { RiskBadge } from '../components/ui/Badge'
import { Button } from '../components/ui/Button'
import { Card } from '../components/ui/Card'

export function CaseDetail() {
  const { id } = useParams<{ id: string }>()
  const [data, setData] = useState<RecoveryRecommendation | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)
  const [retrying, setRetrying] = useState(false)
  const [retryMessage, setRetryMessage] = useState<string | null>(null)

  useEffect(() => {
    if (!id) return
    setLoading(true)
    recoveryApi
      .getRecommendation(id, true)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load this case.'))
      .finally(() => setLoading(false))
  }, [id])

  async function handleRetry() {
    if (!id) return
    setRetrying(true)
    setRetryMessage(null)
    try {
      await recoveryApi.retryPayment(id)
      setRetryMessage('Retry queued — this case will update shortly.')
    } catch (err) {
      setRetryMessage(err instanceof Error ? err.message : 'Could not queue a retry.')
    } finally {
      setRetrying(false)
    }
  }

  if (loading) return <div className="p-8 text-sm text-ink-mid">Loading case…</div>
  if (error) return <div className="p-8 text-sm text-lost">{error}</div>
  if (!data) return null

  const prediction = data.current_prediction

  return (
    <div className="space-y-6 p-8">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="font-display text-2xl text-ink">Case {data.failed_payment_id.slice(-6)}</h1>
          <div className="mt-1">
            <RiskBadge tier={prediction.risk_tier} />
          </div>
        </div>
        <Button onClick={handleRetry} disabled={retrying}>
          {retrying ? 'Queuing retry…' : 'Retry now'}
        </Button>
      </div>

      {retryMessage && <p className="text-sm text-ink-mid">{retryMessage}</p>}

      <Card>
        <h2 className="mb-3 text-sm font-medium text-ink">Recovery score</h2>
        <div className="font-display text-3xl text-ink">{(prediction.recovery_score * 100).toFixed(0)}%</div>
        <p className="mt-1 text-xs text-ink-soft">
          Model {prediction.model_version} · scored {new Date(prediction.predicted_at).toLocaleString()}
        </p>
        {prediction.recommended_action && (
          <p className="mt-3 text-sm text-ink-mid">
            Next step:{' '}
            <span className="font-medium capitalize text-ink">
              {prediction.recommended_action.channel.replace('_', ' ')}
            </span>{' '}
            at {new Date(prediction.recommended_action.next_attempt_at).toLocaleString()}
          </p>
        )}
      </Card>

      {data.history.length > 0 && (
        <Card>
          <h2 className="mb-3 text-sm font-medium text-ink">Score history</h2>
          <ul className="space-y-2 text-sm text-ink-mid">
            {data.history.map((h) => (
              <li key={h.prediction_id} className="flex justify-between border-b border-hairline pb-2">
                <span>{new Date(h.predicted_at).toLocaleString()}</span>
                <span className="tabular-nums">{(h.recovery_score * 100).toFixed(0)}%</span>
              </li>
            ))}
          </ul>
        </Card>
      )}
    </div>
  )
}
