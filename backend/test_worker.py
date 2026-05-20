import asyncio
import redis.asyncio as redis
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

async def main():
    logger.info("Test worker starting...")
    
    # Redis connect
    r = await redis.from_url('redis://localhost:6379', decode_responses=True)
    await r.ping()
    logger.info("Connected to Redis")
    
    # Subscribe to planner_tasks
    while True:
        task = await r.lpop('planner_tasks')
        if task:
            logger.info(f"Received task: {task}")
        else:
            logger.debug("No tasks, waiting...")
            await asyncio.sleep(2)

if __name__ == "__main__":
    asyncio.run(main())
