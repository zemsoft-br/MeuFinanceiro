import {
  createElement,
  type ButtonHTMLAttributes,
  type HTMLAttributes,
  type ReactNode,
} from 'react'

export type ButtonVariant = 'primary' | 'secondary' | 'ghost' | 'danger'

export interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant
}

export function Button({ variant = 'primary', className = '', type = 'button', ...props }: ButtonProps) {
  const classes = ['button', `button--${variant}`, className].filter(Boolean).join(' ')
  return createElement('button', { ...props, type, className: classes })
}

export type BadgeTone = 'neutral' | 'positive' | 'warning' | 'negative' | 'info'

export interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
}

export function Badge({ tone = 'neutral', className = '', ...props }: BadgeProps) {
  const classes = ['badge', `badge--${tone}`, className].filter(Boolean).join(' ')
  return createElement('span', { ...props, className: classes })
}

export type StateKind = 'loading' | 'empty' | 'error' | 'unavailable'

export interface StatePanelProps {
  kind: StateKind
  title: string
  description: string
  action?: ReactNode
  compact?: boolean
}

const STATE_SYMBOLS: Record<StateKind, string> = {
  loading: '…',
  empty: '○',
  error: '!',
  unavailable: '↻',
}

export function StatePanel({ kind, title, description, action, compact = false }: StatePanelProps) {
  return createElement(
    'section',
    {
      className: `state-panel state-panel--${kind}${compact ? ' state-panel--compact' : ''}`,
      'aria-live': kind === 'loading' ? 'polite' : undefined,
      'aria-busy': kind === 'loading' ? true : undefined,
    },
    createElement('span', { className: 'state-panel__symbol', 'aria-hidden': true }, STATE_SYMBOLS[kind]),
    createElement(
      'div',
      { className: 'state-panel__content' },
      createElement('h3', null, title),
      createElement('p', null, description),
      action ? createElement('div', { className: 'state-panel__action' }, action) : null,
    ),
  )
}
