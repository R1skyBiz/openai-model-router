import { useCallback, useEffect, useState } from 'react'

export interface AsyncState<T> {
  data: T | null
  error: Error | null
  loading: boolean
  reload: () => void
}

export function useAsync<T>(loader: (signal: AbortSignal) => Promise<T>, dependencies: readonly unknown[]): AsyncState<T> {
  const [data, setData] = useState<T | null>(null)
  const [error, setError] = useState<Error | null>(null)
  const [loading, setLoading] = useState(true)
  const [revision, setRevision] = useState(0)

  useEffect(() => {
    const controller = new AbortController()
    setLoading(true)
    setError(null)
    loader(controller.signal).then((next) => {
      setData(next)
      setLoading(false)
    }).catch((cause: unknown) => {
      if (cause instanceof DOMException && cause.name === 'AbortError') return
      setError(cause instanceof Error ? cause : new Error('Unable to load data'))
      setLoading(false)
    })
    return () => controller.abort()
    // Callers provide primitive cache keys so request lifecycles remain explicit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...dependencies, revision])

  const reload = useCallback(() => setRevision((value) => value + 1), [])
  return { data, error, loading, reload }
}
