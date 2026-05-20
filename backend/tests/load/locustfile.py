"""
Load test for Multi-Agent Platform.
Run with: locust -f locustfile.py --host=https://your-render-url.com

Scenario: 10 concurrent users, 1 task/minute each, 10 minutes.
Success criteria:
- 95th percentile completion < 90 seconds
- Zero unhandled 500 errors
- All tasks reach COMPLETED or FALLBACK within 10 minutes
"""
import json
import random
from locust import HttpUser, task, between, events

TEST_EMAIL = f"loadtest_{random.randint(1000,9999)}@example.com"
TEST_PASSWORD = "LoadTest123"

SAMPLE_INSTRUCTIONS = [
    "Create a marketing strategy for a coffee shop in downtown Manhattan",
    "Write a business proposal for a SaaS product targeting HR departments",
    "Generate a competitor analysis for an e-commerce fashion brand",
    "Create a social media content calendar for a fitness gym",
    "Write a sales email campaign for a B2B software company",
    "Develop a customer retention strategy for a subscription service",
    "Create a product launch plan for a mobile app",
    "Generate a market entry strategy for a food delivery startup",
]


class BusinessAutomationUser(HttpUser):
    wait_time = between(55, 65)  # ~1 task per minute per user
    token = None
    submitted_tasks = []

    def on_start(self):
        """Register and login."""
        email = f"loadtest_{random.randint(10000, 99999)}@example.com"

        # Register
        resp = self.client.post("/api/v1/auth/register", json={
            "name": "Load Test User",
            "email": email,
            "password": TEST_PASSWORD,
        })
        if resp.status_code not in (201, 409):
            return

        # Login
        resp = self.client.post("/api/v1/auth/login", json={
            "email": email,
            "password": TEST_PASSWORD,
        })
        if resp.status_code == 200:
            self.token = resp.json()["access_token"]

    def get_headers(self):
        return {"Authorization": f"Bearer {self.token}"}

    @task(10)
    def submit_task(self):
        """Submit a business automation task."""
        if not self.token:
            return

        instruction = random.choice(SAMPLE_INSTRUCTIONS)
        resp = self.client.post(
            "/api/v1/tasks",
            headers=self.get_headers(),
            json={"instruction": instruction},
            name="/api/v1/tasks [POST]",
        )

        if resp.status_code == 202:
            task_id = resp.json().get("id")
            if task_id:
                self.submitted_tasks.append(task_id)

    @task(5)
    def check_task_status(self):
        """Check status of previously submitted tasks."""
        if not self.token or not self.submitted_tasks:
            return

        task_id = random.choice(self.submitted_tasks)
        self.client.get(
            f"/api/v1/tasks/{task_id}",
            headers=self.get_headers(),
            name="/api/v1/tasks/[id] [GET]",
        )

    @task(3)
    def list_tasks(self):
        """List user's tasks."""
        if not self.token:
            return

        self.client.get(
            "/api/v1/tasks?limit=10",
            headers=self.get_headers(),
            name="/api/v1/tasks [GET]",
        )

    @task(1)
    def health_check(self):
        """Platform health check."""
        self.client.get("/api/v1/health", name="/api/v1/health [GET]")


@events.test_stop.add_listener
def on_test_stop(environment, **kwargs):
    """Print summary statistics at end of test."""
    stats = environment.stats
    print("\n=== Load Test Summary ===")
    print(f"Total requests: {stats.total.num_requests}")
    print(f"Failures: {stats.total.num_failures}")
    print(f"Failure rate: {stats.total.fail_ratio:.2%}")
    print(f"Median response: {stats.total.median_response_time}ms")
    print(f"95th percentile: {stats.total.get_response_time_percentile(0.95)}ms")
    print(f"Requests/sec: {stats.total.current_rps:.2f}")
