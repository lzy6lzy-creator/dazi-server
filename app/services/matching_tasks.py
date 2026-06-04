from __future__ import annotations

import logging
from uuid import UUID

from fastapi import BackgroundTasks

logger = logging.getLogger(__name__)


def schedule_event_matching(background_tasks: BackgroundTasks | None, event_id: UUID) -> None:
    if background_tasks is None:
        return
    background_tasks.add_task(run_event_matching, event_id)


async def run_event_matching(event_id: UUID) -> None:
    from app.core.database import async_session
    from app.services.matching_service import matching_service

    try:
        async with async_session() as db:
            result = await matching_service.match_event(event_id, db)
            await db.commit()
            if result:
                logger.info(f"Match found for event {event_id}: score={result['score']}")
            else:
                logger.info(f"No match found for event {event_id}")
    except Exception as exc:
        logger.error(f"Matching task failed for {event_id}: {exc}")
