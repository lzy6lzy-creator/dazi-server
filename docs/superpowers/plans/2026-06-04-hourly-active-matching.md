# Hourly Active Matching Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace daily matching with immediate-plus-hourly active matching, gate A2A by vector score `0.55`, and never re-evaluate A2A-failed event pairs automatically.

**Architecture:** Keep `MatchingService.match_event()` as the single matching pipeline. Add a small service-level background task helper used by both direct event creation and agent-created events. Convert `MatchScheduler` to an hourly pending-event scanner with a run lock and a pure next-run helper for tests.

**Tech Stack:** Python 3.11, FastAPI background tasks, SQLAlchemy async sessions, pgvector, unittest/pytest.

---

### Task 1: Update Pure Matching Policy

**Files:**
- Modify: `app/services/matching_policy.py`
- Modify: `tests/test_matching_policy.py`

- [ ] **Step 1: Write failing tests**

```python
def test_candidate_windows_return_only_top_three_above_threshold(self):
    ids = [uuid4() for _ in range(5)]
    candidates = [
        Candidate(event_id=ids[0], vector_score=0.91),
        Candidate(event_id=ids[1], vector_score=0.60),
        Candidate(event_id=ids[2], vector_score=0.55),
        Candidate(event_id=ids[3], vector_score=0.54),
        Candidate(event_id=ids[4], vector_score=0.80),
    ]

    windows = build_candidate_windows(candidates, blocked_event_ids=set())

    self.assertEqual([[c.event_id for c in w] for w in windows], [[ids[0], ids[1], ids[2]]])

def test_default_vector_threshold_is_fifty_five(self):
    self.assertEqual(VECTOR_MATCH_THRESHOLD, 0.55)
```

- [ ] **Step 2: Run tests and verify failure**

Run: `python -m pytest tests/test_matching_policy.py -q`

Expected: FAIL because the default threshold is still `0.5` and the default candidate windows still allow two rounds.

- [ ] **Step 3: Implement policy change**

```python
VECTOR_MATCH_THRESHOLD = 0.55
A2A_WINDOW_SIZE = 3
MAX_A2A_ROUNDS = 1
```

Update existing tests that asserted two A2A windows so they now assert one Top3 window.

- [ ] **Step 4: Verify policy tests pass**

Run: `python -m pytest tests/test_matching_policy.py -q`

Expected: PASS.

### Task 2: Blocklist A2A-Failed Pairs

**Files:**
- Modify: `app/services/matching_service.py`
- Modify: `tests/test_matching_policy.py`

- [ ] **Step 1: Add pure policy test for event-pair blocklist collection**

```python
def test_collect_blocked_event_ids_skips_a2a_rejected_event_pair(self):
    source_event_id = uuid4()
    source_user_id = uuid4()
    candidate_event_id = uuid4()
    candidate_user_id = uuid4()

    blocked = collect_blocked_event_ids(
        source_event_id=source_event_id,
        source_user_id=source_user_id,
        candidate_events_by_user={candidate_user_id: [candidate_event_id]},
        blocklist_rows=[
            BlocklistRow(
                event_a_id=source_event_id,
                event_b_id=candidate_event_id,
                user_a_id=source_user_id,
                user_b_id=candidate_user_id,
            )
        ],
    )

    self.assertEqual(blocked, {candidate_event_id})
```

- [ ] **Step 2: Run test and verify current behavior**

Run: `python -m pytest tests/test_matching_policy.py::MatchingPolicyTests::test_collect_blocked_event_ids_skips_a2a_rejected_event_pair -q`

Expected: PASS, confirming the existing collector already supports event-pair blocklists.

- [ ] **Step 3: Implement service blocklist writing**

In `matching_service.py`, import `add_match_blocklist` and add a private helper:

```python
async def _blocklist_evaluated_pairs(self, event: Event, evaluations: list[A2AEvaluation], db: AsyncSession) -> None:
    for evaluation in evaluations:
        candidate = await db.get(Event, evaluation.candidate_event_id)
        if candidate is None:
            continue
        await add_match_blocklist(
            db,
            user_a_id=event.user_id,
            user_b_id=candidate.user_id,
            event_a_id=event.id,
            event_b_id=candidate.id,
            reason="a2a_rejected",
        )
```

Call it only after A2A evaluated candidates and no final match was committed.

- [ ] **Step 4: Verify matching policy tests still pass**

Run: `python -m pytest tests/test_matching_policy.py -q`

Expected: PASS.

### Task 3: Add Shared Immediate Matching Task Helper

**Files:**
- Create: `app/services/matching_tasks.py`
- Modify: `app/api/events.py`
- Modify: `app/api/agent_chat.py`
- Create: `tests/test_matching_tasks_static.py`

- [ ] **Step 1: Write static tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_direct_event_creation_schedules_immediate_matching():
    text = (ROOT / "app" / "api" / "events.py").read_text(encoding="utf-8")
    assert "schedule_event_matching(background_tasks, event.id)" in text

def test_agent_event_creation_schedules_immediate_matching():
    text = (ROOT / "app" / "api" / "agent_chat.py").read_text(encoding="utf-8")
    assert "schedule_event_matching(background_tasks, event_id)" in text

def test_matching_task_uses_fresh_session():
    text = (ROOT / "app" / "services" / "matching_tasks.py").read_text(encoding="utf-8")
    assert "async with async_session() as db" in text
    assert "matching_service.match_event(event_id, db)" in text
```

- [ ] **Step 2: Run static tests and verify failure**

Run: `python -m pytest tests/test_matching_tasks_static.py -q`

Expected: FAIL because `matching_tasks.py` does not exist and neither creation path schedules immediate matching.

- [ ] **Step 3: Implement helper and call sites**

Create `matching_tasks.py` with:

```python
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
```

Update direct event creation to accept optional `BackgroundTasks` and call `schedule_event_matching(background_tasks, event.id)` after embedding assignment.

Update agent chat creation flow to call `schedule_event_matching(background_tasks, event_id)` only when a new event was created, not when an existing event was edited.

- [ ] **Step 4: Verify static tests pass**

Run: `python -m pytest tests/test_matching_tasks_static.py -q`

Expected: PASS.

### Task 4: Convert Scheduler to Hourly

**Files:**
- Modify: `app/services/scheduler.py`
- Create: `tests/test_scheduler.py`

- [ ] **Step 1: Write scheduler tests**

```python
from datetime import datetime, timezone

from app.services.scheduler import next_hourly_run_at

def test_next_hourly_run_at_rounds_to_next_hour():
    now = datetime(2026, 6, 4, 14, 15, 30, tzinfo=timezone.utc)
    assert next_hourly_run_at(now) == datetime(2026, 6, 4, 15, 0, 0, tzinfo=timezone.utc)

def test_next_hourly_run_at_moves_forward_from_exact_hour():
    now = datetime(2026, 6, 4, 14, 0, 0, tzinfo=timezone.utc)
    assert next_hourly_run_at(now) == datetime(2026, 6, 4, 15, 0, 0, tzinfo=timezone.utc)
```

- [ ] **Step 2: Run scheduler tests and verify failure**

Run: `python -m pytest tests/test_scheduler.py -q`

Expected: FAIL because `next_hourly_run_at` does not exist.

- [ ] **Step 3: Implement hourly scheduler**

Add `next_hourly_run_at(now)` and update `_run_loop()` to sleep until that timestamp. Add an `asyncio.Lock` in `MatchScheduler.__init__` and use it in `_run_matching()` to avoid overlapping scans.

- [ ] **Step 4: Verify scheduler tests pass**

Run: `python -m pytest tests/test_scheduler.py -q`

Expected: PASS.

### Task 5: Admin Reset Clears Related Blocklists

**Files:**
- Modify: `app/api/admin.py`
- Create: `tests/test_admin_reset_static.py`

- [ ] **Step 1: Write static reset tests**

```python
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def test_single_event_reset_clears_match_blocklists():
    text = (ROOT / "app" / "api" / "admin.py").read_text(encoding="utf-8")
    assert "delete(MatchBlocklist)" in text
    assert "MatchBlocklist.event_a_id == event_id" in text
    assert "MatchBlocklist.event_b_id == event_id" in text

def test_reset_all_clears_match_blocklists():
    text = (ROOT / "app" / "api" / "admin.py").read_text(encoding="utf-8")
    assert "await db.execute(delete(MatchBlocklist))" in text
```

- [ ] **Step 2: Run reset tests and verify failure**

Run: `python -m pytest tests/test_admin_reset_static.py -q`

Expected: FAIL because reset endpoints do not delete blocklists yet.

- [ ] **Step 3: Implement reset cleanup**

Import `delete` from SQLAlchemy and delete related `MatchBlocklist` rows in single reset. Delete all `MatchBlocklist` rows in reset-all.

- [ ] **Step 4: Verify reset tests pass**

Run: `python -m pytest tests/test_admin_reset_static.py -q`

Expected: PASS.

### Task 6: Final Verification

**Files:**
- Verify all modified files and focused tests.

- [ ] **Step 1: Run focused tests**

Run:

```bash
python -m pytest \
  tests/test_matching_policy.py \
  tests/test_matching_tasks_static.py \
  tests/test_scheduler.py \
  tests/test_admin_reset_static.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run existing related tests**

Run:

```bash
python -m pytest \
  tests/test_event_location_passthrough.py \
  tests/test_a2a_matcher.py \
  tests/test_admin_console_static.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Review diff**

Run: `git diff -- app/services/matching_policy.py app/services/matching_service.py app/services/scheduler.py app/services/matching_tasks.py app/api/events.py app/api/agent_chat.py app/api/admin.py tests/test_matching_policy.py tests/test_matching_tasks_static.py tests/test_scheduler.py tests/test_admin_reset_static.py`

Expected: Diff only contains hourly active matching changes.
