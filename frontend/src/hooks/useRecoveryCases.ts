import { useCallback, useEffect, useState } from 'react'
import { recoveryApi, type FailedPaymentListResponse } from '../api/recoveryApi'

export function useRecoveryCases(filters: Record<string, string | number | undefined> = {}) {
  const [data, setData] = useState<FailedPaymentListResponse | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const filterKey = JSON.stringify(filters)

  const refetch = useCallback(() => {
    setLoading(true)
    setError(null)
    recoveryApi
      .listFailedPayments(filters)
      .then(setData)
      .catch((err) => setError(err instanceof Error ? err.message : 'Failed to load recovery cases.'))
      .finally(() => setLoading(false))
    // filterKey is the stable dependency; filters itself is a new object each render.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [filterKey])

  useEffect(() => {
    refetch()
  }, [refetch])

  return { data, loading, error, refetch }
}
