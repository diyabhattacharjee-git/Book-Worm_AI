import { BookX } from 'lucide-react'
import { Link } from 'react-router'
import { EmptyState } from '../components/ui'

export default function NotFound() {
  return (
    <div className="mx-auto max-w-xl py-10">
      <EmptyState icon={<BookX className="h-6 w-6" />} title="This page isn’t on our shelves"
        action={<div className="flex gap-2"><Link to="/" className="btn-primary">Go home</Link><Link to="/discover" className="btn-outline">Browse books</Link></div>}>
        The link may be broken, or the page may have been removed.
      </EmptyState>
    </div>
  )
}
