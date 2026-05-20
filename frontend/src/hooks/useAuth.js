import { useState, useEffect, useCallback } from 'react'
import { authAPI } from '../lib/api'

export function useAuth() {
  const [user, setUser] = useState(null)
  const [loading, setLoading] = useState(true)

  const loadUser = useCallback(async () => {
    const token = localStorage.getItem('access_token')
    if (!token) {
      setLoading(false)
      return
    }
    try {
      const res = await authAPI.me()
      setUser(res.data)
    } catch {
      localStorage.removeItem('access_token')
      localStorage.removeItem('refresh_token')
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    loadUser()
  }, [loadUser])

  const login = async (email, password) => {
    const res = await authAPI.login({ email, password })
    localStorage.setItem('access_token', res.data.access_token)
    localStorage.setItem('refresh_token', res.data.refresh_token)
    const me = await authAPI.me()
    setUser(me.data)
    return me.data
  }

  const register = async (name, email, password) => {
    await authAPI.register({ name, email, password })
    return login(email, password)
  }

  const logout = async () => {
    const refreshToken = localStorage.getItem('refresh_token')
    try {
      await authAPI.logout(refreshToken)
    } catch {}
    localStorage.clear()
    setUser(null)
  }

  return { user, loading, login, register, logout }
}
