import type { SVGProps } from 'react'

export type IconName =
  | 'home'
  | 'components'
  | 'system'
  | 'wallet'
  | 'budget'
  | 'cards'
  | 'goals'
  | 'menu'
  | 'close'
  | 'check'
  | 'shield'
  | 'download'
  | 'refresh'

const PATHS: Record<IconName, string> = {
  home: 'M3 10.5 12 3l9 7.5V21a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1V10.5Z',
  components: 'M4 4h6v6H4V4Zm10 0h6v6h-6V4ZM4 14h6v6H4v-6Zm10 0h6v6h-6v-6Z',
  system: 'M12 3a9 9 0 1 0 9 9 9 9 0 0 0-9-9Zm0 4v5l3.5 2',
  wallet: 'M3 7a2 2 0 0 1 2-2h14v14H5a2 2 0 0 1-2-2V7Zm13 4h5v5h-5a2.5 2.5 0 0 1 0-5Z',
  budget: 'M4 5h16v14H4V5Zm4 4h8M8 13h5',
  cards: 'M3 7h18v12H3V7Zm0 4h18M7 16h4',
  goals: 'M12 3a9 9 0 1 0 9 9h-9V3Zm3 0v6h6A9 9 0 0 0 15 3Z',
  menu: 'M4 7h16M4 12h16M4 17h16',
  close: 'm6 6 12 12M18 6 6 18',
  check: 'm5 12 4 4L19 6',
  shield: 'M12 3 5 6v5c0 5 3 8 7 10 4-2 7-5 7-10V6l-7-3Zm-3 9 2 2 4-4',
  download: 'M12 3v12m-5-5 5 5 5-5M5 21h14',
  refresh: 'M20 6v5h-5M4 18v-5h5M6.1 8A7 7 0 0 1 18 6l2 5M4 13l2 5a7 7 0 0 0 11.9-2',
}

export function Icon({ name, ...props }: SVGProps<SVGSVGElement> & { name: IconName }) {
  return (
    <svg
      aria-hidden="true"
      fill="none"
      viewBox="0 0 24 24"
      stroke="currentColor"
      strokeWidth="1.8"
      strokeLinecap="round"
      strokeLinejoin="round"
      {...props}
    >
      <path d={PATHS[name]} />
    </svg>
  )
}
