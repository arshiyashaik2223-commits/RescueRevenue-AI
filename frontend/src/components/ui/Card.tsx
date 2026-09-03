import type { ReactNode } from 'react'

export function Card({ children, className = '' }: { children: ReactNode; className?: string }) {
  return <div className={`border border-hairline bg-surface p-5 ${className}`}>{children}</div>
}
