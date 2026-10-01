# Multi-Agent Automation Platform

A platform where specialized AI agents plan and execute multi-step business tasks from a single natural-language instruction. A planner turns the instruction into a dependency graph (DAG); independent workers handle research, content, email and analytics; an aggregator assembles the final result and streams progress to the browser.

---

## Overview

Submitting a task such as *"research competitors in X and draft an outreach email"* triggers the following flow:

1. The API stores the task and an outbox record in a single PostgreSQL transaction.
2. An outbox poller publishes the task to a Redis queue.
3. The **Planner** worker asks the LLM to break the instruction into a DAG of sub-tasks.
4. Specialized workers pick up the nodes whose dependencies are satisfied.
5. The **Aggregator** resolves the DAG and builds the final output.
6. Progress is pushed to the frontend over Server-Sent Events.

Uploaded documents (PDF, DOCX, TXT) are chunked and embedded into ChromaDB, and can be queried through a RAG endpoint.

## Architecture

```
React frontend (Vite)
        │  HTTPS REST + SSE
        ▼
FastAPI API server
        │
        ├── Outbox poller (PostgreSQL → Redis)
        ▼
Redis task queue
        │
        ├──► Planner worker    ──► builds the task DAG
        ├──► Research worker   ──► Tavily / DuckDuckGo → ChromaDB
        ├──► Content worker    ──► LLM → ChromaDB
        ├──► Email worker      ──► LLM → Resend / EmailJS
        ├──► Analytics worker  ──► deterministic scoring + LLM recommendations
        └──► Aggregator worker ──► DAG resolution → final output → SSE

Data layer
  PostgreSQL  – users, tasks, DAG state, outbox
  Redis       – queue, locks, session memory, SSE events
  ChromaDB    – vector storage for RAG and long-term memory
```

A deeper walkthrough of the outbox flow and the DAG execution model is in [ARCHITECTURE.md](ARCHITECTURE.md).

### Workers

| Worker | Responsibility | Fallback behaviour |
|---|---|---|
| Planner | Creates the DAG and dispatches the first nodes | Marks the task as failed with a user-facing message |
| Research | Web research, stores findings in ChromaDB | DuckDuckGo, then ChromaDB cache |
| Content | Business content generation with validation | Retry with a refined prompt |
| Email | Email drafting and delivery | EmailJS, then store as unsent |
| Analytics | Deterministic scoring plus LLM recommendations | Default recommendation set |
| Aggregator | Dependency resolution and output assembly | Per-section fallback content |

### Design decisions

- **Transactional outbox** – the task and its outbox record are written atomically, so a task is not lost if Redis is unavailable at submission time; the poller publishes it once Redis is back.
- **Serializable DAG updates** – dependency resolution runs in a `SERIALIZABLE` transaction so two nodes finishing at the same time cannot both trigger (or both miss) a dependent node.
- **`BRPOPLPUSH` queues** – a message stays in a backup list while it is being processed, so work from a crashed worker can be recovered on restart.
- **Idempotent vector writes** – ChromaDB writes use deterministic document IDs, so retries do not create duplicates.
- **Dead-letter queue** – repeatedly failing jobs are moved to a DLQ that admins can inspect and re-queue.
- **SSE instead of WebSockets** – progress updates are one-directional, and SSE works over plain HTTP with the browser's native `EventSource`.
- **Local embeddings** – `sentence-transformers` (`all-MiniLM-L6-v2`) runs on CPU, avoiding per-call embedding costs.
- **Input safety** – prompt-injection filtering, `bleach` sanitization and `slowapi` rate limiting on the API.

## Tech Stack

| Area | Technology |
|---|---|
| Frontend | React 18, Vite, Tailwind CSS, Framer Motion, EventSource (SSE) |
| API | FastAPI, Pydantic, slowapi, structlog |
| Workers | Python 3.11, asyncio, APScheduler |
| Data | PostgreSQL (asyncpg, SQLAlchemy, Alembic), Redis, ChromaDB |
| AI / LLM | Google Gemini via a multi-provider LLM client, LangChain (chunking / RAG), sentence-transformers |
| Integrations | Tavily, DuckDuckGo, Resend, EmailJS |
| Tooling | Docker Compose, GitHub Actions, pytest, Locust |

## Project Structure

```
backend/
├── api/v1/          # REST + SSE endpoints
├── core/            # DAG, outbox, locks, memory, RAG, LLM client, retention
├── workers/         # planner, research, content, email, analytics, aggregator
├── models/          # database models
├── prompts/         # prompt templates
└── tests/           # unit, integration, chaos and load tests
frontend/            # React + Vite client
.github/workflows/   # CI pipeline
ARCHITECTURE.md      # architecture deep dive
```

## Getting Started

```bash
git clone https://github.com/NurSayed42/mApML.git
cd mApML

# Backend
cp backend/.env.example backend/.env   # fill in the variables below
docker-compose up

# Frontend
cd frontend
npm install
echo "VITE_API_URL=http://localhost:8000" > .env.local
npm run dev
```

Workers run as separate processes:

```bash
python -m workers.planner_worker
python -m workers.research_worker
python -m workers.content_worker
python -m workers.email_worker
python -m workers.analytics_worker
python -m workers.aggregator_worker
```

## Environment Variables

See [`backend/.env.example`](backend/.env.example).

| Variable | Purpose | Required |
|---|---|---|
| `GEMINI_API_KEY` | Primary LLM provider | Yes |
| `GROQ_API_KEY`, `MISTRAL_API_KEY` | Additional LLM providers | Optional |
| `DATABASE_URL` | PostgreSQL connection string | Yes |
| `REDIS_URL` | Redis connection string | Yes |
| `CHROMA_URL` | ChromaDB HTTP server | Yes |
| `JWT_SECRET_KEY` | JWT signing secret (`openssl rand -hex 32`) | Yes |
| `ENVIRONMENT` | `development` or `production` | Yes |
| `ALLOWED_ORIGIN` | CORS origin of the frontend | Yes |
| `TAVILY_API_KEY` | Web search | Optional |
| `RESEND_API_KEY` | Email delivery | Optional |
| `EMAILJS_SERVICE_ID`, `EMAILJS_TEMPLATE_ID`, `EMAILJS_PUBLIC_KEY` | Email fallback | Optional |

## API

| Method | Route | Description |
|---|---|---|
| POST | `/api/v1/auth/register`, `/login`, `/refresh`, `/logout` | Authentication (JWT access + refresh tokens) |
| GET | `/api/v1/auth/me` | Current user |
| POST / GET | `/api/v1/tasks` | Submit / list automation tasks |
| GET | `/api/v1/tasks/{id}` | Task details and output |
| GET | `/api/v1/tasks/{id}/dag` | DAG execution graph |
| GET / POST / DELETE | `/api/v1/tasks/scheduled` | Scheduled tasks |
| GET | `/api/v1/stream/{task_id}` | SSE progress stream |
| POST / GET / DELETE | `/api/v1/documents` | Document upload and management |
| POST | `/api/v1/documents/query` | RAG question answering over uploaded documents |
| GET / POST / PATCH | `/api/v1/admin/...` | Stats, DLQ, user management, data retention |
| GET | `/api/v1/health` | Health check |

## Testing

```bash
cd backend
pytest tests/unit/ --cov=. -v                         # unit tests
pytest tests/integration/ -v -m integration           # requires Redis + PostgreSQL
locust -f tests/load/locustfile.py --host=http://localhost:8000
```

The test suite covers the DAG, outbox, locks, idempotency, injection filter, retention and individual workers, plus a Redis-failure chaos test.

## Future Improvements

- Centralized logging and metrics across workers
- Horizontal scaling of individual worker types
- Additional task triggers (e.g. chat integrations)

## Author

**Nur Sayed** — Lead Engineer at VecoSoft · [GitHub](https://github.com/NurSayed42)
