# Architecture Deep Dive

## Outbox Pattern Flow

```
User Submit Request
        │
        ▼
API Server (FastAPI)
        │
        ▼ Single PostgreSQL Transaction
┌───────────────────────┐
│  INSERT task record   │
│  INSERT outbox record │
└───────────────────────┘
        │ Commit
        ▼
Return task_id to user (immediate, no Redis dependency)
        │
        ▼ (2 second poll interval)
Outbox Poller
        │
        ├── SELECT unpublished outbox records
        ├── RPUSH to Redis channel
        └── UPDATE is_published = true
                │
                ▼
Planner Worker picks up from Redis and begins DAG creation
```

## DAG Execution Model

```
Planner creates DAG atomically:
  dag_nodes: [research, content, email, analytics, aggregator]
  task_dependencies:
    content → depends on → research
    email   → depends on → content
    analytics → depends on → research, content
    aggregator → depends on → research, content, email, analytics

Root nodes (no dependencies): [research]
Planner queues root nodes to Redis immediately.

Aggregator monitors task_results channel:
  research COMPLETED → unblocks: content, analytics (partial)
  content COMPLETED  → unblocks: email, analytics (now fully unblocked)
  analytics COMPLETED → aggregator checks: all leaf nodes done?
  email COMPLETED → aggregator checks: all leaf nodes done?
  All done → assemble final output → SSE task_completed
```

## Worker Crash Recovery

```
Normal flow:
  BRPOPLPUSH source_queue → backup_list   (atomic)
  Process task
  Remove from backup_list

Worker crashes during processing:
  Message stays in backup_list
  Worker restarts
  Drain backup_list → re-queue to source_queue
  Task is reprocessed from QUEUED state
  Redis lock has 90s TTL — auto-expires if worker crashed holding it
```

## Three-Level Failure Handling

```
Attempt 1: Process task
  ├── Success → COMPLETED
  └── Failure → retry_count=1, retry_after=now+30s, re-queue

Attempt 2 (after 30s): Process task
  ├── Success → COMPLETED
  └── Failure → retry_count=2, retry_after=now+90s, re-queue

Attempt 3 (after 90s): Process task
  ├── Success → COMPLETED
  └── Failure → Move to DLQ
                ├── Redis DLQ (expires 72h)
                ├── PostgreSQL agent_errors (permanent)
                └── Notify Aggregator → generate fallback content
```

## Memory Architecture

```
Short-term (Redis, per session):
  session:{session_id}:messages → List of {message, response} pairs
  Max 10 pairs (LTRIM), 2h TTL
  Included as Gemini messages array in every API call

Long-term (ChromaDB, permanent):
  Collection: long_term_memory
  After task completion: embed (request + response summary) → upsert
  Metadata: user_id, task_id, task_type, created_at
  On new request: embed query → search by user_id + similarity ≥ 0.75
  Top 3 results prepended to Planner system prompt
  Retention: deleted after 180 days
```

## Token Usage Tracking

```
Every Gemini API call → log_token_usage()
        │
        ▼
Redis buffer (TOKEN_BUFFER_KEY list)
        │
        ├── Count ≥ 10 → flush immediately
        └── Every 30s → periodic_flush()
                │
                ▼
        Batch INSERT to token_usage table
        (reduces DB writes by up to 10x)
```

## Rate Limiting Strategy

```
Login: 5 attempts per IP per minute (slowapi + Redis backend)
  → 429 with Retry-After header

Task creation: 20 per user per hour
  → 429

Gemini RPM: Redis counter (60s window)
  → At 13/15 RPM: queue new calls with 1s delay
  → Gemini 429 response: respect Retry-After header, wait 60s

Tavily monthly: Redis counter
  → At 900: switch to DuckDuckGo automatically

Resend daily: Redis counter
  → At 100: switch to EmailJS automatically
```

## Database Schema Relationships

```
users ──< tasks ──< dag_nodes ──< task_dependencies
                │              └──< agent_logs
                │              └──< token_usage
                │              └──< email_records
                └──< outbox
                └──< scheduled_tasks
                └──< conversations

agent_errors (standalone, references dag_node optionally)
data_retention_log (audit log for cleanup runs)
documents (uploaded files, chunks stored in ChromaDB)
```

## SSE Event Schema (v1)

All events include these base fields:
```json
{
  "event_type": "...",
  "event_schema_version": "v1",
  "task_id": "uuid",
  "correlation_id": "uuid",
  "timestamp": "ISO8601",
  "data": { ... }
}
```

Event types and their data fields:
- `task_received` → `{status}`
- `planning_complete` → `{subtask_count, agent_list, title}`
- `agent_started` → `{agent_name, task_type, description}`
- `agent_completed` → `{agent_name, output_summary, duration_ms}`
- `fallback_activated` → `{agent_name, reason, user_message}`
- `task_completed` → `{final_output}` (full structured output)
- `task_failed` → `{message}` (user-readable error)

## Security Layers

```
1. Input layer:   bleach.clean() strips HTML → regex injection blocklist
2. Auth layer:    JWT HS256, 30min access + 7day refresh, Redis blacklist on logout
3. Route layer:   Depends(get_current_user) on all protected routes
4. Role layer:    Depends(require_admin) on all admin routes
5. CORS layer:    Only Vercel frontend URL allowed in production
6. Rate layer:    slowapi Redis backend — login 5/min, tasks 20/hr per user
7. SQL layer:     asyncpg parameterized queries — no string interpolation ever
8. Output layer:  All agent output stored as data, rendered as text only
9. SSE auth:      JWT as query param validated same as headers
```

## Free Tier Capacity Estimates

| Resource | Free Limit | Per Task Usage | Estimated Daily Capacity |
|---|---|---|---|
| Gemini tokens | 1M/day | ~3,500 tokens | ~285 tasks |
| Gemini RPM | 15/min | ~7 calls | ~13 parallel tasks |
| Tavily searches | 1,000/month | 2 searches | ~500 tasks (then DuckDuckGo) |
| Resend emails | 100/day | 1 email | 100 emails (then EmailJS) |
| Neon PostgreSQL | 512MB | ~15KB/task | ~34,000 tasks (retention extends this) |
| Railway Redis | 512MB | ~7KB/task active | hundreds queued, thousands sessions |
| Railway ChromaDB | 512MB RAM | ~3 vectors/task | ~300K vectors (retention manages) |
| Railway worker hours | 500/month | 6 workers × 24h × 30d = 4,320h | Exceeds free — workers block on empty queue, light use stays within |
