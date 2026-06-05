from __future__ import annotations

import json
import unittest

from app.services.sse import sse_event


class SSETests(unittest.TestCase):
    def test_sse_event_formats_json_payload(self):
        text = sse_event("reply_delta", {"text": "你好"})

        self.assertEqual(text, 'event: reply_delta\ndata: {"text":"你好"}\n\n')

    def test_sse_event_escapes_newlines_inside_json(self):
        text = sse_event("reply_delta", {"text": "第一行\n第二行"})
        event, data, blank, trailing = text.split("\n")

        self.assertEqual(event, "event: reply_delta")
        self.assertTrue(data.startswith("data: "))
        self.assertEqual(json.loads(data.removeprefix("data: ")), {"text": "第一行\n第二行"})
        self.assertEqual(blank, "")
        self.assertEqual(trailing, "")


if __name__ == "__main__":
    unittest.main()
