import asyncio
from sqlalchemy import text
from models.database import AsyncSessionLocal

async def test():
    async with AsyncSessionLocal() as db:
        # Check tasks
        result = await db.execute(text("SELECT id, status FROM tasks ORDER BY created_at DESC LIMIT 1"))
        task = result.first()
        if task:
            print(f"Latest Task: {task[0]} - Status: {task[1]}")
        else:
            print("No tasks found")
        
        # Check outbox
        result = await db.execute(text("SELECT COUNT(*) FROM outbox"))
        print(f"Outbox records: {result.scalar()}")

asyncio.run(test())
