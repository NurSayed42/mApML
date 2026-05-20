import { useState, useRef } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { Upload, File, Trash2, MessageSquare, Loader, CheckCircle, X } from 'lucide-react'
import { documentsAPI } from '../lib/api'

export default function DocumentUpload() {
  const [documents, setDocuments] = useState([])
  const [uploading, setUploading] = useState(false)
  const [dragOver, setDragOver] = useState(false)
  const [question, setQuestion] = useState('')
  const [answer, setAnswer] = useState(null)
  const [querying, setQuerying] = useState(false)
  const [selectedDocId, setSelectedDocId] = useState(null)
  const [error, setError] = useState(null)
  const fileRef = useRef()

  const loadDocuments = async () => {
    try {
      const res = await documentsAPI.list()
      setDocuments(res.data)
    } catch (e) {
      console.error(e)
    }
  }

  useState(() => { loadDocuments() }, [])

  const handleUpload = async (file) => {
    if (!file) return
    const maxMB = 10
    if (file.size > maxMB * 1024 * 1024) {
      setError(`File too large. Max ${maxMB}MB.`)
      return
    }

    setUploading(true)
    setError(null)
    const formData = new FormData()
    formData.append('file', file)

    try {
      const res = await documentsAPI.upload(formData)
      setDocuments((prev) => [res.data, ...prev])
    } catch (e) {
      setError(e.response?.data?.detail || 'Upload failed')
    } finally {
      setUploading(false)
    }
  }

  const handleDelete = async (id) => {
    try {
      await documentsAPI.delete(id)
      setDocuments((prev) => prev.filter((d) => d.id !== id))
      if (selectedDocId === id) setSelectedDocId(null)
    } catch (e) {
      setError('Delete failed')
    }
  }

  const handleQuery = async () => {
    if (!question.trim()) return
    setQuerying(true)
    setAnswer(null)
    setError(null)
    try {
      const res = await documentsAPI.query({
        question: question.trim(),
        document_id: selectedDocId || undefined,
      })
      setAnswer(res.data.answer)
    } catch (e) {
      setError(e.response?.data?.detail || 'Query failed')
    } finally {
      setQuerying(false)
    }
  }

  const handleDrop = (e) => {
    e.preventDefault()
    setDragOver(false)
    const file = e.dataTransfer.files[0]
    if (file) handleUpload(file)
  }

  return (
    <div className="space-y-6">
      {/* Upload Zone */}
      <div
        onDragOver={(e) => { e.preventDefault(); setDragOver(true) }}
        onDragLeave={() => setDragOver(false)}
        onDrop={handleDrop}
        onClick={() => fileRef.current?.click()}
        className={`border-2 border-dashed rounded-2xl p-10 text-center cursor-pointer transition-all ${
          dragOver ? 'border-indigo-400 bg-indigo-50' : 'border-gray-300 hover:border-indigo-300 hover:bg-gray-50'
        }`}
      >
        <input
          ref={fileRef}
          type="file"
          className="hidden"
          accept=".pdf,.docx,.doc,.txt"
          onChange={(e) => handleUpload(e.target.files[0])}
        />
        {uploading ? (
          <div className="flex flex-col items-center gap-2">
            <Loader className="w-8 h-8 text-indigo-500 animate-spin" />
            <p className="text-sm text-gray-600">Processing document...</p>
          </div>
        ) : (
          <div className="flex flex-col items-center gap-2">
            <Upload className="w-8 h-8 text-gray-400" />
            <p className="font-medium text-gray-700">Drop a file or click to upload</p>
            <p className="text-sm text-gray-400">PDF, DOCX, TXT — max 10MB</p>
          </div>
        )}
      </div>

      {error && (
        <div className="flex items-center gap-2 p-3 bg-red-50 border border-red-200 rounded-xl text-red-700 text-sm">
          <X className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      {/* Documents list */}
      {documents.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
          <h3 className="font-semibold text-gray-900 mb-4">Your Documents</h3>
          <div className="space-y-2">
            {documents.map((doc) => (
              <div
                key={doc.id}
                className={`flex items-center gap-3 p-3 rounded-xl border transition-all cursor-pointer ${
                  selectedDocId === doc.id
                    ? 'border-indigo-300 bg-indigo-50'
                    : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                }`}
                onClick={() => setSelectedDocId(selectedDocId === doc.id ? null : doc.id)}
              >
                <File className="w-5 h-5 text-gray-400 flex-shrink-0" />
                <div className="flex-1 min-w-0">
                  <p className="text-sm font-medium text-gray-900 truncate">{doc.filename}</p>
                  <p className="text-xs text-gray-400">{doc.chunk_count} chunks</p>
                </div>
                {selectedDocId === doc.id && (
                  <CheckCircle className="w-4 h-4 text-indigo-500" />
                )}
                <button
                  onClick={(e) => { e.stopPropagation(); handleDelete(doc.id) }}
                  className="p-1 text-gray-400 hover:text-red-500 transition-colors"
                >
                  <Trash2 className="w-4 h-4" />
                </button>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Q&A section */}
      {documents.length > 0 && (
        <div className="bg-white rounded-2xl shadow-sm border border-gray-200 p-6">
          <h3 className="font-semibold text-gray-900 mb-4 flex items-center gap-2">
            <MessageSquare className="w-4 h-4 text-indigo-500" />
            Ask a Question
            {selectedDocId && (
              <span className="text-xs bg-indigo-100 text-indigo-700 px-2 py-0.5 rounded-full">
                Searching selected document
              </span>
            )}
          </h3>

          <div className="flex gap-3">
            <input
              type="text"
              value={question}
              onChange={(e) => setQuestion(e.target.value)}
              onKeyDown={(e) => e.key === 'Enter' && handleQuery()}
              placeholder="What are the key findings in this document?"
              className="flex-1 px-4 py-2.5 rounded-xl border border-gray-300 text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500"
            />
            <button
              onClick={handleQuery}
              disabled={!question.trim() || querying}
              className="px-4 py-2.5 bg-indigo-600 text-white rounded-xl text-sm font-medium hover:bg-indigo-700 disabled:opacity-50 transition-colors"
            >
              {querying ? <Loader className="w-4 h-4 animate-spin" /> : 'Ask'}
            </button>
          </div>

          <AnimatePresence>
            {answer && (
              <motion.div
                initial={{ opacity: 0, y: 5 }}
                animate={{ opacity: 1, y: 0 }}
                className="mt-4 p-4 bg-gray-50 rounded-xl border border-gray-200 text-sm text-gray-700 whitespace-pre-wrap"
              >
                {answer}
              </motion.div>
            )}
          </AnimatePresence>
        </div>
      )}
    </div>
  )
}
