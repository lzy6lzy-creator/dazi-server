from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.services.llm_service import LLMService


class FakeResponse:
    def __init__(self, status_code=200, payload=None, text=""):
        self.status_code = status_code
        self._payload = payload or {
            "choices": [{"message": {"content": "{\"ok\": true}"}}],
        }
        self.text = text

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("POST", "https://example.test/chat/completions")
            response = httpx.Response(self.status_code, text=self.text, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)

    def json(self):
        return self._payload


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.payloads = []
        self.is_closed = False

    async def post(self, url, json):
        self.payloads.append(json)
        return self.responses.pop(0)


class LLMServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_kimi_k2_uses_required_temperature_and_thinking_disabled(self):
        service = LLMService()
        service.model = "kimi-k2.5"
        service.base_url = "https://example.test"
        fake = FakeClient([FakeResponse()])
        service._client = fake

        await service.chat([{"role": "user", "content": "hi"}], temperature=0.1, retries=0)

        self.assertEqual(fake.payloads[0]["temperature"], 0.6)
        self.assertEqual(fake.payloads[0]["thinking"], {"type": "disabled"})

    async def test_llm_retries_429_then_succeeds(self):
        service = LLMService()
        service.model = "kimi-k2.5"
        service.base_url = "https://example.test"
        fake = FakeClient([
            FakeResponse(status_code=429, text="overloaded"),
            FakeResponse(),
        ])
        service._client = fake

        async def no_sleep(_seconds):
            return None

        with patch("app.services.llm_service.asyncio.sleep", no_sleep):
            raw = await service.chat([{"role": "user", "content": "hi"}], retries=1)

        self.assertEqual(raw, "{\"ok\": true}")
        self.assertEqual(len(fake.payloads), 2)


if __name__ == "__main__":
    unittest.main()
