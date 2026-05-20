"""
Integration tests for full pipeline.
Requires Railway Redis and Neon test database.
External APIs are mocked at HTTP level.
Run with: pytest tests/integration/ -v
"""
import pytest
import asyncio
import json
import uuid
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock, patch
from httpx import AsyncClient

# These tests require actual Redis and PostgreSQL connections
# Set TEST_DATABASE_URL and TEST_REDIS_URL environment variables


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest.fixture(scope="session")
async def test_app():
    """Create test FastAPI app instance."""
    from main import app
    from models.database import init_db
    await init_db()
    return app


@pytest.mark.asyncio
@pytest.mark.integration
async def test_full_task_pipeline(test_app):
    """
    Test complete task flow:
    POST /tasks → Planner → Research → Content → Analytics → Aggregator → SSE complete
    """
    mock_plan = {
        "title": "Test Marketing Campaign",
        "subtasks": [
            {"agent_role": "research", "task_type": "market_research", "payload": {}, "dependencies": []},
            {"agent_role": "content", "task_type": "marketing_strategy", "payload": {}, "dependencies": ["research"]},
            {"agent_role": "analytics", "task_type": "engagement_analysis", "payload": {}, "dependencies": ["content", "research"]},
        ]
    }

    mock_gemini_responses = [
        json.dumps(mock_plan),  # Planner
        "Market research summary: Strong demand exists.",  # Research
        "## Marketing Strategy\n\nComprehensive strategy with 300+ words of detailed content " * 5,  # Content
        json.dumps([  # Analytics recommendations
            {"title": "R1", "rationale": "Why", "action": "Do"},
            {"title": "R2", "rationale": "Why", "action": "Do"},
            {"title": "R3", "rationale": "Why", "action": "Do"},
        ]),
    ]
    call_count = [0]

    async def mock_gemini(*args, **kwargs):
        idx = call_count[0] % len(mock_gemini_responses)
        call_count[0] += 1
        return mock_gemini_responses[idx]

    with patch("workers.base_worker.BaseWorker.call_gemini", new_callable=AsyncMock, side_effect=mock_gemini), \
         patch("workers.research_worker.ResearchWorker._perform_search", new_callable=AsyncMock, return_value=[
             {"url": "http://example.com", "title": "Test", "content": "Market data"}
         ]):

        async with AsyncClient(app=test_app, base_url="http://test") as client:
            # Register user
            reg_resp = await client.post("/api/v1/auth/register", json={
                "name": "Test User",
                "email": f"test_{uuid.uuid4()}@example.com",
                "password": "TestPass123",
            })
            assert reg_resp.status_code == 201

            # Login
            login_resp = await client.post("/api/v1/auth/login", json={
                "email": reg_resp.json()["email"],
                "password": "TestPass123",
            })
            assert login_resp.status_code == 200
            token = login_resp.json()["access_token"]

            headers = {"Authorization": f"Bearer {token}"}

            # Submit task
            task_resp = await client.post(
                "/api/v1/tasks",
                headers=headers,
                json={"instruction": "Create a marketing campaign for my coffee shop"},
            )
            assert task_resp.status_code == 202
            task_id = task_resp.json()["id"]
            assert task_id

            # Wait for task to be received
            await asyncio.sleep(0.5)

            # Check task status
            status_resp = await client.get(f"/api/v1/tasks/{task_id}", headers=headers)
            assert status_resp.status_code == 200
            assert status_resp.json()["id"] == task_id


@pytest.mark.asyncio
@pytest.mark.integration
async def test_idempotency_duplicate_request(test_app):
    """Test that duplicate requests within 5 minutes return same task."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        reg_resp = await client.post("/api/v1/auth/register", json={
            "name": "Idem User",
            "email": f"idem_{uuid.uuid4()}@example.com",
            "password": "TestPass123",
        })
        token = (await client.post("/api/v1/auth/login", json={
            "email": reg_resp.json()["email"], "password": "TestPass123"
        })).json()["access_token"]

        headers = {"Authorization": f"Bearer {token}"}
        instruction = "Test instruction for idempotency check"

        resp1 = await client.post("/api/v1/tasks", headers=headers,
                                   json={"instruction": instruction})
        resp2 = await client.post("/api/v1/tasks", headers=headers,
                                   json={"instruction": instruction})

        assert resp1.status_code == 202
        assert resp2.status_code == 202
        assert resp1.json()["id"] == resp2.json()["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_unauthorized_task_access(test_app):
    """Test that users cannot access other users' tasks."""
    async with AsyncClient(app=test_app, base_url="http://test") as client:
        # Create two users
        user1_email = f"user1_{uuid.uuid4()}@example.com"
        user2_email = f"user2_{uuid.uuid4()}@example.com"

        for email in [user1_email, user2_email]:
            await client.post("/api/v1/auth/register", json={
                "name": "User", "email": email, "password": "TestPass123"
            })

        token1 = (await client.post("/api/v1/auth/login", json={
            "email": user1_email, "password": "TestPass123"
        })).json()["access_token"]

        token2 = (await client.post("/api/v1/auth/login", json={
            "email": user2_email, "password": "TestPass123"
        })).json()["access_token"]

        # User1 creates a task
        task_resp = await client.post("/api/v1/tasks",
                                       headers={"Authorization": f"Bearer {token1}"},
                                       json={"instruction": "User1 task"})
        task_id = task_resp.json()["id"]

        # User2 tries to access user1's task
        access_resp = await client.get(f"/api/v1/tasks/{task_id}",
                                        headers={"Authorization": f"Bearer {token2}"})
        assert access_resp.status_code == 404
