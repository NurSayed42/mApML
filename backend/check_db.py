import asyncio
from sqlalchemy import text
from models.database import AsyncSessionLocal

async def check():
    async with AsyncSessionLocal() as db:
        r = await db.execute(text('SELECT COUNT(*) FROM outbox'))
        print('Total outbox:', r.scalar())
        r = await db.execute(text('SELECT COUNT(*) FROM outbox WHERE is_published = false'))
        print('Unpublished:', r.scalar())
        r = await db.execute(text('SELECT id, status FROM tasks ORDER BY created_at DESC LIMIT 3'))
        for row in r.fetchall():
            print('Task:', row)
        r = await db.execute(text('SELECT task_id, is_published, redis_channel FROM outbox ORDER BY created_at DESC LIMIT 3'))
        for row in r.fetchall():
            print('Outbox:', row)

asyncio.run(check())