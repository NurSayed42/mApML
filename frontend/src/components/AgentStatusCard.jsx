import { motion, AnimatePresence } from 'framer-motion'
import { CheckCircle, Loader, AlertTriangle, Clock, Zap, Search, FileText, Mail, BarChart2, GitMerge } from 'lucide-react'

const AGENT_CONFIG = {
  planner: { label: 'Planner', icon: Zap, color: 'purple', desc: 'Creates execution plan' },
  research: { label: 'Research', icon: Search, color: 'blue', desc: 'Gathers market intelligence' },
  content: { label: 'Content', icon: FileText, color: 'green', desc: 'Generates business content' },
  email: { label: 'Email', icon: Mail, color: 'orange', desc: 'Creates & sends emails' },
  analytics: { label: 'Analytics', icon: BarChart2, color: 'pink', desc: 'Scores & recommends' },
  aggregator: { label: 'Aggregator', icon: GitMerge, color: 'indigo', desc: 'Assembles final output' },
}

const COLOR_CLASSES = {
  purple: { bg: 'bg-purple-50', border: 'border-purple-200', icon: 'text-purple-600', badge: 'bg-purple-100 text-purple-700' },
  blue: { bg: 'bg-blue-50', border: 'border-blue-200', icon: 'text-blue-600', badge: 'bg-blue-100 text-blue-700' },
  green: { bg: 'bg-green-50', border: 'border-green-200', icon: 'text-green-600', badge: 'bg-green-100 text-green-700' },
  orange: { bg: 'bg-orange-50', border: 'border-orange-200', icon: 'text-orange-600', badge: 'bg-orange-100 text-orange-700' },
  pink: { bg: 'bg-pink-50', border: 'border-pink-200', icon: 'text-pink-600', badge: 'bg-pink-100 text-pink-700' },
  indigo: { bg: 'bg-indigo-50', border: 'border-indigo-200', icon: 'text-indigo-600', badge: 'bg-indigo-100 text-indigo-700' },
}

function StatusIcon({ status }) {
  if (status === 'completed') return <CheckCircle className="w-4 h-4 text-green-500" />
  if (status === 'running') return <Loader className="w-4 h-4 text-blue-500 animate-spin" />
  if (status === 'fallback') return <AlertTriangle className="w-4 h-4 text-amber-500" />
  return <Clock className="w-4 h-4 text-gray-400" />
}

function StatusBadge({ status }) {
  const labels = {
    completed: { text: 'Done', cls: 'bg-green-100 text-green-700' },
    running: { text: 'Working', cls: 'bg-blue-100 text-blue-700' },
    fallback: { text: 'Fallback', cls: 'bg-amber-100 text-amber-700' },
    idle: { text: 'Waiting', cls: 'bg-gray-100 text-gray-500' },
  }
  const cfg = labels[status] || labels.idle
  return (
    <span className={`text-xs font-medium px-2 py-0.5 rounded-full ${cfg.cls}`}>
      {cfg.text}
    </span>
  )
}

export default function AgentStatusCard({ agentName, status = {} }) {
  const config = AGENT_CONFIG[agentName] || { label: agentName, icon: Zap, color: 'indigo', desc: '' }
  const colors = COLOR_CLASSES[config.color]
  const Icon = config.icon
  const currentStatus = status.status || 'idle'
  const isRunning = currentStatus === 'running'

  return (
    <motion.div
      initial={{ opacity: 0, y: 8 }}
      animate={{ opacity: 1, y: 0 }}
      className={`relative rounded-xl border p-4 transition-all duration-300 ${
        isRunning
          ? `${colors.bg} ${colors.border} shadow-md`
          : currentStatus === 'completed'
          ? 'bg-green-50 border-green-200'
          : currentStatus === 'fallback'
          ? 'bg-amber-50 border-amber-200'
          : 'bg-white border-gray-200'
      }`}
    >
      {isRunning && (
        <motion.div
          className={`absolute inset-0 rounded-xl ${colors.bg} opacity-50`}
          animate={{ opacity: [0.3, 0.6, 0.3] }}
          transition={{ duration: 2, repeat: Infinity }}
        />
      )}

      <div className="relative flex items-start gap-3">
        <div className={`p-2 rounded-lg ${isRunning ? colors.bg : 'bg-gray-100'}`}>
          <Icon className={`w-5 h-5 ${isRunning ? colors.icon : 'text-gray-500'}`} />
        </div>

        <div className="flex-1 min-w-0">
          <div className="flex items-center justify-between gap-2">
            <span className="font-semibold text-gray-900 text-sm">{config.label}</span>
            <div className="flex items-center gap-1.5">
              <StatusIcon status={currentStatus} />
              <StatusBadge status={currentStatus} />
            </div>
          </div>

          <AnimatePresence mode="wait">
            {isRunning && status.description && (
              <motion.p
                key="desc"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                className="text-xs text-gray-600 mt-1 truncate"
              >
                {status.description}
              </motion.p>
            )}
            {currentStatus === 'completed' && status.summary && (
              <motion.p
                key="summary"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-xs text-green-700 mt-1 line-clamp-2"
              >
                {status.summary}
              </motion.p>
            )}
            {currentStatus === 'fallback' && (
              <motion.p
                key="fallback"
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                className="text-xs text-amber-700 mt-1"
              >
                {status.userMessage || 'Using simplified fallback content'}
              </motion.p>
            )}
            {currentStatus === 'idle' && (
              <p className="text-xs text-gray-400 mt-1">{config.desc}</p>
            )}
          </AnimatePresence>

          {currentStatus === 'completed' && status.duration && (
            <p className="text-xs text-gray-400 mt-1">{(status.duration / 1000).toFixed(1)}s</p>
          )}
        </div>
      </div>
    </motion.div>
  )
}
