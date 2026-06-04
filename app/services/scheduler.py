"""
定时匹配调度器

每小时自动扫描所有 pending 事件，逐个运行匹配 pipeline。
基于 asyncio 实现，不引入额外依赖。
"""
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta

logger = logging.getLogger(__name__)


def next_hourly_run_at(now: datetime) -> datetime:
    next_run = now.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)
    return next_run


class MatchScheduler:
    def __init__(self):
        self._task: asyncio.Task | None = None
        self._run_lock = asyncio.Lock()

    def start(self):
        """在 app startup 时调用"""
        self._task = asyncio.create_task(self._run_loop())
        logger.info("Match scheduler started, hourly")

    async def stop(self):
        """在 app shutdown 时调用"""
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("Match scheduler stopped")

    async def _run_loop(self):
        """每小时运行一次匹配"""
        while True:
            now = datetime.now().astimezone()
            target = next_hourly_run_at(now)
            wait_seconds = (target - now).total_seconds()
            logger.info(f"Next match run at {target.isoformat()}, waiting {wait_seconds:.0f}s")

            await asyncio.sleep(wait_seconds)
            await self._run_matching()

    async def _run_matching(self):
        """扫描所有 pending 事件并逐个匹配"""
        from app.core.database import async_session
        from app.services.matching_service import matching_service
        from app.models.event import Event
        from sqlalchemy import select

        if self._run_lock.locked():
            logger.info("Scheduled matching run skipped because a previous run is still active")
            return

        async with self._run_lock:
            logger.info("Starting scheduled matching run...")
            matched_count = 0
            error_count = 0

            try:
                async with async_session() as db:
                    # 查找所有 pending 事件
                    result = await db.execute(
                        select(Event).where(Event.status == "pending")
                    )
                    pending_events = result.scalars().all()
                    logger.info(f"Found {len(pending_events)} pending events")

                # 逐个匹配（每个用独立 session）
                for event in pending_events:
                    try:
                        async with async_session() as db:
                            # 重新加载确认还是 pending
                            fresh = await db.execute(
                                select(Event).where(
                                    Event.id == event.id,
                                    Event.status == "pending",
                                )
                            )
                            if not fresh.scalar_one_or_none():
                                continue

                            result = await matching_service.match_event(event.id, db)
                            await db.commit()
                            if result:
                                matched_count += 1
                                logger.info(f"Matched event {event.id}: {event.title}")
                    except Exception as e:
                        error_count += 1
                        logger.error(f"Failed to match event {event.id}: {e}")

                logger.info(
                    f"Scheduled matching complete: {matched_count} matched, {error_count} errors"
                )

                # 被动匹配：对多轮失败的事件尝试从用户池中找人
                try:
                    from app.services.passive_matching_service import passive_matching_service
                    async with async_session() as db:
                        passive_count = await passive_matching_service.run_passive_matching(db)
                        logger.info(f"Passive matching complete: {passive_count} matched")
                except Exception as e:
                    logger.error(f"Passive matching failed: {e}")

            except Exception as e:
                logger.error(f"Scheduled matching run failed: {e}")


match_scheduler = MatchScheduler()
