from __future__ import annotations

import unittest

from app.services.agent_stream_parser import (
    AgentStreamParser,
    QuestionJSONStreamExtractor,
    parse_conversation_tag_payload,
    parse_draft_tag_payload,
)


class AgentStreamParserTests(unittest.TestCase):
    def test_parser_streams_reply_text_inside_reply_tag(self):
        parser = AgentStreamParser(visible_tags={"reply"})

        self.assertEqual(parser.feed("<rep"), [])
        self.assertEqual(parser.feed("ly>你好"), ["你好"])
        self.assertEqual(parser.feed("呀</reply><action>chat</action>"), ["呀"])
        self.assertEqual(parser.raw_text, "<reply>你好呀</reply><action>chat</action>")

    def test_parse_conversation_tag_payload_extracts_structured_json(self):
        payload = (
            "<reply>我先帮你确认时间。</reply>"
            "<action>clarify</action>"
            "<draft_json>{\"activity_type\":\"羽毛球\",\"preferences\":[\"女生优先\"]}</draft_json>"
            "<questions_json>[{\"id\":\"time\",\"title\":\"时间\",\"options\":[{\"id\":\"t\",\"label\":\"今晚\"}]}]</questions_json>"
        )

        result = parse_conversation_tag_payload(payload)

        self.assertEqual(result["action"], "clarify")
        self.assertEqual(result["reply"], "我先帮你确认时间。")
        self.assertEqual(result["draft"]["activity_type"], "羽毛球")
        self.assertEqual(result["questions"][0]["id"], "time")

    def test_parse_conversation_tag_payload_extracts_repeated_question_tags(self):
        payload = (
            "<reply>我先帮你确认时间。</reply>"
            "<action>clarify</action>"
            "<draft_json>{\"activity_type\":\"羽毛球\"}</draft_json>"
            "<question_json>{\"id\":\"time\",\"title\":\"时间\",\"options\":[{\"id\":\"t\",\"label\":\"今晚\"}]}</question_json>"
            "<question_json>{\"id\":\"location\",\"title\":\"地点\",\"options\":[{\"id\":\"xuhui\",\"label\":\"徐汇\"}]}</question_json>"
        )

        result = parse_conversation_tag_payload(payload)

        self.assertEqual([question["id"] for question in result["questions"]], ["time", "location"])

    def test_question_json_stream_extractor_emits_completed_question_once(self):
        extractor = QuestionJSONStreamExtractor()

        self.assertEqual(extractor.feed("<question_json>{\"id\":\"ti"), [])
        emitted = extractor.feed("me\",\"title\":\"时间\"}</question_json><question_json>{")
        self.assertEqual(emitted, [{"id": "time", "title": "时间"}])
        self.assertEqual(extractor.feed("\"id\":\"location\"}</question_json>"), [{"id": "location"}])
        self.assertEqual(extractor.feed("</question_json>"), [])

    def test_parse_conversation_tag_payload_falls_back_to_json_output(self):
        payload = (
            "{\"action\":\"chat\",\"reply\":\"能啊，测试成功。\","
            "\"draft\":{},\"questions\":[]}"
        )

        result = parse_conversation_tag_payload(payload)

        self.assertEqual(result["action"], "chat")
        self.assertEqual(result["reply"], "能啊，测试成功。")

    def test_parse_conversation_tag_payload_falls_back_to_plain_reply(self):
        result = parse_conversation_tag_payload("能啊，测试成功。")

        self.assertEqual(result["action"], "chat")
        self.assertEqual(result["reply"], "能啊，测试成功。")

    def test_parse_draft_tag_payload_extracts_reply_and_draft(self):
        payload = (
            "<draft_reply>草稿整理好了。</draft_reply>"
            "<draft_json>{\"title\":\"今晚羽毛球\",\"activity_type\":\"羽毛球\"}</draft_json>"
        )

        result = parse_draft_tag_payload(payload)

        self.assertEqual(result["reply"], "草稿整理好了。")
        self.assertEqual(result["draft"]["title"], "今晚羽毛球")


if __name__ == "__main__":
    unittest.main()
