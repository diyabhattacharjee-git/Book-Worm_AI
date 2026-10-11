import { BookMarked, ChevronDown, LogOut, Menu, Search, Shield, Store, X } from 'lucide-react'
import { useEffect, useRef, useState, type FormEvent } from 'react'
import { Link, NavLink, Outlet, useLocation, useNavigate } from 'react-router'
import { useAuth } from '../contexts/AuthContext'
import { useToast } from '../contexts/ToastContext'

const MAIN_NAV = [
  { to: '/discover', label: 'Discover' },
  { to: '/for-you', label: 'For You' },
  { to: '/search', label: 'Smart Search' },
  { to: '/assistant', label: 'Assistant' },
  { to: '/marketplace', label: 'Used Books' },
]

const USER_MENU = [
  { to: '/shelf', label: 'My bookshelf' },
  { to: '/history', label: 'History & goals' },
  { to: '/plans', label: 'Reading plans' },
  { to: '/saved', label: 'Saved' },
  { to: '/seller', label: 'Seller dashboard' },
  { to: '/settings', label: 'Profile & settings' },
]

function Logo() {
  return (
    <Link to="/" className="flex items-center gap-2" aria-label="BookWorm home">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink text-gold"><BookMarked className="h-4 w-4" aria-hidden /></span>
      <span className="font-serif text-xl font-semibold tracking-tight">BookWorm</span>
    </Link>
  )
}

export function AppLayout() {
  const { user, logout } = useAuth()
  const toast = useToast()
  const navigate = useNavigate()
  const location = useLocation()
  const [mobileOpen, setMobileOpen] = useState(false)
  const [menuOpen, setMenuOpen] = useState(false)
  const [q, setQ] = useState('')
  const menuRef = useRef<HTMLDivElement>(null)

  useEffect(() => {
    setMobileOpen(false)
    setMenuOpen(false)
  }, [location.pathname])

  useEffect(() => {
    function onClick(e: MouseEvent) {
      if (menuRef.current && !menuRef.current.contains(e.target as Node)) setMenuOpen(false)
    }
    document.addEventListener('mousedown', onClick)
    return () => document.removeEventListener('mousedown', onClick)
  }, [])

  function submitSearch(e: FormEvent) {
    e.preventDefault()
    const term = q.trim()
    if (term) navigate(`/discover?q=${encodeURIComponent(term)}`)
  }

  async function doLogout() {
    await logout()
    toast.info('You have been logged out.')
    navigate('/')
  }

  const navCls = ({ isActive }: { isActive: boolean }) =>
    `rounded-lg px-3 py-2 text-sm font-medium transition-colors ${isActive ? 'bg-parchment text-ink' : 'text-ink-soft hover:text-ink'}`

  return (
    <div className="flex min-h-screen flex-col">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:left-4 focus:top-4 focus:z-50 focus:rounded focus:bg-paper focus:px-3 focus:py-2">Skip to content</a>
      <header className="sticky top-0 z-40 border-b border-line bg-cream/90 backdrop-blur">
        <div className="mx-auto flex h-16 max-w-7xl items-center gap-4 px-4 sm:px-6">
          <Logo />
          <nav className="ml-4 hidden items-center gap-1 lg:flex" aria-label="Main">
            {MAIN_NAV.map((n) => <NavLink key={n.to} to={n.to} className={navCls}>{n.label}</NavLink>)}
          </nav>
          <form onSubmit={submitSearch} className="ml-auto hidden max-w-xs flex-1 md:block" role="search">
            <label htmlFor="global-search" className="sr-only">Search books</label>
            <div className="relative">
              <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted" aria-hidden />
              <input id="global-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Title, author or ISBN" className="input pl-9" />
            </div>
          </form>
          <div className="ml-auto flex items-center gap-2 md:ml-0">
            <Link to="/sell" className="btn-forest btn-sm hidden sm:inline-flex"><Store className="h-4 w-4" aria-hidden />Sell a book</Link>
            {user ? (
              <div className="relative" ref={menuRef}>
                <button onClick={() => setMenuOpen((o) => !o)} aria-expanded={menuOpen} aria-haspopup="menu"
                  className="flex items-center gap-2 rounded-full border border-line bg-paper py-1 pl-1 pr-2 text-sm hover:border-ink-soft">
                  {user.avatar_url ? <img src={user.avatar_url} alt="" className="h-7 w-7 rounded-full object-cover" />
                    : <span className="flex h-7 w-7 items-center justify-center rounded-full bg-gold-soft font-semibold text-gold-dark">{user.display_name[0]?.toUpperCase()}</span>}
                  <span className="hidden max-w-[8rem] truncate sm:inline">{user.display_name}</span>
                  <ChevronDown className="h-3.5 w-3.5" aria-hidden />
                </button>
                {menuOpen && (
                  <div role="menu" className="absolute right-0 mt-2 w-56 overflow-hidden rounded-xl border border-line bg-paper py-1 shadow-[var(--shadow-lift)]">
                    {USER_MENU.map((m) => <Link key={m.to} to={m.to} role="menuitem" className="block px-4 py-2 text-sm hover:bg-parchment">{m.label}</Link>)}
                    {user.role === 'admin' && <Link to="/admin" role="menuitem" className="flex items-center gap-2 px-4 py-2 text-sm hover:bg-parchment"><Shield className="h-4 w-4" aria-hidden />Admin</Link>}
                    <button role="menuitem" onClick={doLogout} className="flex w-full items-center gap-2 border-t border-line px-4 py-2 text-left text-sm hover:bg-parchment"><LogOut className="h-4 w-4" aria-hidden />Log out</button>
                  </div>
                )}
              </div>
            ) : (
              <div className="hidden items-center gap-2 sm:flex">
                <Link to="/login" className="btn-ghost btn-sm">Log in</Link>
                <Link to="/register" className="btn-primary btn-sm">Join free</Link>
              </div>
            )}
            <button className="btn-ghost btn-sm lg:hidden" onClick={() => setMobileOpen((o) => !o)} aria-expanded={mobileOpen} aria-label="Toggle navigation menu">
              {mobileOpen ? <X className="h-5 w-5" /> : <Menu className="h-5 w-5" />}
            </button>
          </div>
        </div>
        {mobileOpen && (
          <nav className="border-t border-line bg-paper px-4 py-3 lg:hidden" aria-label="Mobile">
            <form onSubmit={submitSearch} className="mb-3 md:hidden" role="search">
              <label htmlFor="mobile-search" className="sr-only">Search books</label>
              <input id="mobile-search" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Search title, author or ISBN" className="input" />
            </form>
            <div className="grid gap-1">
              {MAIN_NAV.map((n) => <NavLink key={n.to} to={n.to} className={navCls}>{n.label}</NavLink>)}
              <NavLink to="/marketplace/find" className={navCls}>Find a used deal</NavLink>
              <NavLink to="/sell" className={navCls}>Sell a book</NavLink>
              {!user && <><NavLink to="/login" className={navCls}>Log in</NavLink><NavLink to="/register" className={navCls}>Create account</NavLink></>}
            </div>
          </nav>
        )}
      </header>

      <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-8 sm:px-6 sm:py-10">
        <Outlet />
      </main>

      <footer className="border-t border-line bg-paper">
        <div className="mx-auto grid max-w-7xl gap-6 px-4 py-10 text-sm text-muted sm:px-6 md:grid-cols-3">
          <div>
            <Logo />
            <p className="mt-3 max-w-xs">Discover books, get recommendations you can understand, and buy second-hand copies at fair prices.</p>
          </div>
          <div className="grid grid-cols-2 gap-2">
            <Link to="/discover" className="hover:text-ink">Discover</Link>
            <Link to="/marketplace" className="hover:text-ink">Used books</Link>
            <Link to="/compare" className="hover:text-ink">Compare books</Link>
            <Link to="/marketplace/find" className="hover:text-ink">Find a deal</Link>
            <Link to="/plans" className="hover:text-ink">Reading plans</Link>
            <Link to="/sell" className="hover:text-ink">Sell a book</Link>
          </div>
          <p className="text-xs leading-relaxed">
            BookWorm doesn’t process payments, hold funds or guarantee transactions, and doesn’t verify every seller.
            Prices are sellers’ asking prices. Book metadata comes from Open Library and Google Books where available.
          </p>
        </div>
      </footer>
    </div>
  )
}
