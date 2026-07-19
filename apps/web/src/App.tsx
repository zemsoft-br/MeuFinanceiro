import { useEffect, useState, type ChangeEvent, type FormEvent, type MouseEvent, type ReactNode } from 'react'

import { APP_ROUTES, type RouteId } from './routes'
import { Badge, Button, StatePanel } from './ui'
import { Icon, type IconName } from './icons'
import { useApiHealth } from './use-api-health'
import { useAppRoute } from './use-router'
import { usePwaInstall } from './pwa'
import {
  hasValidationErrors,
  validateDemoPreferences,
  type DemoPreferences,
  type DemoPreferencesErrors,
} from './validation'

const ROUTE_ICONS: Record<RouteId, IconName> = {
  home: 'home',
  components: 'components',
  system: 'system',
}

const API_LABELS = {
  checking: { label: 'Verificando', tone: 'neutral' },
  online: { label: 'Operacional', tone: 'positive' },
  degraded: { label: 'Atenção', tone: 'warning' },
  offline: { label: 'Indisponível', tone: 'negative' },
} as const

function Brand() {
  return (
    <a className="brand" href="/" aria-label="MeuFinanceiro — página inicial">
      <span className="brand__mark" aria-hidden="true">MF</span>
      <span>
        <strong>MeuFinanceiro</strong>
        <small>Fundação Web/PWA</small>
      </span>
    </a>
  )
}

function Navigation({
  currentRoute,
  onNavigate,
  variant,
}: {
  currentRoute: RouteId
  onNavigate: (event: MouseEvent<HTMLAnchorElement>) => void
  variant: 'sidebar' | 'mobile'
}) {
  return (
    <nav className={`navigation navigation--${variant}`} aria-label="Navegação principal">
      {APP_ROUTES.map((route) => (
        <a
          key={route.id}
          href={route.path}
          onClick={onNavigate}
          aria-current={currentRoute === route.id ? 'page' : undefined}
          title={route.description}
        >
          <Icon name={ROUTE_ICONS[route.id]} />
          <span>{variant === 'mobile' ? route.shortLabel : route.label}</span>
        </a>
      ))}
    </nav>
  )
}

function ApiNotice({ state, onRefresh }: { state: keyof typeof API_LABELS; onRefresh: () => void }) {
  if (state === 'online') return null

  if (state === 'checking') {
    return (
      <div className="api-notice" role="status">
        <span className="spinner" aria-hidden="true" />
        Verificando a conexão com a API…
      </div>
    )
  }

  return (
    <div className={`api-notice api-notice--${state}`} role="status">
      <div>
        <strong>{state === 'degraded' ? 'Serviço parcialmente disponível' : 'API indisponível'}</strong>
        <span>
          {state === 'degraded'
            ? 'A interface continua acessível enquanto o ambiente é verificado.'
            : 'Você pode navegar pela interface, mas operações dependentes da API estão suspensas.'}
        </span>
      </div>
      <Button variant="ghost" onClick={onRefresh}>Tentar novamente</Button>
    </div>
  )
}

const FEATURE_CARDS: readonly {
  icon: IconName
  title: string
  description: string
  label: string
}[] = [
  {
    icon: 'wallet',
    title: 'Livro financeiro',
    description: 'Contas, lançamentos e conciliação com rastreabilidade.',
    label: 'Próxima fase',
  },
  {
    icon: 'budget',
    title: 'Orçamentos',
    description: 'Planejamento mensal configurável para pessoas e residência.',
    label: 'Planejado',
  },
  {
    icon: 'cards',
    title: 'Cartões e faturas',
    description: 'Compras, parcelas, fechamento e pagamento sem duplicidade.',
    label: 'Planejado',
  },
  {
    icon: 'goals',
    title: 'Patrimônio e metas',
    description: 'Visão consolidada, compromissos e projeções de longo prazo.',
    label: 'Planejado',
  },
]

function HomePage({ apiState }: { apiState: keyof typeof API_LABELS }) {
  return (
    <div className="page-stack">
      <section className="hero" aria-labelledby="home-title">
        <div className="hero__content">
          <Badge tone="info">Ambiente de demonstração</Badge>
          <h1 id="home-title">A base para organizar as finanças da sua residência.</h1>
          <p>
            Esta versão apresenta a navegação, os padrões de interface e a infraestrutura do
            MeuFinanceiro. Nenhum dado financeiro real é solicitado ou armazenado nesta fase.
          </p>
          <div className="hero__actions">
            <a className="button button--primary" href="/componentes">Explorar componentes</a>
            <a className="button button--secondary" href="/sistema">Ver estado do sistema</a>
          </div>
        </div>
        <aside className="hero__status" aria-label="Resumo do ambiente">
          <div className="hero__status-header">
            <span>Fundação técnica</span>
            <Badge tone={API_LABELS[apiState].tone}>{API_LABELS[apiState].label}</Badge>
          </div>
          <ul className="foundation-list">
            {['Shell responsivo', 'Design system inicial', 'PWA instalável', 'API e PostgreSQL'].map(
              (item, index) => (
                <li key={item}>
                  <span className={index === 3 && apiState !== 'online' ? 'check check--muted' : 'check'}>
                    <Icon name="check" />
                  </span>
                  {item}
                </li>
              ),
            )}
          </ul>
          <p className="privacy-note"><Icon name="shield" /> Dados sob controle de quem hospeda.</p>
        </aside>
      </section>

      <section aria-labelledby="capabilities-title">
        <div className="section-heading">
          <div>
            <p className="eyebrow">Estrutura preparada</p>
            <h2 id="capabilities-title">Módulos previstos</h2>
          </div>
          <p>Os cartões abaixo documentam direção de produto; ainda não representam funcionalidades ativas.</p>
        </div>
        <div className="feature-grid">
          {FEATURE_CARDS.map((feature) => (
            <article className="feature-card" key={feature.title}>
              <span className="feature-card__icon"><Icon name={feature.icon} /></span>
              <Badge>{feature.label}</Badge>
              <h3>{feature.title}</h3>
              <p>{feature.description}</p>
            </article>
          ))}
        </div>
      </section>

      <section className="principles" aria-labelledby="principles-title">
        <div>
          <p className="eyebrow">Princípios do produto</p>
          <h2 id="principles-title">Simples para usar, rigoroso com os dados.</h2>
        </div>
        <div className="principles__grid">
          <article><strong>Autohospedado</strong><span>Execução local por Docker, sem dependência obrigatória de nuvem.</span></article>
          <article><strong>Brasil primeiro</strong><span>Moeda, calendário e fluxos pensados para pessoa física no Brasil.</span></article>
          <article><strong>Privacidade padrão</strong><span>Telemetria desativada e nenhuma resposta financeira em cache offline.</span></article>
        </div>
      </section>
    </div>
  )
}

function Field({
  id,
  label,
  hint,
  error,
  children,
}: {
  id: string
  label: string
  hint?: string
  error?: string
  children: ReactNode
}) {
  const descriptionId = error ? `${id}-error` : hint ? `${id}-hint` : undefined
  return (
    <div className="field" data-invalid={error ? 'true' : undefined}>
      <label htmlFor={id}>{label}</label>
      {children}
      {error ? <p id={descriptionId} className="field__error">{error}</p> : null}
      {!error && hint ? <p id={descriptionId} className="field__hint">{hint}</p> : null}
    </div>
  )
}

function ComponentsPage() {
  const [values, setValues] = useState<DemoPreferences>({ residenceName: '', startDay: '1' })
  const [errors, setErrors] = useState<DemoPreferencesErrors>({})
  const [saved, setSaved] = useState(false)

  const submit = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    const nextErrors = validateDemoPreferences(values)
    setErrors(nextErrors)
    setSaved(!hasValidationErrors(nextErrors))
  }

  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Design system inicial</p>
        <h1>Componentes e estados comuns</h1>
        <p>Referência mínima para manter novas contribuições consistentes, acessíveis e previsíveis.</p>
      </header>

      <section className="documentation-card" aria-labelledby="actions-title">
        <div className="documentation-card__header">
          <div><h2 id="actions-title">Ações</h2><p>Hierarquia visual para decisões primárias, secundárias e destrutivas.</p></div>
        </div>
        <div className="component-row">
          <Button>Salvar alterações</Button>
          <Button variant="secondary">Ação secundária</Button>
          <Button variant="ghost">Ação discreta</Button>
          <Button variant="danger">Remover</Button>
          <Button disabled>Indisponível</Button>
        </div>
      </section>

      <section className="documentation-card" aria-labelledby="feedback-title">
        <div className="documentation-card__header">
          <div><h2 id="feedback-title">Feedback e status</h2><p>Cores sempre acompanhadas por texto para não depender apenas da percepção visual.</p></div>
        </div>
        <div className="component-row">
          <Badge>Neutro</Badge><Badge tone="positive">Concluído</Badge><Badge tone="warning">Atenção</Badge>
          <Badge tone="negative">Erro</Badge><Badge tone="info">Informação</Badge>
        </div>
      </section>

      <section className="documentation-card" aria-labelledby="form-title">
        <div className="documentation-card__header">
          <div><h2 id="form-title">Formulário e validação-base</h2><p>Exemplo local; nenhum valor é enviado ou persistido.</p></div>
        </div>
        <form className="demo-form" noValidate onSubmit={submit}>
          <Field
            id="residence-name"
            label="Nome da residência"
            hint="Entre 3 e 60 caracteres."
            error={errors.residenceName}
          >
            <input
              id="residence-name"
              name="residenceName"
              value={values.residenceName}
              onChange={(event: ChangeEvent<HTMLInputElement>) => {
                setValues((current) => ({ ...current, residenceName: event.target.value }))
                setSaved(false)
              }}
              aria-invalid={Boolean(errors.residenceName)}
              aria-describedby={errors.residenceName ? 'residence-name-error' : 'residence-name-hint'}
              autoComplete="organization"
            />
          </Field>
          <Field id="start-day" label="Dia inicial do ciclo" error={errors.startDay}>
            <select
              id="start-day"
              name="startDay"
              value={values.startDay}
              onChange={(event: ChangeEvent<HTMLSelectElement>) => {
                setValues((current) => ({ ...current, startDay: event.target.value }))
                setSaved(false)
              }}
              aria-invalid={Boolean(errors.startDay)}
              aria-describedby={errors.startDay ? 'start-day-error' : undefined}
            >
              {[1, 5, 10, 15, 20, 25, 28].map((day) => <option key={day} value={day}>{day}</option>)}
            </select>
          </Field>
          <div className="form-actions">
            <Button type="submit">Validar preferências</Button>
            {saved ? <span className="success-message" role="status"><Icon name="check" /> Validação concluída.</span> : null}
          </div>
        </form>
      </section>

      <section aria-labelledby="states-title">
        <div className="section-heading section-heading--compact">
          <div><p className="eyebrow">Estados reutilizáveis</p><h2 id="states-title">Carregamento, vazio, erro e indisponibilidade</h2></div>
        </div>
        <div className="state-grid">
          <StatePanel kind="loading" title="Carregando informações" description="Aguarde enquanto os dados necessários são consultados." compact />
          <StatePanel kind="empty" title="Nenhum item cadastrado" description="Quando houver conteúdo, ele será apresentado neste espaço." compact />
          <StatePanel kind="error" title="Não foi possível concluir" description="Revise os dados informados e tente novamente." compact />
          <StatePanel kind="unavailable" title="Serviço indisponível" description="A interface permanece acessível enquanto a conexão é restabelecida." compact />
        </div>
      </section>
    </div>
  )
}

function SystemPage({
  apiState,
  readiness,
  checkedAt,
  refresh,
}: ReturnType<typeof useApiHealth> & { apiState: keyof typeof API_LABELS }) {
  const install = usePwaInstall()
  const tone = API_LABELS[apiState].tone

  return (
    <div className="page-stack">
      <header className="page-header">
        <p className="eyebrow">Diagnóstico local</p>
        <h1>Estado do sistema e instalação</h1>
        <p>Acompanhe a disponibilidade dos serviços e instale o shell como aplicativo quando o navegador permitir.</p>
      </header>

      <div className="system-grid">
        <section className="system-card" aria-labelledby="api-health-title">
          <div className="system-card__header">
            <span className="system-card__icon"><Icon name="system" /></span>
            <Badge tone={tone}>{API_LABELS[apiState].label}</Badge>
          </div>
          <h2 id="api-health-title">API e persistência</h2>
          <dl className="health-details">
            <div><dt>Processo</dt><dd>{readiness?.process ?? 'não verificado'}</dd></div>
            <div><dt>Banco</dt><dd>{readiness?.database ?? 'não verificado'}</dd></div>
            <div><dt>Schema</dt><dd>{readiness?.schema ?? 'não verificado'}</dd></div>
            <div><dt>Última verificação</dt><dd>{checkedAt ? checkedAt.toLocaleTimeString('pt-BR') : '—'}</dd></div>
          </dl>
          <Button variant="secondary" onClick={refresh} disabled={apiState === 'checking'}>
            <Icon name="refresh" /> Atualizar estado
          </Button>
        </section>

        <section className="system-card" aria-labelledby="install-title">
          <div className="system-card__header">
            <span className="system-card__icon"><Icon name="download" /></span>
            <Badge tone={install.state === 'installed' ? 'positive' : 'info'}>
              {install.state === 'installed' ? 'Instalada' : 'PWA'}
            </Badge>
          </div>
          <h2 id="install-title">Instalar MeuFinanceiro</h2>
          <p>O navegador pode adicionar esta interface à área de trabalho ou à tela inicial.</p>
          {install.state === 'available' ? (
            <Button onClick={() => void install.install()}>Instalar aplicativo</Button>
          ) : (
            <p className="install-hint">
              {install.state === 'installed'
                ? 'O aplicativo já está sendo executado em modo instalado.'
                : 'Use a opção “Instalar aplicativo” ou “Adicionar à tela inicial” do navegador compatível.'}
            </p>
          )}
        </section>
      </div>

      <section className="cache-policy" aria-labelledby="cache-title">
        <span className="cache-policy__icon"><Icon name="shield" /></span>
        <div>
          <p className="eyebrow">Política offline desta fase</p>
          <h2 id="cache-title">Somente a interface é armazenada.</h2>
          <p>
            O service worker exclui explicitamente qualquer URL sob <code>/api/</code>. Tokens,
            respostas de saúde e futuros dados financeiros não entram no cache da PWA.
          </p>
        </div>
      </section>
    </div>
  )
}

function App() {
  const { route, handleLinkClick } = useAppRoute()
  const health = useApiHealth()
  const [menuOpen, setMenuOpen] = useState(false)

  useEffect(() => {
    document.title = `${route.label} · MeuFinanceiro`
  }, [route.label])

  useEffect(() => {
    if (!menuOpen) return
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setMenuOpen(false)
    }
    window.addEventListener('keydown', closeOnEscape)
    return () => window.removeEventListener('keydown', closeOnEscape)
  }, [menuOpen])

  const navigate = (event: MouseEvent<HTMLAnchorElement>) => {
    handleLinkClick(event)
    setMenuOpen(false)
  }

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main-content">Ir para o conteúdo principal</a>

      <aside id="primary-sidebar" className={`sidebar${menuOpen ? ' sidebar--open' : ''}`} aria-label="Menu lateral">
        <div className="sidebar__header">
          <Brand />
          <button className="icon-button sidebar__close" type="button" onClick={() => setMenuOpen(false)} aria-label="Fechar menu">
            <Icon name="close" />
          </button>
        </div>
        <Navigation currentRoute={route.id} onNavigate={navigate} variant="sidebar" />
        <div className="sidebar__footer">
          <span>Projeto open-source</span>
          <small>Não use dados reais nesta fase.</small>
        </div>
      </aside>

      {menuOpen ? <button className="backdrop" type="button" aria-label="Fechar menu" onClick={() => setMenuOpen(false)} /> : null}

      <div className="app-main">
        <header className="topbar">
          <button className="icon-button topbar__menu" type="button" onClick={() => setMenuOpen(true)} aria-label="Abrir menu" aria-expanded={menuOpen} aria-controls="primary-sidebar">
            <Icon name="menu" />
          </button>
          <div className="topbar__mobile-brand"><Brand /></div>
          <div className="topbar__status" aria-label={`API: ${API_LABELS[health.state].label}`}>
            <span className={`status-dot status-dot--${health.state}`} aria-hidden="true" />
            <span>API</span>
            <strong>{API_LABELS[health.state].label}</strong>
          </div>
        </header>

        <ApiNotice state={health.state} onRefresh={health.refresh} />

        <main id="main-content" className="content" tabIndex={-1}>
          {route.id === 'home' ? <HomePage apiState={health.state} /> : null}
          {route.id === 'components' ? <ComponentsPage /> : null}
          {route.id === 'system' ? <SystemPage {...health} apiState={health.state} /> : null}
        </main>

        <footer className="app-footer">
          <span>MeuFinanceiro · Fundação do projeto</span>
          <a href="/api/v1/docs">Documentação da API</a>
        </footer>
      </div>

      <Navigation currentRoute={route.id} onNavigate={navigate} variant="mobile" />
    </div>
  )
}

export default App
