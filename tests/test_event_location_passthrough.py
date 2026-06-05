from __future__ import annotations

import unittest
from unittest import mock
from unittest.mock import AsyncMock
from uuid import uuid4

from app.api import agent_chat as agent_chat_api
from app.api import events as events_api
from app.api.schemas import EventCreate, EventUpdate
from app.models.event import Event


class FakeScalarResult:
    def __init__(self, value):
        self.value = value

    def scalar_one_or_none(self):
        return self.value


class FakeDb:
    def __init__(self, event=None):
        self.event = event
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def flush(self):
        return None

    async def execute(self, _statement):
        return FakeScalarResult(self.event)


async def fake_align_city(city):
    if not city:
        return "unknown"
    if "上海" in city:
        return "上海"
    if "北京" in city:
        return "北京"
    return "unknown"


async def fake_encode(_text):
    return [0.0] * 768


class EventLocationPassthroughTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self._patches = [
            mock.patch.object(events_api.embedding_service, "align_city", fake_align_city),
            mock.patch.object(events_api.embedding_service, "encode", fake_encode),
            mock.patch.object(agent_chat_api.embedding_service, "align_city", fake_align_city),
            mock.patch.object(agent_chat_api.embedding_service, "encode", fake_encode),
        ]
        for patcher in self._patches:
            patcher.start()

        for module in (events_api, agent_chat_api):
            service = getattr(module, "location_extraction_service", None)
            if service is not None:
                patcher = mock.patch.object(
                    service,
                    "resolve_event_location",
                    AsyncMock(side_effect=AssertionError("二次地点抽取不应被调用")),
                )
                patcher.start()
                self._patches.append(patcher)

    def tearDown(self):
        for patcher in reversed(self._patches):
            patcher.stop()

    async def test_direct_create_event_records_only_location(self):
        db = FakeDb()
        user_id = uuid4()
        data = EventCreate(
            title="江浙沪咖啡",
            activity_type="咖啡",
            city="上海",
            location="徐汇",
        )

        event = await events_api.create_event(data=data, user_id=user_id, db=db)

        self.assertIs(event, db.added[0])
        self.assertIsNone(event.city)
        self.assertEqual(event.location, "徐汇")
        self.assertIsNone(event.city_normalized)

    async def test_direct_create_event_migrates_legacy_city_to_location(self):
        db = FakeDb()
        user_id = uuid4()
        data = EventCreate(
            title="上海咖啡",
            activity_type="咖啡",
            city="上海",
            location=None,
        )

        event = await events_api.create_event(data=data, user_id=user_id, db=db)

        self.assertIs(event, db.added[0])
        self.assertIsNone(event.city)
        self.assertEqual(event.location, "上海")
        self.assertIsNone(event.city_normalized)

    async def test_direct_update_event_records_only_location(self):
        user_id = uuid4()
        event = Event(
            user_id=user_id,
            title="上海咖啡",
            activity_type="咖啡",
            city="上海",
            location=None,
            preferences=[],
            constraints=[],
            status="pending",
        )
        db = FakeDb(event=event)
        data = EventUpdate(city=None, location="江浙沪")

        updated = await events_api.update_event(event_id=uuid4(), data=data, user_id=user_id, db=db)

        self.assertIs(updated, event)
        self.assertIsNone(event.city)
        self.assertEqual(event.location, "江浙沪")
        self.assertIsNone(event.city_normalized)

    async def test_agent_draft_create_migrates_legacy_city_into_location(self):
        db = FakeDb()
        user_id = uuid4()
        draft = {
            "title": "上海咖啡",
            "activity_type": "咖啡",
            "city": "上海",
            "location": None,
            "preferences": [],
            "constraints": [],
        }

        with mock.patch.object(agent_chat_api.ChatHistoryCache, "get_event_draft", AsyncMock(return_value=draft)), \
             mock.patch.object(agent_chat_api.ChatHistoryCache, "clear_event_draft", AsyncMock()):
            await agent_chat_api._create_event_from_draft(
                user_id=user_id,
                uid_str=str(user_id),
                db=db,
            )

        event = db.added[0]
        self.assertIsNone(event.city)
        self.assertEqual(event.location, "上海")
        self.assertIsNone(event.city_normalized)

    async def test_agent_draft_create_does_not_default_missing_location_to_current_location(self):
        db = FakeDb()
        user_id = uuid4()
        draft = {
            "title": "周六下午看电影",
            "activity_type": "看电影",
            "preferences": ["周六下午"],
            "constraints": [],
        }

        with mock.patch.object(agent_chat_api.ChatHistoryCache, "get_event_draft", AsyncMock(return_value=draft)), \
             mock.patch.object(agent_chat_api.ChatHistoryCache, "clear_event_draft", AsyncMock()):
            await agent_chat_api._create_event_from_draft(
                user_id=user_id,
                uid_str=str(user_id),
                db=db,
            )

        event = db.added[0]
        self.assertIsNone(event.city)
        self.assertIsNone(event.location)
        self.assertIsNone(event.city_normalized)

    async def test_agent_draft_create_keeps_region_location_without_city(self):
        db = FakeDb()
        user_id = uuid4()
        draft = {
            "title": "江浙沪咖啡",
            "activity_type": "咖啡",
            "city": None,
            "location": "江浙沪",
            "preferences": [],
            "constraints": [],
        }

        with mock.patch.object(agent_chat_api.ChatHistoryCache, "get_event_draft", AsyncMock(return_value=draft)), \
             mock.patch.object(agent_chat_api.ChatHistoryCache, "clear_event_draft", AsyncMock()):
            await agent_chat_api._create_event_from_draft(
                user_id=user_id,
                uid_str=str(user_id),
                db=db,
            )

        event = db.added[0]
        self.assertIsNone(event.city)
        self.assertEqual(event.location, "江浙沪")
        self.assertIsNone(event.city_normalized)

    async def test_agent_draft_update_can_clear_city_for_region_location(self):
        user_id = uuid4()
        event = Event(
            user_id=user_id,
            title="上海咖啡",
            activity_type="咖啡",
            city="上海",
            location=None,
            preferences=[],
            constraints=[],
            status="pending",
        )
        db = FakeDb(event=event)
        draft = {
            "title": "江浙沪咖啡",
            "activity_type": "咖啡",
            "city": None,
            "location": "江浙沪",
            "preferences": [],
            "constraints": [],
        }

        with mock.patch.object(agent_chat_api.ChatHistoryCache, "get_event_draft", AsyncMock(return_value=draft)), \
             mock.patch.object(agent_chat_api.ChatHistoryCache, "clear_event_draft", AsyncMock()), \
             mock.patch.object(agent_chat_api.ChatHistoryCache, "clear_editing_event", AsyncMock()):
            await agent_chat_api._update_event_from_draft(
                user_id=user_id,
                uid_str=str(user_id),
                event_id_str=str(uuid4()),
                db=db,
            )

        self.assertIsNone(event.city)
        self.assertEqual(event.location, "江浙沪")
        self.assertIsNone(event.city_normalized)


if __name__ == "__main__":
    unittest.main()
