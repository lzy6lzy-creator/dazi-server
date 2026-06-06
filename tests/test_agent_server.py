from __future__ import annotations

import unittest

from app.services.agent_server import AgentModelConfig, AgentServer


class FakeStreamResponse:
    def __init__(self, chunks):
        self.chunks = chunks
        self.status_code = 200

    def raise_for_status(self):
        return None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return None

    async def aiter_lines(self):
        for chunk in self.chunks:
            yield chunk


class FakeClient:
    def __init__(self):
        self.payloads = []
        self.is_closed = False

    def stream(self, method, url, json, **_kwargs):
        self.payloads.append((url, json))
        self.method = method
        return FakeStreamResponse([
            'data: {"choices":[{"delta":{"content":"<reply>你好"}}]}',
            'data: {"choices":[{"delta":{"content":"</reply>"}}]}',
            "data: [DONE]",
        ])

    async def aclose(self):
        self.is_closed = True


class AgentServerTests(unittest.IsolatedAsyncioTestCase):
    def test_extract_json_handles_markdown_and_embedded_payload(self):
        payload = AgentServer.extract_json('```json\n{"reply":"你好"}\n```')
        self.assertEqual(payload, {"reply": "你好"})

        embedded = AgentServer.extract_json('模型输出：{"reply":"可以"}')
        self.assertEqual(embedded, {"reply": "可以"})

    async def test_kimi_k2_payload_disables_thinking_and_uses_k2_temperature(self):
        server = AgentServer(
            conversation_config=AgentModelConfig(
                provider="kimi",
                model="kimi-k2.5",
                base_url="https://example.test/v1",
                api_key="key",
            ),
            draft_config=None,
        )
        fake = FakeClient()
        server._client = fake

        chunks = []
        async for item in server.stream_chat(
            [{"role": "user", "content": "hi"}],
            purpose="conversation",
            temperature=0.1,
            max_tokens=128,
        ):
            chunks.append(item)

        self.assertEqual(chunks, ["<reply>你好", "</reply>"])
        self.assertEqual(fake.method, "POST")
        payload = fake.payloads[0][1]
        self.assertEqual(payload["model"], "kimi-k2.5")
        self.assertEqual(payload["temperature"], 0.6)
        self.assertEqual(payload["thinking"], {"type": "disabled"})
        self.assertTrue(payload["stream"])

    async def test_deepseek_payload_disables_thinking_without_kimi_temperature_override(self):
        server = AgentServer(
            conversation_config=AgentModelConfig(
                provider="deepseek",
                model="deepseek-v4-pro",
                base_url="https://api.deepseek.com",
                api_key="key",
            ),
            draft_config=None,
        )
        fake = FakeClient()
        server._client = fake

        async for _ in server.stream_chat(
            [{"role": "user", "content": "hi"}],
            purpose="conversation",
            temperature=0.2,
            max_tokens=128,
        ):
            pass

        payload = fake.payloads[0][1]
        self.assertEqual(payload["model"], "deepseek-v4-pro")
        self.assertEqual(payload["temperature"], 0.2)
        self.assertEqual(payload["thinking"], {"type": "disabled"})


if __name__ == "__main__":
    unittest.main()
