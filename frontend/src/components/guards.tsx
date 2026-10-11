import { type ReactNode } from 'react'
import { Link, Navigate, useLocation } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { EmptyState, Spinner } from './ui'

export function RequireAuth({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) return <div className="py-20 text-center"><Spinner /></div>
  if (!user) return <Navigate to={`/login?next=${encodeURIComponent(location.pathname + location.search)}`} replace />
  return <>{children}</>
}

export function RequireAdmin({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  if (loading) return <div className="py-20 text-center"><Spinner /></div>
  if (!user) return <Navigate to="/login?next=/admin" replace />
  if (user.role !== 'admin') {
    return (
      <EmptyState title="Administrators only" action={<Link to="/" className="btn-outline">Go home</Link>}>
        Your account doesn’t have access to the admin area.
      </EmptyState>
    )
  }
  return <>{children}</>
}
