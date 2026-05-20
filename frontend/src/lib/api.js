import axios from 'axios'

const API_BASE = import.meta.env.VITE_API_URL || ''

const api = axios.create({
  baseURL: `${API_BASE}/api/v1`,
  timeout: 30000,
})

// Attach auth token to every request
api.interceptors.request.use((config) => {
  const token = localStorage.getItem('access_token')
  if (token) config.headers.Authorization = `Bearer ${token}`
  return config
})

// Handle 401 → refresh token
api.interceptors.response.use(
  (res) => res,
  async (err) => {
    const original = err.config
    if (err.response?.status === 401 && !original._retry) {
      original._retry = true
      const refreshToken = localStorage.getItem('refresh_token')
      if (refreshToken) {
        try {
          const res = await axios.post(`${API_BASE}/api/v1/auth/refresh`, {
            refresh_token: refreshToken
          })
          localStorage.setItem('access_token', res.data.access_token)
          original.headers.Authorization = `Bearer ${res.data.access_token}`
          return api(original)
        } catch {
          localStorage.clear()
          window.location.href = '/login'
        }
      }
    }
    return Promise.reject(err)
  }
)

// Auth
export const authAPI = {
  register: (data) => api.post('/auth/register', data),
  login: (data) => api.post('/auth/login', data),
  logout: (refreshToken) => api.post('/auth/logout', { refresh_token: refreshToken }),
  me: () => api.get('/auth/me'),
}

// Tasks
export const tasksAPI = {
  create: (data) => api.post('/tasks', data),
  list: (params) => api.get('/tasks', { params }),
  get: (id) => api.get(`/tasks/${id}`),
  getDAG: (id) => api.get(`/tasks/${id}/dag`),
}

// Scheduled tasks
export const scheduledAPI = {
  list: () => api.get('/tasks/scheduled'),
  create: (data) => api.post('/tasks/scheduled', data),
  cancel: (id) => api.delete(`/tasks/scheduled/${id}`),
}

// Documents
export const documentsAPI = {
  upload: (formData) => api.post('/documents', formData, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000,
  }),
  list: () => api.get('/documents'),
  query: (data) => api.post('/documents/query', data),
  delete: (id) => api.delete(`/documents/${id}`),
}

// Admin
export const adminAPI = {
  stats: () => api.get('/admin/stats'),
  dlq: () => api.get('/admin/dlq'),
  requeueDLQ: (correlationId) => api.post('/admin/dlq/requeue', { correlation_id: correlationId }),
  users: (params) => api.get('/admin/users', { params }),
  updateRole: (userId, role) => api.patch(`/admin/users/${userId}/role`, { role }),
  updateStatus: (userId, isActive) => api.patch(`/admin/users/${userId}/status`, { is_active: isActive }),
  tokenUsage: (days) => api.get('/admin/token-usage', { params: { days } }),
  errors: () => api.get('/admin/errors'),
  triggerRetention: () => api.post('/admin/retention/trigger'),
}

// Health
export const healthAPI = {
  check: () => api.get('/health'),
}

export default api
