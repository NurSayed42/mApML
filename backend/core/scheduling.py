from datetime import datetime, timezone
from typing import Optional

from apscheduler.triggers.cron import CronTrigger


def cron_task_is_due(
    cron_expression: str,
    now: datetime,
    last_run_at: Optional[datetime] = None,
) -> bool:
    """Return True if a cron-scheduled task should run at `now` (UTC)."""
    trigger = CronTrigger.from_crontab(cron_expression.strip(), timezone="UTC")
    previous = last_run_at
    if previous is not None and previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    next_fire = trigger.get_next_fire_time(previous, now)
    return next_fire is not None and next_fire <= now
