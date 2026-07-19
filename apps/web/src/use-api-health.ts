import { useCallback, useEffect, useRef, useState } from 'react'

import {
  apiStateFromResponse,
  readinessFromPayload,
  type ApiReadiness,
  type ApiState,
} from './api-status'

interface ApiHealthResult {
  state: ApiState
  readiness: ApiReadiness | null
  checkedAt: Date | null
  refresh: () => void
}

const REQUEST_TIMEOUT_MS = 8_000

export function useApiHealth(): ApiHealthResult {
  const [state, setState] = useState<ApiState>('checking')
  const [readiness, setReadiness] = useState<ApiReadiness | null>(null)
  const [checkedAt, setCheckedAt] = useState<Date | null>(null)
  const [requestVersion, setRequestVersion] = useState(0)
  const activeRequest = useRef<AbortController | null>(null)

  const refresh = useCallback(() => setRequestVersion((version) => version + 1), [])

  useEffect(() => {
    const controller = new AbortController()
    let disposed = false
    activeRequest.current?.abort()
    activeRequest.current = controller
    setState('checking')

    const timeout = window.setTimeout(() => controller.abort(), REQUEST_TIMEOUT_MS)

    void fetch('/api/v1/health/ready', {
      method: 'GET',
      cache: 'no-store',
      credentials: 'same-origin',
      signal: controller.signal,
      headers: { Accept: 'application/json' },
    })
      .then(async (response) => {
        let payload: unknown
        try {
          payload = await response.json()
        } catch {
          payload = null
        }

        if (!disposed) {
          setReadiness(readinessFromPayload(payload))
          setState(apiStateFromResponse(response.ok, payload))
          setCheckedAt(new Date())
        }
      })
      .catch(() => {
        if (!disposed) {
          setReadiness(null)
          setState('offline')
          setCheckedAt(new Date())
        }
      })
      .finally(() => window.clearTimeout(timeout))

    return () => {
      disposed = true
      window.clearTimeout(timeout)
      controller.abort()
    }
  }, [requestVersion])

  return { state, readiness, checkedAt, refresh }
}
