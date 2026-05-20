import { useState, useEffect, useRef, useCallback } from 'react'

const SCHEMA_HANDLERS = {
  v1: (event) => event,
}

export function useSSE(taskId) {
  const [events, setEvents] = useState([])
  const [agentStatuses, setAgentStatuses] = useState({})
  const [isComplete, setIsComplete] = useState(false)
  const [finalOutput, setFinalOutput] = useState(null)
  const [error, setError] = useState(null)
  const esRef = useRef(null)

  const connect = useCallback(() => {
    if (!taskId) return
    const token = localStorage.getItem('access_token')
    if (!token) return

    const API_BASE = import.meta.env.VITE_API_URL || ''
    const url = `${API_BASE}/api/v1/stream/${taskId}?token=${token}`

    esRef.current = new EventSource(url)

    esRef.current.onmessage = (e) => {
      try {
        const event = JSON.parse(e.data)
        if (event.event_type === 'connected') return

        // Handle schema versioning
        const version = event.event_schema_version || 'v1'
        const handler = SCHEMA_HANDLERS[version] || SCHEMA_HANDLERS['v1']
        const processed = handler(event)

        setEvents((prev) => [...prev, processed])

        switch (processed.event_type) {
          case 'agent_started':
            setAgentStatuses((prev) => ({
              ...prev,
              [processed.data.agent_name]: {
                status: 'running',
                description: processed.data.description,
                startedAt: processed.timestamp,
              }
            }))
            break

          case 'agent_completed':
            setAgentStatuses((prev) => ({
              ...prev,
              [processed.data.agent_name]: {
                status: 'completed',
                summary: processed.data.output_summary,
                duration: processed.data.duration_ms,
                completedAt: processed.timestamp,
              }
            }))
            break

          case 'fallback_activated':
            setAgentStatuses((prev) => ({
              ...prev,
              [processed.data.agent_name]: {
                status: 'fallback',
                reason: processed.data.reason,
                userMessage: processed.data.user_message,
              }
            }))
            break

          case 'task_completed':
            setFinalOutput(processed.data.final_output)
            setIsComplete(true)
            esRef.current?.close()
            break

          case 'task_failed':
            setError(processed.data.message || 'Task failed')
            setIsComplete(true)
            esRef.current?.close()
            break

          default:
            break
        }
      } catch (err) {
        console.error('SSE parse error:', err)
      }
    }

    esRef.current.onerror = () => {
      setError('Connection lost. Please refresh the page.')
      esRef.current?.close()
    }
  }, [taskId])

  useEffect(() => {
    connect()
    return () => {
      esRef.current?.close()
    }
  }, [connect])

  return { events, agentStatuses, isComplete, finalOutput, error }
}
