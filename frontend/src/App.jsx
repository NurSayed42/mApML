import { useState } from 'react'
import { useAuth } from './hooks/useAuth'
import Dashboard from './components/Dashboard'
import Login from './pages/Login'
import Register from './pages/Register'
import Admin from './pages/Admin'
import { Loader, Zap } from 'lucide-react'

export default function App() {
  const { user, loading, login, register, logout } = useAuth()
  const [page, setPage] = useState('login') // 'login' | 'register' | 'admin'

  // Global loading splash
  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex flex-col items-center justify-center gap-3">
        <div className="w-12 h-12 rounded-2xl bg-indigo-600 flex items-center justify-center">
          <Zap className="w-6 h-6 text-white" />
        </div>
        <Loader className="w-5 h-5 animate-spin text-indigo-500" />
        <p className="text-sm text-gray-400">Starting platform...</p>
      </div>
    )
  }

  // Not authenticated
  if (!user) {
    if (page === 'register') {
      return (
        <Register
          onRegister={async (name, email, password) => {
            await register(name, email, password)
            setPage('login')
          }}
          onSwitchToLogin={() => setPage('login')}
        />
      )
    }
    return (
      <Login
        onLogin={login}
        onSwitchToRegister={() => setPage('register')}
      />
    )
  }

  // Admin page
  if (page === 'admin' && user.role === 'admin') {
    return <Admin user={user} onBack={() => setPage('dashboard')} />
  }

  // Main dashboard
  return (
    <Dashboard
      user={user}
      onLogout={logout}
      onGoAdmin={() => setPage('admin')}
    />
  )
}
