import { useState, useEffect } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { LogOut, FileText, BarChart2, Clock, CheckCircle, AlertCircle, Loader } from 'lucide-react'
import TaskForm from './TaskForm'
import AgentStatusCard from './AgentStatusCard'
import Analytics from './Analytics'
import DocumentUpload from './DocumentUpload'
import { tasksAPI } from '../lib/api'
import { useSSE } from '../hooks/useSSE'
import { formatDistanceToNow } from 'date-fns'

const AGENT_NAMES = ['planner', 'research', 'content', 'email', 'analytics', 'aggregator']

function ActiveTask({ task }) {
  const { agentStatuses, isComplete, finalOutput, error } = useSSE(task?.id)

  if (!task) return null

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center justify-between mb-4">
        <div>
          <h3 className="font-semibold text-gray-900">{task.title}</h3>
          <p className="text-xs text-gray-400 mt-0.5">ID: {task.id?.slice(0, 8)}...</p>
        </div>
        <StatusBadge status={isComplete ? (error ? 'FAILED' : 'COMPLETED') : 'IN_PROGRESS'} />
      </div>

      <div className="grid grid-cols-2 md:grid-cols-3 gap-3 mb-4">
        {AGENT_NAMES.map((name) => (
          <AgentStatusCard key={name} agentName={name} status={agentStatuses[name] || {}} />
        ))}
      </div>

      {error && (
        <div className="mt-4 p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          <AlertCircle className="w-4 h-4 inline mr-2" />
          {error}
        </div>
      )}

      {finalOutput && <TaskOutput output={finalOutput} />}
    </div>
  )
}

function TaskOutput({ output }) {
  const [copied, setCopied] = useState(null)

  const copySection = (key, content) => {
    navigator.clipboard.writeText(typeof content === 'string' ? content : JSON.stringify(content, null, 2))
    setCopied(key)
    setTimeout(() => setCopied(null), 2000)
  }

  const sections = output.sections || {}
  const hasFallback = output.metadata?.has_fallback_sections

  return (
    <motion.div
      initial={{ opacity: 0, y: 10 }}
      animate={{ opacity: 1, y: 0 }}
      className="mt-6 space-y-4"
    >
      <div className="flex items-center gap-2">
        <CheckCircle className="w-5 h-5 text-green-500" />
        <h4 className="font-semibold text-gray-900">Task Complete</h4>
        {hasFallback && (
          <span className="text-xs bg-amber-100 text-amber-700 px-2 py-0.5 rounded-full">
            Some sections used fallback
          </span>
        )}
      </div>

      {Object.entries(sections).map(([sectionName, content]) => (
        <div key={sectionName} className="border border-gray-200 rounded-xl overflow-hidden">
          <div className="flex items-center justify-between px-4 py-2 bg-gray-50 border-b border-gray-200">
            <span className="font-medium text-gray-700 text-sm">{sectionName}</span>
            <button
              onClick={() => copySection(sectionName, content)}
              className="text-xs text-gray-500 hover:text-gray-700 transition-colors"
            >
              {copied === sectionName ? '✓ Copied' : 'Copy'}
            </button>
          </div>
          <div className="p-4 text-sm text-gray-700">
            {typeof content === 'object' ? (
              <AnalyticsSection data={content} />
            ) : (
              <pre className="whitespace-pre-wrap font-sans">{content}</pre>
            )}
          </div>
        </div>
      ))}
    </motion.div>
  )
}

function AnalyticsSection({ data }) {
  if (!data) return null
  const score = data.engagement_score || 0
  const category = data.score_category || 'Unknown'
  const recs = data.recommendations || []
  const scoreColor = category === 'High' ? 'text-green-600' : category === 'Medium' ? 'text-amber-600' : 'text-red-600'
  const barColor = category === 'High' ? 'bg-green-500' : category === 'Medium' ? 'bg-amber-500' : 'bg-red-500'

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-4">
        <div>
          <span className={`text-4xl font-bold ${scoreColor}`}>{score}</span>
          <span className="text-gray-500 text-sm">/100</span>
          <span className={`ml-2 text-sm font-medium ${scoreColor}`}>({category})</span>
        </div>
        <div className="flex-1">
          <div className="h-3 bg-gray-100 rounded-full overflow-hidden">
            <motion.div
              className={`h-full ${barColor} rounded-full`}
              initial={{ width: 0 }}
              animate={{ width: `${score}%` }}
              transition={{ duration: 1, ease: 'easeOut' }}
            />
          </div>
        </div>
      </div>

      {data.score_breakdown && (
        <div className="grid grid-cols-2 gap-2 text-xs">
          {Object.entries(data.score_breakdown).map(([key, val]) => (
            <div key={key} className="flex justify-between text-gray-600">
              <span className="capitalize">{key.replace(/_/g, ' ')}</span>
              <span className="font-medium">{val}/20</span>
            </div>
          ))}
        </div>
      )}

      {recs.length > 0 && (
        <div>
          <p className="font-medium text-gray-900 mb-2">Growth Recommendations</p>
          <div className="space-y-2">
            {recs.map((rec, i) => (
              <div key={i} className="bg-indigo-50 rounded-lg p-3">
                <p className="font-medium text-indigo-900 text-xs">{rec.title}</p>
                <p className="text-indigo-700 text-xs mt-0.5">{rec.action}</p>
              </div>
            ))}
          </div>
        </div>
      )}
    </div>
  )
}

function StatusBadge({ status }) {
  const configs = {
    COMPLETED: { cls: 'bg-green-100 text-green-700', label: 'Completed' },
    FAILED: { cls: 'bg-red-100 text-red-700', label: 'Failed' },
    IN_PROGRESS: { cls: 'bg-blue-100 text-blue-700', label: 'In Progress' },
    RECEIVED: { cls: 'bg-gray-100 text-gray-600', label: 'Received' },
    PLANNED: { cls: 'bg-purple-100 text-purple-700', label: 'Planned' },
    FALLBACK: { cls: 'bg-amber-100 text-amber-700', label: 'Fallback' },
  }
  const cfg = configs[status] || configs.RECEIVED
  return <span className={`text-xs font-medium px-2 py-1 rounded-full ${cfg.cls}`}>{cfg.label}</span>
}

export default function Dashboard({ user, onLogout }) {
  const [activeTask, setActiveTask] = useState(null)
  const [taskHistory, setTaskHistory] = useState([])
  const [submitting, setSubmitting] = useState(false)
  const [activeTab, setActiveTab] = useState('tasks')
  const [error, setError] = useState(null)

  useEffect(() => {
    loadTaskHistory()
  }, [])

  const loadTaskHistory = async () => {
    try {
      const res = await tasksAPI.list({ limit: 20 })
      setTaskHistory(res.data.tasks)
    } catch (e) {
      console.error('Failed to load tasks', e)
    }
  }

  const handleTaskCreate = async (instruction) => {
    setSubmitting(true)
    setError(null)
    try {
      const res = await tasksAPI.create({ instruction })
      const newTask = res.data

      // Set as active task
      setActiveTask(newTask)

      // Add to history only if not already present (prevent duplicate keys)
      setTaskHistory((prev) => {
        const exists = prev.some((t) => t.id === newTask.id)
        if (exists) {
          // Update existing entry status
          return prev.map((t) => t.id === newTask.id ? newTask : t)
        }
        // Prepend new task
        return [newTask, ...prev]
      })
    } catch (e) {
      setError(e.response?.data?.detail || 'Failed to submit task')
    } finally {
      setSubmitting(false)
    }
  }

  const TABS = [
    { id: 'tasks', label: 'Tasks', icon: FileText },
    { id: 'documents', label: 'Documents', icon: FileText },
    { id: 'analytics', label: 'Analytics', icon: BarChart2 },
  ]

  return (
    <div className="min-h-screen bg-gray-50">
      <header className="bg-white border-b border-gray-200 sticky top-0 z-10">
        <div className="max-w-6xl mx-auto px-4 py-3 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 rounded-lg bg-indigo-600 flex items-center justify-center">
              <span className="text-white font-bold text-sm">AI</span>
            </div>
            <span className="font-semibold text-gray-900">AutoAgent Platform</span>
          </div>

          <nav className="hidden md:flex gap-1">
            {TABS.map(({ id, label, icon: Icon }) => (
              <button
                key={id}
                onClick={() => setActiveTab(id)}
                className={`flex items-center gap-1.5 px-4 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  activeTab === id
                    ? 'bg-indigo-50 text-indigo-700'
                    : 'text-gray-600 hover:text-gray-900 hover:bg-gray-100'
                }`}
              >
                <Icon className="w-4 h-4" />
                {label}
              </button>
            ))}
          </nav>

          <div className="flex items-center gap-3">
            <span className="text-sm text-gray-600 hidden md:block">{user?.name}</span>
            {user?.role === 'admin' && (
              <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-1 rounded-full font-medium">Admin</span>
            )}
            <button
              onClick={onLogout}
              className="flex items-center gap-1.5 text-sm text-gray-600 hover:text-red-600 transition-colors"
            >
              <LogOut className="w-4 h-4" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-6xl mx-auto px-4 py-6 space-y-6">
        {activeTab === 'tasks' && (
          <>
            <TaskForm onTaskCreated={handleTaskCreate} loading={submitting} />

            {error && (
              <div className="p-4 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
                {error}
              </div>
            )}

            <AnimatePresence mode="wait">
              {activeTask && (
                <motion.div
                  key={activeTask.id}
                  initial={{ opacity: 0, y: 8 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0 }}
                >
                  <ActiveTask task={activeTask} />
                </motion.div>
              )}
            </AnimatePresence>

            {taskHistory.length > 0 && (
              <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
                <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
                  <Clock className="w-4 h-4 text-gray-400" />
                  Task History
                </h3>
                <div className="space-y-2">
                  {taskHistory.map((task) => (
                    <motion.div
                      key={task.id}
                      initial={{ opacity: 0 }}
                      animate={{ opacity: 1 }}
                      className="flex items-center justify-between p-3 rounded-lg hover:bg-gray-50
                                 cursor-pointer transition-colors border border-transparent hover:border-gray-200"
                      onClick={() => setActiveTask(task)}
                    >
                      <div className="flex-1 min-w-0">
                        <p className="text-sm font-medium text-gray-900 truncate">{task.title}</p>
                        <p className="text-xs text-gray-400 mt-0.5">
                          {task.created_at && formatDistanceToNow(new Date(task.created_at), { addSuffix: true })}
                        </p>
                      </div>
                      <StatusBadge status={task.status} />
                    </motion.div>
                  ))}
                </div>
              </div>
            )}
          </>
        )}

        {activeTab === 'documents' && <DocumentUpload userId={user?.id} />}
        {activeTab === 'analytics' && <Analytics />}
      </main>
    </div>
  )
}