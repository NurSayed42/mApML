# Multi-Agent AI Business Automation Platform

An AI automation platform where six specialized agents collaborate to complete complex business tasks from a single instruction.

![Python 3.11](https://img.shields.io/badge/Python-3.11-blue?style=flat-square&logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.111-green?style=flat-square&logo=fastapi)
![React](https://img.shields.io/badge/React-18-61dafb?style=flat-square&logo=react)
![License: MIT](https://img.shields.io/badge/License-MIT-yellow?style=flat-square)
![Deployed on Vercel](https://img.shields.io/badge/Frontend-Vercel-black?style=flat-square&logo=vercel)
![Workers on Railway](https://img.shields.io/badge/Workers-Railway-purple?style=flat-square)

---

## Why This is Different

| Feature | Zapier | ChatGPT | **This Platform** |
|---|---|---|---|
| Workflow type | Static templates | Sequential, single model | Dynamic DAG, multi-agent parallel |
| AI reasoning | None | Basic | Specialized per agent |
| Parallel execution | No | No | Yes — independent workers |
| Memory | No | Session only | Short-term + long-term semantic |
| Failure recovery | Manual | None | Automatic retry, fallback, DLQ |
| Output | Single action | Text | Unified report — research + content + email + analytics |

---

## Live Demo

> **URL:** https://autoagent-platform.vercel.app
> **Demo email:** `demo@autoagent.ai`
> **Demo password:** `Demo1234`

---

## Architecture

```
User Browser (Vercel)
        │  HTTPS REST + SSE
        ▼
FastAPI API Server (Render)
        │
        ├── Outbox Poller (writes to PostgreSQL, publishes to Redis)
        │
Redis Task Queue (Railway)
        │
        ├──► Planner Worker    ──► Creates DAG
        ├──► Research Worker   ──► Tavily / DuckDuckGo → ChromaDB
        ├──► Content Worker    ──► Gemini → ChromaDB
        ├──► Email Worker      ──► Gemini → Resend / EmailJS
        ├──► Analytics Worker  ──► Scoring → Gemini recommendations
        └──► Aggregator Worker ──► DAG resolution → Final output → SSE

Data Layer:
  PostgreSQL (Neon)  ──  All relational data, DAG state, outbox
  Redis (Railway)    ──  Queue, locks, session memory, SSE events
  ChromaDB (Railway) ──  Vector storage, RAG, long-term memory
```

---

## Phase Plan

| Phase | Status | Description |
|---|---|---|
| **Phase 1 — MVP** | ✅ Current | Single Railway project, shared codebase, free tiers, validates product-market fit |
| **Phase 2 — Scale** | Planned at 285+ tasks/day | Railway paid workers, Gemini paid API, horizontal scaling, centralized logging, Slack triggers |

---

## Workers

| Worker | Single Responsibility | Primary Tool | Fallback |
|---|---|---|---|
| Planner | DAG creation and initial dispatch | Gemini 1.5 Flash | Mark task FAILED with user message |
| Research | Information gathering and ChromaDB storage | Tavily API | DuckDuckGo → ChromaDB cache |
| Content | Business content generation with validation | Gemini 1.5 Flash | Retry with refined prompt |
| Email | Email generation and delivery | Resend API | EmailJS → store as UNSENT |
| Analytics | Deterministic scoring + AI recommendations | Python scoring + Gemini | Default recommendation set |
| Aggregator | Dependency resolution, output assembly | DAG state + ChromaDB | Gemini fallback content per failed section |

---

## Tech Stack

### Frontend
| Technology | Purpose |
|---|---|
| React 18 | UI framework |
| Vite | Build tool |
| TailwindCSS | Styling |
| Framer Motion | Animations |
| EventSource API | SSE real-time updates |

### Backend & Workers
| Technology | Purpose |
|---|---|
| FastAPI | REST API + SSE streaming |
| Python 3.11 | All workers |
| asyncpg | Async PostgreSQL |
| redis-py async | Queue, locks, session memory |
| APScheduler | Scheduled tasks |
| slowapi | Rate limiting |
| structlog | Structured JSON logging |
| bleach | Input sanitization |

### AI & ML
| Technology | Purpose |
|---|---|
| Gemini 1.5 Flash | Primary LLM — 15 RPM, 1M tokens/day free |
| sentence-transformers all-MiniLM-L6-v2 | Embeddings — 90MB, CPU, no cost |
| LangChain | Document chunking and RAG pipeline |
| Tavily | Web search — 1,000/month free |
| DuckDuckGo | Search fallback — free |

### Databases
| Technology | Purpose | Free Tier |
|---|---|---|
| PostgreSQL (Neon) | Source of truth — tasks, DAG, users | 512MB |
| Redis (Railway) | Queue, locks, session memory, SSE | 512MB |
| ChromaDB (Railway) | Vector storage for RAG + memory | 512MB RAM |

---

## Quick Start

```bash
# 1. Clone the repository
git clone https://github.com/yourname/multi-agent-platform.git
cd multi-agent-platform

# 2. Set up backend environment
cd backend
cp .env.example .env
# Fill in environment variables (see table below)

# 3. Start API server locally (databases connect to cloud)
docker-compose up

# 4. Set up frontend
cd ../frontend
npm install
cp .env.example .env.local
# Set VITE_API_URL=http://localhost:8000

# 5. Start frontend
npm run dev

# 6. Open http://localhost:3000
```

---

## Environment Variables

| Variable | Description | Where to Obtain | Required |
|---|---|---|---|
| `GEMINI_API_KEY` | Google Gemini API key | [Google AI Studio](https://aistudio.google.com/) | ✅ |
| `TAVILY_API_KEY` | Tavily web search API | [Tavily](https://tavily.com/) | Optional |
| `RESEND_API_KEY` | Email delivery API | [Resend](https://resend.com/) | Optional |
| `DATABASE_URL` | PostgreSQL connection (asyncpg) | [Neon](https://neon.tech/) | ✅ |
| `REDIS_URL` | Redis connection URL | [Railway](https://railway.app/) | ✅ |
| `CHROMA_URL` | ChromaDB HTTP server URL | Railway Docker service | ✅ |
| `JWT_SECRET_KEY` | JWT signing secret | `openssl rand -hex 32` | ✅ |
| `ENVIRONMENT` | `development` or `production` | Set manually | ✅ |
| `ALLOWED_ORIGIN` | CORS allowed origin | Your Vercel URL | ✅ |
| `EMAILJS_SERVICE_ID` | EmailJS service ID | [EmailJS](https://emailjs.com/) | Optional |
| `EMAILJS_TEMPLATE_ID` | EmailJS template ID | EmailJS dashboard | Optional |
| `EMAILJS_PUBLIC_KEY` | EmailJS public key | EmailJS dashboard | Optional |

---

## API Endpoints

| Method | Route | Auth | Description |
|---|---|---|---|
| POST | `/api/v1/auth/register` | No | Register new user |
| POST | `/api/v1/auth/login` | No | Login, get JWT tokens |
| POST | `/api/v1/auth/refresh` | No | Refresh access token |
| POST | `/api/v1/auth/logout` | Yes | Revoke refresh token |
| GET | `/api/v1/auth/me` | Yes | Get current user |
| POST | `/api/v1/tasks` | Yes | Submit automation task |
| GET | `/api/v1/tasks` | Yes | List user's tasks |
| GET | `/api/v1/tasks/{id}` | Yes | Get task details + output |
| GET | `/api/v1/tasks/{id}/dag` | Yes | Get DAG execution graph |
| GET | `/api/v1/tasks/scheduled` | Yes | List scheduled tasks |
| POST | `/api/v1/tasks/scheduled` | Yes | Create scheduled task |
| DELETE | `/api/v1/tasks/scheduled/{id}` | Yes | Cancel scheduled task |
| GET | `/api/v1/stream/{task_id}?token=JWT` | JWT query | SSE real-time stream |
| POST | `/api/v1/documents` | Yes | Upload PDF/DOCX/TXT |
| GET | `/api/v1/documents` | Yes | List uploaded documents |
| POST | `/api/v1/documents/query` | Yes | RAG question answering |
| DELETE | `/api/v1/documents/{id}` | Yes | Delete document |
| GET | `/api/v1/admin/stats` | Admin | Platform analytics |
| GET | `/api/v1/admin/dlq` | Admin | Dead Letter Queue items |
| POST | `/api/v1/admin/dlq/requeue` | Admin | Re-queue DLQ item |
| GET | `/api/v1/admin/users` | Admin | List all users |
| PATCH | `/api/v1/admin/users/{id}/role` | Admin | Change user role |
| PATCH | `/api/v1/admin/users/{id}/status` | Admin | Activate/deactivate user |
| POST | `/api/v1/admin/retention/trigger` | Admin | Run data retention now |
| GET | `/api/v1/health` | No | Service health check |

---

## Testing

```bash
# Run all unit tests with coverage
cd backend
pytest tests/unit/ --cov=. --cov-report=term-missing -v

# Run integration tests (requires live Redis + PostgreSQL)
pytest tests/integration/ -v -m integration

# Run load test (requires running server)
locust -f tests/load/locustfile.py --host=http://localhost:8000 --users=10 --spawn-rate=2

# Expected output (unit tests)
# PASSED tests/unit/test_injection_filter.py::test_check_injection_safe_inputs
# PASSED tests/unit/test_analytics_worker.py::test_compute_scores_high_quality
# PASSED tests/unit/test_dag.py::test_create_dag_atomically_creates_nodes
# ...
# Coverage: 75%+
```

---

## Deployment

### Railway Workers
Each worker deploys as a separate Railway service in the same project.

```bash
# Start command per worker
python -m workers.planner_worker
python -m workers.research_worker
python -m workers.content_worker
python -m workers.email_worker
python -m workers.analytics_worker
python -m workers.aggregator_worker
```

### ChromaDB on Railway
Deploy using the official Docker image: `chromadb/chroma`
- Port: 8000
- No additional configuration needed

### Render (API Server)
- Connect GitHub repo
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn main:app -w 2 -k uvicorn.workers.UvicornWorker --bind 0.0.0.0:$PORT`
- Set all environment variables in Render dashboard

### Vercel (Frontend)
- Connect `frontend/` directory
- Framework: Vite
- Set `VITE_API_URL` to your Render URL

---

## Key Design Decisions

**Outbox Pattern** — Task submission writes task + outbox record in one atomic PostgreSQL transaction. If Redis is down at submission time, the outbox poller publishes when it recovers. Zero task loss.

**Serializable Transaction for DAG** — Dependency resolution runs in a SERIALIZABLE PostgreSQL transaction to prevent race conditions when two leaf nodes complete simultaneously.

**BRPOPLPUSH** — Workers use BRPOPLPUSH instead of BRPOP. If a worker crashes mid-task, the message stays in the backup list and is drained on restart.

**ChromaDB Upsert Idempotency** — Every ChromaDB write uses a deterministic document ID. Worker crash-and-retry produces identical write with no duplicates.

**SSE over WebSocket** — Unidirectional server-to-client perfectly matches this use case. Works over standard HTTP without special proxy config. Native browser EventSource needs no library.

**Embedding model on CPU** — sentence-transformers all-MiniLM-L6-v2 runs on CPU with 150-200MB RAM, no API cost, no rate limits. Replaceable with an embedding API in Phase 2.

---

## License

MIT © 2024 — see [LICENSE](LICENSE) for details.
#   M A P  
 #   M A P  
 #   m A p M L  
 