import { lazy, Suspense, type ReactNode } from 'react'
import { createBrowserRouter, RouterProvider } from 'react-router'
import { RequireAdmin, RequireAuth } from './components/guards'
import { Spinner } from './components/ui'
import { AuthProvider } from './contexts/AuthContext'
import { ToastProvider } from './contexts/ToastContext'
import { AppLayout } from './layouts/AppLayout'

const Landing = lazy(() => import('./pages/Landing'))
const Discover = lazy(() => import('./pages/Discover'))
const BookDetail = lazy(() => import('./pages/BookDetail'))
const ForYou = lazy(() => import('./pages/ForYou'))
const SmartSearch = lazy(() => import('./pages/SmartSearch'))
const Assistant = lazy(() => import('./pages/Assistant'))
const Compare = lazy(() => import('./pages/Compare'))
const ReadingPlans = lazy(() => import('./pages/ReadingPlans'))
const BookOffers = lazy(() => import('./pages/BookOffers'))
const Marketplace = lazy(() => import('./pages/Marketplace'))
const UsedSearch = lazy(() => import('./pages/UsedSearch'))
const ListingDetail = lazy(() => import('./pages/ListingDetail'))
const SellBook = lazy(() => import('./pages/SellBook'))
const SellerDashboard = lazy(() => import('./pages/SellerDashboard'))
const SellerProfile = lazy(() => import('./pages/SellerProfile'))
const Saved = lazy(() => import('./pages/Saved'))
const Bookshelf = lazy(() => import('./pages/Bookshelf'))
const History = lazy(() => import('./pages/History'))
const Settings = lazy(() => import('./pages/Settings'))
const Login = lazy(() => import('./pages/Login'))
const Register = lazy(() => import('./pages/Register'))
const ForgotPassword = lazy(() => import('./pages/ForgotPassword'))
const Admin = lazy(() => import('./pages/Admin'))
const Moderation = lazy(() => import('./pages/Moderation'))
const NotFound = lazy(() => import('./pages/NotFound'))

const page = (el: ReactNode) => <Suspense fallback={<div className="py-24 text-center"><Spinner /></div>}>{el}</Suspense>
const auth = (el: ReactNode) => page(<RequireAuth>{el}</RequireAuth>)
const admin = (el: ReactNode) => page(<RequireAdmin>{el}</RequireAdmin>)

export const routes = [
  {
    element: <AppLayout />,
    children: [
      { path: '/', element: page(<Landing />) },
      { path: '/discover', element: page(<Discover />) },
      { path: '/books/:id', element: page(<BookDetail />) },
      { path: '/books/:id/offers', element: page(<BookOffers />) },
      { path: '/for-you', element: page(<ForYou />) },
      { path: '/search', element: page(<SmartSearch />) },
      { path: '/assistant', element: page(<Assistant />) },
      { path: '/compare', element: page(<Compare />) },
      { path: '/plans', element: auth(<ReadingPlans />) },
      { path: '/marketplace', element: page(<Marketplace />) },
      { path: '/marketplace/find', element: page(<UsedSearch />) },
      { path: '/marketplace/listings/:id', element: page(<ListingDetail />) },
      { path: '/sell', element: auth(<SellBook />) },
      { path: '/sell/:id/edit', element: auth(<SellBook />) },
      { path: '/seller', element: auth(<SellerDashboard />) },
      { path: '/sellers/:id', element: page(<SellerProfile />) },
      { path: '/saved', element: auth(<Saved />) },
      { path: '/shelf', element: auth(<Bookshelf />) },
      { path: '/history', element: auth(<History />) },
      { path: '/settings', element: auth(<Settings />) },
      { path: '/login', element: page(<Login />) },
      { path: '/register', element: page(<Register />) },
      { path: '/forgot-password', element: page(<ForgotPassword />) },
      { path: '/admin', element: admin(<Admin />) },
      { path: '/admin/moderation', element: admin(<Moderation />) },
      { path: '*', element: page(<NotFound />) },
    ],
  },
]

const router = createBrowserRouter(routes)

export default function App() {
  return (
    <ToastProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ToastProvider>
  )
}
