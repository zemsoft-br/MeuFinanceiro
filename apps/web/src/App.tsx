import { useEffect, useState } from 'react'

import { apiStateFromResponse, type ApiState } from './api-status'

function App() {
  const [apiState, setApiState] = useState<ApiState>('checking')

  useEffect(() => {
    const controller = new AbortController()

    fetch('/api/v1/health/ready', { signal: controller.signal })
      .then((response) => {
        setApiState(apiStateFromResponse(response.ok))
      })
      .catch(() => {
        if (!controller.signal.aborted) setApiState('offline')
      })

    return () => controller.abort()
  }, [])

  return (
    <main className="shell">
      <section className="card" aria-labelledby="page-title">
        <p className="eyebrow">Fundação técnica</p>
        <h1 id="page-title">MeuFinanceiro</h1>
        <p>
          O monorepo está ativo. Esta tela é provisória e foi mantida neutra para receber a
          interface produzida no Google Stitch.
        </p>

        <dl className="status-list">
          <div>
            <dt>Frontend</dt>
            <dd data-state="online">online</dd>
          </div>
          <div>
            <dt>API e PostgreSQL</dt>
            <dd data-state={apiState}>{apiState}</dd>
          </div>
        </dl>

        <a href="/api/v1/docs">Abrir documentação OpenAPI</a>
      </section>
    </main>
  )
}

export default App
