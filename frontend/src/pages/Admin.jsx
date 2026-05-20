import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import {
  BarChart2, Users, AlertTriangle, RefreshCw,
  CheckCircle, XCircle, Loader, Shield, ArrowLeft
} from 'lucide-react'
import { adminAPI } from '../lib/api'

export default function Admin({ user, onBack }) {
  const [stats, setStats] = useState(null)
  const [dlqItems, setDlqItems] = useState([])
  const [users, setUsers] = useState([])
  const [loading, setLoading] = useState(true)
  const [activeTab, setActiveTab] = useState('overview')
  const [actionMsg, setActionMsg] = useState(null)

  useEffect(() => {
    loadData()
  }, [])

  const loadData = async () => {
    setLoading(true)
    try {
      const [statsRes, dlqRes, usersRes] = await Promise.all([
        adminAPI.stats(),
        adminAPI.dlq(),
        adminAPI.users(),
      ])
      setStats(statsRes.data)
      setDlqItems(dlqRes.data)
      setUsers(usersRes.data)
    } catch (e) {
      console.error('Admin load failed', e)
    } finally {
      setLoading(false)
    }
  }

  const handleRequeue = async (correlationId) => {
    try {
      await adminAPI.requeueDLQ(correlationId)
      setDlqItems((prev) => prev.filter((i) => i.correlation_id !== correlationId))
      showAction('Item re-queued successfully')
    } catch (e) {
      showAction('Requeue failed: ' + (e.response?.data?.detail || e.message), true)
    }
  }

  const handleRoleChange = async (userId, newRole) => {
    try {
      await adminAPI.updateRole(userId, newRole)
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, role: newRole } : u))
      showAction('Role updated')
    } catch (e) {
      showAction('Role update failed', true)
    }
  }

  const handleStatusChange = async (userId, isActive) => {
    try {
      await adminAPI.updateStatus(userId, isActive)
      setUsers((prev) => prev.map((u) => u.id === userId ? { ...u, is_active: isActive } : u))
      showAction(`User ${isActive ? 'activated' : 'deactivated'}`)
    } catch (e) {
      showAction('Status update failed', true)
    }
  }

  const handleTriggerRetention = async () => {
    try {
      await adminAPI.triggerRetention()
      showAction('Retention job triggered')
    } catch (e) {
      showAction('Failed to trigger retention', true)
    }
  }

  const showAction = (msg, isError = false) => {
    setActionMsg({ msg, isError })
    setTimeout(() => setActionMsg(null), 3000)
  }

  if (loading) {
    return (
      <div className="min-h-screen bg-gray-50 flex items-center justify-center">
        <Loader className="w-6 h-6 animate-spin text-indigo-500" />
      </div>
    )
  }

  const TABS = [
    { id: 'overview', label: 'Overview', icon: BarChart2 },
    { id: 'dlq', label: `DLQ (${dlqItems.length})`, icon: AlertTriangle },
    { id: 'users', label: 'Users', icon: Users },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      {/* Header */}
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <button onClick={onBack} className="p-1.5 rounded-lg hover:bg-gray-100 transition-colors">
              <ArrowLeft className="w-4 h-4 text-gray-600" />
            </button>
            <Shield className="w-5 h-5 text-indigo-600" />
            <span className="font-semibold text-gray-900">Admin Panel</span>
          </div>
          <div className="flex items-center gap-3">
            <button
              onClick={loadData}
              className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-gray-900 transition-colors"
            >
              <RefreshCw className="w-4 h-4" /> Refresh
            </button>
            <button
              onClick={handleTriggerRetention}
              className="text-sm px-3 py-1.5 bg-amber-50 text-amber-700 rounded-lg border border-amber-200 hover:bg-amber-100 transition-colors"
            >
              Run Retention
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6">
        {/* Action feedback */}
        {actionMsg && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            className={`mb-4 p-3 rounded-xl border text-sm flex items-center gap-2 ${
              actionMsg.isError
                ? 'bg-red-50 border-red-200 text-red-700'
                : 'bg-green-50 border-green-200 text-green-700'
            }`}
          >
            {actionMsg.isError ? <XCircle className="w-4 h-4" /> : <CheckCircle className="w-4 h-4" />}
            {actionMsg.msg}
          </motion.div>
        )}

        {/* Tabs */}
        <div className="flex gap-1 mb-6">
          {TABS.map(({ id, label, icon: Icon }) => (
            <button
              key={id}
              onClick={() => setActiveTab(id)}
              className={`flex items-center gap-1.5 px-4 py-2 rounded-xl text-sm font-medium transition-colors ${
                activeTab === id
                  ? 'bg-indigo-600 text-white'
                  : 'bg-white text-gray-600 hover:text-gray-900 border border-gray-200'
              }`}
            >
              <Icon className="w-4 h-4" />
              {label}
            </button>
          ))}
        </div>

        {/* Overview Tab */}
        {activeTab === 'overview' && stats && (
          <div className="space-y-6">
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
              {[
                { label: 'Tasks Today', value: stats.total_tasks_today, color: 'indigo' },
                { label: 'Tokens Today', value: stats.total_tokens_today?.toLocaleString(), color: 'purple' },
                { label: 'Active Users Today', value: stats.active_users_today, color: 'green' },
                { label: 'DLQ Items', value: stats.dlq_count, color: 'red' },
              ].map(({ label, value, color }) => (
                <div key={label} className="bg-white rounded-2xl border border-gray-200 p-5">
                  <p className="text-2xl font-bold text-gray-900">{value}</p>
                  <p className="text-sm text-gray-500 mt-0.5">{label}</p>
                </div>
              ))}
            </div>

            {/* Agent Success Rates */}
            <div className="bg-white rounded-2xl border border-gray-200 p-6">
              <h3 className="font-semibold text-gray-900 mb-4">Agent Success Rates (7 days)</h3>
              <div className="space-y-3">
                {Object.entries(stats.agent_success_rates || {}).map(([agent, rate]) => (
                  <div key={agent}>
                    <div className="flex justify-between text-sm mb-1">
                      <span className="capitalize text-gray-700">{agent}</span>
                      <span className="text-gray-500">{(rate * 100).toFixed(0)}%</span>
                    </div>
                    <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                      <motion.div
                        className={`h-full rounded-full ${rate >= 0.9 ? 'bg-green-500' : rate >= 0.7 ? 'bg-amber-500' : 'bg-red-500'}`}
                        initial={{ width: 0 }}
                        animate={{ width: `${rate * 100}%` }}
                        transition={{ duration: 0.8 }}
                      />
                    </div>
                  </div>
                ))}
                {Object.keys(stats.agent_success_rates || {}).length === 0 && (
                  <p className="text-sm text-gray-400">No agent data in last 7 days</p>
                )}
              </div>
            </div>
          </div>
        )}

        {/* DLQ Tab */}
        {activeTab === 'dlq' && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="font-semibold text-gray-900">Dead Letter Queue</h3>
              <p className="text-sm text-gray-500 mt-0.5">Failed tasks that need manual intervention</p>
            </div>
            {dlqItems.length === 0 ? (
              <div className="p-10 text-center">
                <CheckCircle className="w-10 h-10 text-green-400 mx-auto mb-3" />
                <p className="text-gray-500">DLQ is empty — all good!</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {dlqItems.map((item, i) => (
                  <div key={i} className="p-6 hover:bg-gray-50 transition-colors">
                    <div className="flex items-start justify-between gap-4">
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-xs font-medium bg-red-100 text-red-700 px-2 py-0.5 rounded-full">
                            {item.agent_name}
                          </span>
                          <span className="text-xs text-gray-400">{item.error_type}</span>
                        </div>
                        <p className="text-sm text-gray-700 truncate">{item.error_message}</p>
                        <p className="text-xs text-gray-400 mt-1 font-mono">{item.correlation_id}</p>
                      </div>
                      <button
                        onClick={() => handleRequeue(item.correlation_id)}
                        className="flex items-center gap-1.5 px-3 py-1.5 bg-indigo-50 text-indigo-700 rounded-lg text-sm font-medium hover:bg-indigo-100 transition-colors flex-shrink-0"
                      >
                        <RefreshCw className="w-3.5 h-3.5" /> Re-queue
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}

        {/* Users Tab */}
        {activeTab === 'users' && (
          <div className="bg-white rounded-2xl border border-gray-200 overflow-hidden">
            <div className="px-6 py-4 border-b border-gray-200">
              <h3 className="font-semibold text-gray-900">All Users ({users.length})</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-sm">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="text-left px-6 py-3 text-gray-500 font-medium">User</th>
                    <th className="text-left px-6 py-3 text-gray-500 font-medium">Role</th>
                    <th className="text-left px-6 py-3 text-gray-500 font-medium">Status</th>
                    <th className="text-left px-6 py-3 text-gray-500 font-medium">Joined</th>
                    <th className="text-left px-6 py-3 text-gray-500 font-medium">Actions</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {users.map((u) => (
                    <tr key={u.id} className="hover:bg-gray-50 transition-colors">
                      <td className="px-6 py-3">
                        <p className="font-medium text-gray-900">{u.name}</p>
                        <p className="text-xs text-gray-400">{u.email}</p>
                      </td>
                      <td className="px-6 py-3">
                        <select
                          value={u.role}
                          onChange={(e) => handleRoleChange(u.id, e.target.value)}
                          disabled={u.id === user?.id}
                          className="text-xs border border-gray-300 rounded-lg px-2 py-1 focus:outline-none focus:ring-1 focus:ring-indigo-500 disabled:opacity-50"
                        >
                          <option value="standard">Standard</option>
                          <option value="admin">Admin</option>
                        </select>
                      </td>
                      <td className="px-6 py-3">
                        <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                          u.is_active ? 'bg-green-100 text-green-700' : 'bg-red-100 text-red-700'
                        }`}>
                          {u.is_active ? 'Active' : 'Inactive'}
                        </span>
                      </td>
                      <td className="px-6 py-3 text-xs text-gray-400">
                        {u.created_at && new Date(u.created_at).toLocaleDateString()}
                      </td>
                      <td className="px-6 py-3">
                        {u.id !== user?.id && (
                          <button
                            onClick={() => handleStatusChange(u.id, !u.is_active)}
                            className={`text-xs px-2 py-1 rounded-lg border transition-colors ${
                              u.is_active
                                ? 'border-red-200 text-red-600 hover:bg-red-50'
                                : 'border-green-200 text-green-600 hover:bg-green-50'
                            }`}
                          >
                            {u.is_active ? 'Deactivate' : 'Activate'}
                          </button>
                        )}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </main>
    </div>
  )
}
