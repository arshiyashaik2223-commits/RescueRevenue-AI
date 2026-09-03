import type { ReactNode } from 'react'
import { Navigate, NavLink as RouterNavLink, Route, Routes } from 'react-router-dom'
import { useAuth } from './hooks/useAuth'
import { Login } from './pages/Login'
import { Dashboard } from './pages/Dashboard'
import { RecoveryFeed } from './pages/RecoveryFeed'
import { CaseDetail } from './pages/CaseDetail'
import { Copilot } from './pages/Copilot'

function NavItem({ to, children }: { to: string; children: ReactNode }) {
  return (
    <RouterNavLink
      to={to}
      end={to === '/'}
      className={({ isActive }) =>
        `rounded-sm px-3 py-2 text-sm ${isActive ? 'bg-paper/10 text-paper' : 'text-paper/70 hover:text-paper'}`
      }
    >
      {children}
    </RouterNavLink>
  )
}

function ProtectedLayout({ children }: { children: ReactNode }) {
  const { user, loading, logout } = useAuth()

  if (loading) return <div className="p-8 text-sm text-ink-mid">Loading…</div>
  if (!user) return <Navigate to="/login" replace />

  return (
    <div className="flex min-h-screen">
      <nav className="relative w-56 shrink-0 border-r border-hairline bg-ink text-paper">
        <div className="p-6">
          <div className="font-display text-lg">RevenueRescue</div>
          <div className="mt-1 text-xs text-paper/60">{user.email}</div>
        </div>
        <div className="flex flex-col gap-1 px-3">
          <NavItem to="/">Dashboard</NavItem>
          <NavItem to="/cases">Recovery feed</NavItem>
          <NavItem to="/copilot">Copilot</NavItem>
        </div>
        <button onClick={logout} className="absolute bottom-6 left-6 text-xs text-paper/60 hover:text-paper">
          Sign out
        </button>
      </nav>
      <main className="flex-1 overflow-y-auto">{children}</main>
    </div>
  )
}

export default function App() {
  return (
    <Routes>
      <Route path="/login" element={<Login />} />
      <Route
        path="/"
        element={
          <ProtectedLayout>
            <Dashboard />
          </ProtectedLayout>
        }
      />
      <Route
        path="/cases"
        element={
          <ProtectedLayout>
            <RecoveryFeed />
          </ProtectedLayout>
        }
      />
      <Route
        path="/cases/:id"
        element={
          <ProtectedLayout>
            <CaseDetail />
          </ProtectedLayout>
        }
      />
      <Route
        path="/copilot"
        element={
          <ProtectedLayout>
            <Copilot />
          </ProtectedLayout>
        }
      />
    </Routes>
  )
}
