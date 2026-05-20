import { useState } from 'react'
import { motion } from 'framer-motion'
import { Send, Loader, Sparkles } from 'lucide-react'

const EXAMPLE_TASKS = [
  "Create a marketing campaign for a coffee shop and generate an email proposal",
  "Analyze competitors in the B2B SaaS space and create a positioning strategy",
  "Write a social media content calendar for a fitness brand for the next month",
  "Generate a business plan for an online tutoring platform targeting high schoolers",
]

export default function TaskForm({ onTaskCreated, loading }) {
  const [instruction, setInstruction] = useState('')
  const [charCount, setCharCount] = useState(0)

  const handleChange = (e) => {
    setInstruction(e.target.value)
    setCharCount(e.target.value.length)
  }

  const handleSubmit = async (e) => {
    e.preventDefault()
    if (!instruction.trim() || loading) return
    await onTaskCreated(instruction.trim())
    setInstruction('')
    setCharCount(0)
  }

  const handleExample = (example) => {
    setInstruction(example)
    setCharCount(example.length)
  }

  return (
    <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
      <div className="flex items-center gap-2 mb-4">
        <Sparkles className="w-5 h-5 text-indigo-500" />
        <h2 className="text-lg font-semibold text-gray-900">New Automation Task</h2>
      </div>

      <form onSubmit={handleSubmit}>
        <div className="relative">
          <textarea
            value={instruction}
            onChange={handleChange}
            placeholder="Describe what you need automated... e.g. 'Create a marketing campaign for my coffee shop'"
            className="w-full h-32 px-4 py-3 rounded-xl border border-gray-300 text-gray-900 placeholder-gray-400 
                       focus:outline-none focus:ring-2 focus:ring-indigo-500 focus:border-transparent
                       resize-none text-sm transition-all"
            maxLength={5000}
            disabled={loading}
          />
          <span className="absolute bottom-3 right-3 text-xs text-gray-400">{charCount}/5000</span>
        </div>

        <div className="mt-3 flex flex-wrap gap-2">
          {EXAMPLE_TASKS.map((ex, i) => (
            <button
              key={i}
              type="button"
              onClick={() => handleExample(ex)}
              className="text-xs px-3 py-1.5 rounded-full bg-indigo-50 text-indigo-600 hover:bg-indigo-100 
                         transition-colors border border-indigo-100 text-left line-clamp-1 max-w-xs"
            >
              {ex.substring(0, 50)}...
            </button>
          ))}
        </div>

        <div className="mt-4 flex justify-end">
          <motion.button
            type="submit"
            disabled={!instruction.trim() || loading}
            whileHover={{ scale: 1.02 }}
            whileTap={{ scale: 0.98 }}
            className="flex items-center gap-2 px-6 py-2.5 bg-indigo-600 text-white rounded-xl font-medium
                       hover:bg-indigo-700 disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
          >
            {loading ? (
              <><Loader className="w-4 h-4 animate-spin" /> Processing...</>
            ) : (
              <><Send className="w-4 h-4" /> Submit Task</>
            )}
          </motion.button>
        </div>
      </form>
    </div>
  )
}
