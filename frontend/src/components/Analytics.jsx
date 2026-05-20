import { useState, useEffect } from 'react'
import { motion } from 'framer-motion'
import { BarChart2, TrendingUp, Zap, Loader } from 'lucide-react'
import { tasksAPI } from '../lib/api'

export default function Analytics() {
  const [tasks, setTasks] = useState([])
  const [loading, setLoading] = useState(true)

  useEffect(() => {
    const load = async () => {
      try {
        const res = await tasksAPI.list({ limit: 100 })
        setTasks(res.data.tasks)
      } catch (e) {
        console.error(e)
      } finally {
        setLoading(false)
      }
    }
    load()
  }, [])

  if (loading) {
    return (
      <div className="flex items-center justify-center h-48">
        <Loader className="w-6 h-6 animate-spin text-indigo-500" />
      </div>
    )
  }

  const statusCounts = tasks.reduce((acc, t) => {
    acc[t.status] = (acc[t.status] || 0) + 1
    return acc
  }, {})

  const completionRate = tasks.length > 0
    ? Math.round(((statusCounts.COMPLETED || 0) + (statusCounts.FALLBACK || 0)) / tasks.length * 100)
    : 0

  const statCards = [
    { label: 'Total Tasks', value: tasks.length, icon: BarChart2, color: 'indigo' },
    { label: 'Completed', value: statusCounts.COMPLETED || 0, icon: TrendingUp, color: 'green' },
    { label: 'Completion Rate', value: `${completionRate}%`, icon: Zap, color: 'purple' },
    { label: 'Fallback Used', value: statusCounts.FALLBACK || 0, icon: BarChart2, color: 'amber' },
  ]

  const colorMap = {
    indigo: 'bg-indigo-50 text-indigo-600',
    green: 'bg-green-50 text-green-600',
    purple: 'bg-purple-50 text-purple-600',
    amber: 'bg-amber-50 text-amber-600',
  }

  return (
    <div className="space-y-6">
      <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
        {statCards.map(({ label, value, icon: Icon, color }) => (
          <motion.div
            key={label}
            initial={{ opacity: 0, y: 8 }}
            animate={{ opacity: 1, y: 0 }}
            className="bg-white rounded-2xl shadow-sm border border-gray-200 p-5"
          >
            <div className={`w-10 h-10 rounded-xl ${colorMap[color]} flex items-center justify-center mb-3`}>
              <Icon className="w-5 h-5" />
            </div>
            <p className="text-2xl font-bold text-gray-900">{value}</p>
            <p className="text-sm text-gray-500 mt-0.5">{label}</p>
          </motion.div>
        ))}
      </div>

      {/* Task status breakdown */}
      <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
        <h3 className="font-semibold text-gray-900 mb-4">Task Status Breakdown</h3>
        <div className="space-y-3">
          {Object.entries(statusCounts).map(([status, count]) => {
            const pct = Math.round((count / tasks.length) * 100)
            const barColors = {
              COMPLETED: 'bg-green-500',
              FAILED: 'bg-red-500',
              FALLBACK: 'bg-amber-500',
              IN_PROGRESS: 'bg-blue-500',
              RECEIVED: 'bg-gray-400',
              PLANNED: 'bg-purple-500',
            }
            return (
              <div key={status}>
                <div className="flex justify-between text-sm mb-1">
                  <span className="text-gray-700">{status}</span>
                  <span className="text-gray-500">{count} ({pct}%)</span>
                </div>
                <div className="h-2 bg-gray-100 rounded-full overflow-hidden">
                  <motion.div
                    className={`h-full ${barColors[status] || 'bg-gray-400'} rounded-full`}
                    initial={{ width: 0 }}
                    animate={{ width: `${pct}%` }}
                    transition={{ duration: 0.8 }}
                  />
                </div>
              </div>
            )
          })}
        </div>
      </div>

      {/* Recent tasks table */}
      {tasks.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 overflow-hidden">
          <div className="px-6 py-4 border-b border-gray-200">
            <h3 className="font-semibold text-gray-900">Recent Tasks</h3>
          </div>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="bg-gray-50">
                <tr>
                  <th className="text-left px-6 py-3 text-gray-500 font-medium">Title</th>
                  <th className="text-left px-6 py-3 text-gray-500 font-medium">Status</th>
                  <th className="text-left px-6 py-3 text-gray-500 font-medium">Created</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {tasks.slice(0, 10).map((task) => (
                  <tr key={task.id} className="hover:bg-gray-50 transition-colors">
                    <td className="px-6 py-3 text-gray-900 truncate max-w-xs">{task.title}</td>
                    <td className="px-6 py-3">
                      <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${
                        task.status === 'COMPLETED' ? 'bg-green-100 text-green-700' :
                        task.status === 'FAILED' ? 'bg-red-100 text-red-700' :
                        task.status === 'FALLBACK' ? 'bg-amber-100 text-amber-700' :
                        'bg-gray-100 text-gray-600'
                      }`}>{task.status}</span>
                    </td>
                    <td className="px-6 py-3 text-gray-400 text-xs">
                      {task.created_at && new Date(task.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      )}
    </div>
  )
}
