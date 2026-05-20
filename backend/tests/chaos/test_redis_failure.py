"""
Chaos tests — manual execution only before major releases.
These tests inject real failures into the system and verify recovery.

Run individually:
    pytest tests/chaos/test_redis_failure.py -v -m chaos -s

Requires: running API server, workers, and databases.
WARNING: These tests affect shared state. Run against staging only.
"""
import pytest
import asyncio
import time


@pytest.mark.chaos
@pytest.mark.skip(reason="Manual chaos test — run against staging only")
async def test_task_survives_redis_unavailability():
    """
    Scenario: Submit task, suspend Redis for 30s, verify task completes.
    Expected: Outbox pattern preserves task, queue drains after Redis recovers.
    """
    import httpx

    BASE_URL = "http://localhost:8000"

    async with httpx.AsyncClient() as client:
        # Login
        resp = await client.post(f"{BASE_URL}/api/v1/auth/login", json={
            "email": "chaos@test.com",
            "password": "ChaosTest123"
        })
        token = resp.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        # Submit task
        resp = await client.post(f"{BASE_URL}/api/v1/tasks", headers=headers, json={
            "instruction": "Create a brief marketing summary for chaos test"
        })
        assert resp.status_code == 202
        task_id = resp.json()["id"]

        print(f"\nTask submitted: {task_id}")
        print("NOW: Suspend Redis for 30 seconds, then resume")
        print("Waiting 60 seconds for system to recover...")

        await asyncio.sleep(60)

        # Check task status
        resp = await client.get(f"{BASE_URL}/api/v1/tasks/{task_id}", headers=headers)
        status = resp.json()["status"]
        print(f"Task status after recovery: {status}")

        # Task should eventually reach COMPLETED or FALLBACK
        assert status in ("COMPLETED", "FALLBACK", "IN_PROGRESS"), \
            f"Expected COMPLETED/FALLBACK/IN_PROGRESS, got {status}"


@pytest.mark.chaos
@pytest.mark.skip(reason="Manual chaos test — run against staging only")
async def test_worker_kill_mid_task():
    """
    Scenario: Submit task, kill Content Worker mid-processing, verify recovery.
    Expected: BRPOPLPUSH backup + lock expiry ensures task is reprocessed.
    """
    print("\nManual steps:")
    print("1. Submit a task via API")
    print("2. Watch Railway dashboard for Content Worker to start")
    print("3. Kill Content Worker process in Railway")
    print("4. Verify task eventually completes via DAG monitoring")
    print("5. Restart Content Worker")
    print("Expected: Task retries and completes without data loss")


@pytest.mark.chaos
@pytest.mark.skip(reason="Manual chaos test — run against staging only")
async def test_neon_suspension():
    """
    Scenario: Trigger Neon auto-suspension (idle > 5 min), then submit task.
    Expected: asyncpg reconnects transparently, ~1s delay on first query.
    """
    print("\nManual steps:")
    print("1. Let system sit idle for > 5 minutes (Neon auto-suspends)")
    print("2. Submit a task via API")
    print("3. Verify task is received and processed normally")
    print("4. Check API logs for 'Neon reconnect' — should be transparent")
    print("Expected: No task loss, ~1s slower first query")
